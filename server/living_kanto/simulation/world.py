"""Shared world orchestration. All mutations use the canonical event/store boundary."""
from __future__ import annotations
import json, random, copy
from pathlib import Path
from collections import deque
from typing import Mapping, Any
from ..contracts import CanonicalEvent, StateUpdate, RunMetadata, WorldState
from ..contracts.base import content_hash
from ..contracts.human import LegalAction
from .engine import SimulationEngine, EngineError, StaleActionError, GENESIS_HEAD, first_starter_eligible
from .maps import GameMap
from .gameplay import GameplayMixin
from .services import ServiceMixin
from .entity_systems import EntitySystemsMixin, PC_ACTIONS, ITEM_TRADE_ACTIONS
from .shared_clock import SharedClockMixin
from . import pickups,scenarios,scheduling,workplaces,source_npcs
from ..mechanics import BattleSession

ROLE_COUNTS = {'aspiring_trainer':30,'gym_leader':8,'elite_four':4,'initial_champion':1,'professor':1,'service_staff':20,'shop_staff':10,'worker':10,'resident':16}

class WorldEngine(SharedClockMixin,EntitySystemsMixin,ServiceMixin,GameplayMixin,SimulationEngine):
    def __init__(self, content_root):
        self.content_root = Path(content_root)
        maps = {}
        for p in sorted((self.content_root/'maps').glob('*.json')):
            try: maps[p.stem] = GameMap.from_content(p.stem, p)
            except (ValueError, KeyError): continue
        if 'PalletTown' not in maps: raise EngineError('Pallet Town content is missing')
        # Preserve legacy run identifiers, but normalize source warp targets.
        maps['pallet-town'] = maps['PalletTown']
        for gm in maps.values():
            for cell,target in list(gm.exits.items()):
                if target.startswith('MAP_'):
                    gm.exits[cell] = next((key for key in maps if key.replace('_','').lower()==target[4:].replace('_','').lower()),target)
        super().__init__(maps)

    def commit(self,store,event):
        provenance=event.causation.get('provenance',{})
        with store._lock:
            status=store.get_status(event.run_id)
            permitted=provenance.get('kind') in {'user','creative'}
            if status!='running' and permitted:store.set_status(event.run_id,'running')
            try:return super().commit(store,event)
            finally:
                if status!='running' and permitted:store.set_status(event.run_id,status)

    def resolve_time_effects(self,state,changes,duration):
        """Resolve elapsed needs/completions in the action's canonical receipt."""
        if any(c.get('op')=='advance_clock' for c in changes):raise EngineError('time effects require changes before clock advance')
        preview=state.apply_changes(expand_entity_sets(changes))
        deltas,receipts=scheduling.due_completions(preview,state.simulated_time+duration)
        # The helper resolves intermediate boundaries before calculating its
        # values. Only final writes are needed in the authoritative transaction.
        final_writes={}
        for delta in deltas:final_writes[delta['path']]=delta
        compact=[]
        for receipt in receipts:
            saved=preview.humans[receipt['human_id']].get('activity',{})
            row={k:copy.deepcopy(v) for k,v in receipt.items() if k!='decision_explanation'}
            row['decision_explanation_preview']=receipt['decision_explanation'][:160]
            row['intent_hash']=content_hash(saved)
            compact.append(row)
            final_writes[f'humans.{row["human_id"]}.last_activity']={'op':'set','path':f'humans.{row["human_id"]}.last_activity','value':row}
        return list(changes)+list(final_writes.values()),compact

    def build_activity_batch_event(self,store,run_id,choices):
        _,state,head=store.load_run(run_id)
        for choice in choices:
            if choice['action'] not in {a.action for a in self.legal_actions_for_validation(state,choice['human_id'],choice['action'])}:raise EngineError('Batch actor is not ready for this activity')
        event,new=scheduling.build_batch_event(state,head,choices,self._wall_time())
        event.causation['runtime_order']=[c['human_id'] for c in choices]
        event.validate()
        return event,new

    def advance_activities(self,store,run_id,*,allow_future=False):
        """One persisted engine boundary; never manufactures a human choice."""
        with store._lock:
            _,state,_=store.load_run(run_id);due=scheduling.next_due(state)
            if due is None or (due>state.simulated_time and not allow_future):return None
            target=max(state.simulated_time,due)
            changes,receipts=self.resolve_time_effects(state,[],target-state.simulated_time)
            if not receipts:return None
            changes.append({'op':'advance_clock','seconds':target-state.simulated_time})
            status=store.get_status(run_id);store.set_status(run_id,'running')
            try:
                return self.commit_changes(store,run_id,changes,kind='world.public_event',actor='engine',explanation='Complete recorded daily activity at its engine readiness boundary',provenance={'kind':'engine','engine_continuation':True},expected_version=state.state_version,details={'activity_completions':receipts})[0]
            finally:store.set_status(run_id,status)

    def place_initial_population(self,humans):
        """Nearest distinct on-foot source cells; never changes existing saves."""
        from .field import actor_map,WATER
        occupied={}
        for hid,h in sorted(humans.items()):
            mid=h['map_id'];source=self.maps[mid];game_map=actor_map(source,h)
            used=occupied.setdefault(mid,set())
            objects={(obj['x'],obj['y']) for obj in source.events.get('object_events',[]) if 'x' in obj and 'y' in obj}
            post=h.get('workplace',{}).get('service_post')
            if post and (h['x'],h['y']) == (post['x'],post['y']) and game_map.can_stand(h['x'],h['y']) and (h['x'],h['y']) not in used:
                used.add((h['x'],h['y'])); continue
            blocked=used|objects;near=(h['x'],h['y']);available=[]
            for y in range(source.height):
                for x in range(source.width):
                    behavior=int(source.cells.get((x,y),{}).get('behavior',0))
                    if (x,y) in blocked or not game_map.is_walkable(x,y) or behavior in WATER or 0x30<=behavior<=0x3f:continue
                    if not any((dest:=game_map.step_destination((x,y),direction)) is not None and dest not in blocked for direction in ['north','south','east','west']):continue
                    available.append((abs(x-near[0])+abs(y-near[1]),y,x))
            if not available:raise EngineError(f'No unique on-foot initial placement available in {mid}')
            _,y,x=min(available);h['x'],h['y']=x,y;used.add((x,y))

    def initialize(self, store, run_id, seed=1, mode='observer'):
        if type(seed) is not int: raise EngineError('seed must be an integer')
        path=self.content_root/'population.json'
        pop=json.loads(path.read_text())['humans']
        if len(pop)!=100 or len({h['human_id'] for h in pop})!=100: raise EngineError('content must contain exactly 100 distinct humans')
        humans={}
        for i,raw in enumerate(pop):
            h=copy.deepcopy(raw); hid=h['human_id']
            mid=h.get('map_id','PalletTown')
            if mid not in self.maps: mid='PalletTown'
            gm=self.maps[mid]; x,y=gm.first_open_cell((4+i%8,5+i//8%8))
            humans[hid]={**h,'map_id':mid,'x':x,'y':y,'facing':'south','money':h.get('money',3000),'badges':[], 'party':[], 'box':[], 'inventory':{k.lower():{'item_id':k.lower(),'quantity':v} for k,v in h.get('inventory',{}).items()},'goal':{'text':(h.get('goals') or [{'text':'Explore and meet people'}])[0]['text']},'memories':{str(n):m for n,m in enumerate(h.get('memories',[]))},'relationships':h.get('relationships',{}),'last_entry':{},'status':{'energy':h.get('needs',{}).get('energy',100),'social':h.get('needs',{}).get('social',75),'activity':'ready'},'pokedex':[], 'setup_role':h.get('role','resident')}
        self.setup_services(humans)
        from ..mechanics.progression import official_team,GYMS
        pokemon={}
        dojo=humans['human-075'];dojo.update({'name':'Koichi','source_office':'dojo_master','map_id':'SaffronCity_Dojo','x':6,'y':5})
        dojo['biography']='Koichi works in Saffron’s Fighting Dojo. Their office and source challenge team are declared initial circumstances; they have earned no simulated badges or victories.'
        dojo['responsibilities']=list(dojo.get('responsibilities',[]))+[{'kind':'dojo_master','map_id':'SaffronCity_Dojo','source':'declared_setup'}]
        researcher=humans['human-076'];researcher.update({'name':'Miguel','source_office':'fossil_researcher','map_id':'MtMoon_B2F','x':13,'y':11})
        researcher['biography']='Miguel studies fossils in Mt. Moon. Their research office and source challenge team are declared initial circumstances, without earned victories or badges.'
        for hid,h in humans.items():
            if h['role'] in {'gym_leader','elite_four','initial_champion'} or h.get('source_office') in {'dojo_master','fossil_researcher'}:
                role='Miguel' if h.get('source_office')=='fossil_researcher' else 'Koichi' if h.get('source_office')=='dojo_master' else h['name'].replace(' ','').replace('.','') if h['role']!='initial_champion' else 'Champion'
                team=official_team(role,hid,random.Random(seed+int(hid.split('-')[-1])))
                for mon in team:pokemon[mon['pokemon_id']]=mon
                h['official_challenge_team']=[mon['pokemon_id'] for mon in team]
                personal=[]
                for mon in team:
                    own=copy.deepcopy(mon);own['pokemon_id']=mon['pokemon_id'].replace('official-','personal-',1);own['official_challenge_team']=False;pokemon[own['pokemon_id']]=own;personal.append(own['pokemon_id'])
                h['party']=personal
                if role in GYMS:h['gym_badge']=GYMS[role]
        # Declared setup individuals: half of aspiring trainers already own a
        # common Route 1 companion; this is not earned simulation progress.
        aspiring=sorted(hid for hid,h in humans.items() if h['role']=='aspiring_trainer')
        route_tables=self.encounter_table('Route1')
        eligible=[row for table in route_tables for row in table['land_mons']['mons'] if row['min_level']<=5<=row['max_level']]
        if eligible and 'Route1' in self.maps:
            from ..mechanics import create_pokemon
            route=self.maps['Route1']
            for index,hid in enumerate(aspiring[len(aspiring)//2:]):
                rng=random.Random(seed+10000+index)
                source=eligible[index%len(eligible)]
                pid=f'pokemon-{hid}-setup';species=source['species'].removeprefix('SPECIES_')
                mon=create_pokemon(species,5,hid,rng,identifier=pid)
                mon['origin']={'kind':'declared_initial_setup','map_id':'Route1','encounter_species':source['species'],'level':5,'reference':'pret-pokefirered/wild_encounters'}
                pokemon[pid]=mon;human=humans[hid];human['party']=[pid];human['pokedex']=[mon['species']]
                x,y=route.first_open_cell((4+index%6,6+index//6))
                human.update({'map_id':'Route1','x':x,'y':y,'setup_companion':{'pokemon_id':pid,'source':'declared_initial_setup','earned':False}})
        workplaces.initialize(self, humans)
        self.place_initial_population(humans)
        state=WorldState(run_id=run_id,state_version=0,state_hash='',tick=0,simulated_time=0,mode=mode,phase='paused',clock={'seconds':0},humans=humans,pokemon=pokemon,maps={k.lower():v.content_summary() for k,v in self.maps.items() if k!='pallet-town'},world_facts={'seed':seed,'rng_counter':0,'creative_modified':False,'initial_population':100,'rules':'firered-gen3','release_verified':False,'championship':{'current_champion':'human-043','hall_of_fame':[],'tenures':[]}})
        state.npcs=source_npcs.initial_actors(self,humans)
        state.world_facts['source_npc_policy']={'version':'source-residents-v1','population':len(state.npcs),'movement':'source_positions_with_courtesy'}
        state.state_hash=state.compute_state_hash();state.verify()
        meta=RunMetadata(run_id=run_id,world_id='living-kanto',world_revision='037335f4c725d7c9aecdac87066f2002b4bd7e14',engine_version='world-0.2',code_revision='direct-build',mode=mode,created_at=self._wall_time(),population_target=100,population_actual=100,data_directory='.',content_manifest_hash=content_hash({k:v.source_sha256 for k,v in self.maps.items()}),notes='Initial officeholders are setup facts. Release evidence remains incomplete.')
        store.create_run(meta,state);store.set_status(run_id,'paused');return state

    def commit_changes(self,store,run_id,changes,*,kind,actor,explanation,provenance,expected_version,details=None):
        _,state,head=store.load_run(run_id)
        if type(expected_version) is not int or expected_version!=state.state_version: raise StaleActionError('state changed; refresh before acting')
        changes=expand_entity_sets(copy.deepcopy(changes))
        if actor in state.humans:
            changes.append({'op':'set','path':f'humans.{actor}.last_decision','value':{'action':kind,'explanation':explanation,'provenance':dict(provenance),'observation_version':expected_version}})
        from .task_continuity import settle_changes
        changes += settle_changes(state,changes)
        result=state.with_advanced_version(changes)
        idx=state.state_version;eid=f'evt-{idx}-{content_hash(changes)[:24]}'
        update=StateUpdate(run_id=run_id,event_id=eid,event_index=idx,prior_state_version=state.state_version,prior_state_hash=state.state_hash,previous_head=head,state_version=result.state_version,state_hash=result.state_hash,changes=changes).validate()
        event=CanonicalEvent(run_id=run_id,event_id=eid,event_index=idx,state_version=result.state_version,previous_head=head,event_kind=kind,tick=result.tick,simulated_time=result.simulated_time,real_wall_time=self._wall_time(),causation={'human_id':actor,'decision_explanation':explanation,'provenance':dict(provenance),**(details or {})},affected=[{'human_id':actor}],before={},after={},deterministic_inputs={'seed':state.world_facts.get('seed',1)},transaction={'kind':'state_update',**update.to_dict()},visibility={'public':True}).validate()
        self.commit(store,event);return event,result

    def add_player(self,store,run_id,expected_version):
        _,state,_=store.load_run(run_id)
        if expected_version!=state.state_version:raise StaleActionError('stale player creation')
        if 'player' in state.humans:return state
        gm=self.maps['PalletTown'];x,y=gm.first_open_cell((6,6))
        h={'human_id':'player','name':'You','role':'user_trainer','map_id':'PalletTown','x':x,'y':y,'facing':'south','money':3000,'badges':[],'party':[],'box':[],'inventory':{},'goal':{},'memories':{},'relationships':{},'last_entry':{},'status':{'energy':100,'social':75},'pokedex':[]}
        return self.commit_changes(store,run_id,[{'op':'set','path':'humans.player','value':h}],kind='human.created',actor='user',explanation='Create optional user trainer',provenance={'kind':'user'},expected_version=expected_version)[1]

    def runtime_blocker(self,state):
        if 'player' in state.humans and self.active_battle(state,'player') and (self.legal_actions(state,'player') if self.shared_clock_enabled(state) else self.battle_actions(state,'player')):
            return {'human_id':'player','reason':'Player battle input required'}
        return None

    def observation_for(self,state,human_id):
        obs=super().observation_for(state,human_id);h=state.humans[human_id]
        obs.party=tuple(copy.deepcopy(state.pokemon[pid]) for pid in h['party'] if pid in state.pokemon)
        obs.self_state.update({'role':h.get('role','resident'),'personality':h.get('personality',{}),'biography':h.get('biography',''),'needs':h.get('status',{}),'relationships':h.get('relationships',{})})
        for key,default in [('interests',[]),('ambitions',[]),('preferences',{}),('responsibilities',[]),('active_plan',None),('memory_summary',''),('source_office',None)]:
            obs.self_state[key]=copy.deepcopy(h.get(key,default))
        def compact_fact(value):
            if isinstance(value,dict):return {str(k):compact_fact(v) for k,v in list(value.items())[:32]}
            if isinstance(value,(list,tuple)):return [compact_fact(v) for v in value[-32:]]
            if isinstance(value,str):return value[:2000]
            return copy.deepcopy(value)
        last=h.get('last_decision') or {}
        obs.self_state['last_decision']={key:compact_fact(last[key]) for key in ['action','arguments','explanation','observation_version'] if key in last}
        for key in ['last_service','last_heal_station','last_whiteout','access','field','scenarios','league','used_tutors','collected_source_items','acquisition','last_acquisition','activity','ready_at','last_activity']:
            obs.self_state[key]=compact_fact(h.get(key,{} if key!='used_tutors' else []))
        obs.self_state['recent_progression_battles']=list(h.get('progression_battles',[]))[-8:]
        obs.self_state['caught_species']=list(h.get('pokedex',[]))[-151:]
        from .individual_life import life_view
        obs.self_state['individual_life']=life_view(h)
        from ..mechanics.pc import layout
        saved_pc = layout(h)
        obs.self_state['pc_storage'] = {key:value for key,value in saved_pc.items() if key != 'placements'}
        obs.self_state['pc_storage']['boxes'] = [{'box':box,'name':saved_pc['names'].get(str(box),f'Box {box}'),
            'occupied':sum(place['box']==box for place in saved_pc['placements'].values()),'capacity':30} for box in range(1,15)]
        obs.self_state['stored_pokemon'] = [{key:copy.deepcopy(state.pokemon[pid].get(key)) for key in ('pokemon_id','species','level','held_item')}
            for pid,place in saved_pc['placements'].items() if place['box'] == saved_pc['current_box']]
        selected_pc = saved_pc.get('selected_pokemon')
        if selected_pc in h['box']: obs.self_state['selected_stored_pokemon'] = copy.deepcopy(state.pokemon[selected_pc])
        obs.self_state['registered_item'] = h.get('registered_item')
        obs.self_state['pc_items'] = copy.deepcopy(h.get('pc_items', {}))
        obs.self_state['mailbox'] = copy.deepcopy(h.get('mailbox', {}))
        obs.self_state['last_mail_action'] = copy.deepcopy(h.get('last_mail_action', {}))
        obs.self_state['trade_preferences'] = copy.deepcopy(h.get('trade_preferences', {}))
        for key in ('field_steps','utility_items','collected_hidden_items','last_hidden_item','last_itemfinder','last_vs_seeker','last_fame_checker','last_town_map','last_teachy_tv','last_powder_jar','last_renewable_items'):
            obs.self_state[key] = copy.deepcopy(h.get(key, [] if key == 'collected_hidden_items' else {}))
        obs.self_state['trade_offers'] = [copy.deepcopy(offer) for offer in state.world_facts.get('trade_offers', {}).values()
            if human_id in (offer['proposer'], offer['recipient']) and offer['phase'] in ('offered', 'countered')]
        from .memory_retrieval import retrieve
        obs.memories,recall=retrieve(h,state.simulated_time,[a.get('human_id') for a in obs.visible_actors])
        obs.self_state['memory_recall']=recall
        obs.goals=tuple(copy.deepcopy(h.get('goals',[])))
        obs.self_state.update(self.service_private_info(state,human_id))
        radius=self.interaction_radius(h)
        obs.self_state['nearby_source_residents']=[{'npc_id':npc['npc_id'],'name':npc.get('name','Local resident'),'x':npc['x'],'y':npc['y'],'source_resident':True} for npc in source_npcs.visible_actors(state,h['map_id']) if abs(npc['x']-h['x'])+abs(npc['y']-h['y'])<=radius][:24]
        obs.self_state['workplace_duty'] = workplaces.duty_info(state, human_id)
        record=self.active_battle(state,human_id)
        if record:
            session=BattleSession(record['session'])
            obs.revealed_battle_info=session.observation(human_id)
            own=next(team for team in session.record['teams'] if team['actor_id']==human_id)
            party=copy.deepcopy(own['party'])
            updates={p['pokemon_id']:p for p in session.record['result']['pokemon'] if p['owner_id']==human_id}
            for mon in party:
                update=updates.get(mon['pokemon_id'])
                if update:
                    mon['hp']=update['hp'];mon['status']=update['status']
                    for move,resolved in zip(mon['moves'],update['moves']):
                        move['pp']=resolved['pp'];move['max_pp']=resolved['max_pp']
            obs.party=tuple(party)
            obs.self_state['challenge_team_active']=human_id==record['opponent'] and not record['wild']
        from .care import observation_view
        obs.self_state['care_summary'] = observation_view(self,state,human_id,obs.party,obs.legal_actions)
        from .behavior_feedback import observation_view as behavior_view
        obs.self_state['behavior_feedback'] = behavior_view(self,state,human_id,obs.legal_actions)
        from .conversation import conversation_view
        obs.self_state['conversation_context'] = conversation_view(h)
        from .task_continuity import view as continuity_view
        obs.self_state['continuity'] = continuity_view(h,obs.legal_actions,obs.self_state['workplace_duty'])
        from .decision_awareness import observation_view as awareness_view
        obs.self_state['decision_awareness'] = awareness_view(h, [a.get('human_id') for a in obs.visible_actors])
        from .cognition import private_view
        obs.self_state["cognition"] = private_view(h)
        return obs

    def legal_actions(self,state,human_id,*,include_routes=True):
        if self.shared_clock_enabled(state):
            shared=self.shared_legal_override(state,human_id)
            if shared is not None:return shared
        battle=self.battle_actions(state,human_id)
        if battle is not None:return battle
        h=self._require_human(state,human_id)
        if scheduling.current_activity(h):
            if h.get('role')=='user_trainer':
                return (LegalAction(action='wait_until_ready',arguments={},known_consequences={'ready_at':h['ready_at']}),LegalAction(action='cancel_activity',arguments={},known_consequences={'no_completion_reward':True}))
            return ()
        if h.get('service_request'):
            # Staying in the queue and leaving it are both real choices.
            return (LegalAction(action='wait_for_service',arguments={},known_consequences={'retains_queue_position':True,'duration_seconds':30,'healing_requires_staff_service':True}),
                    LegalAction(action='cancel_service',arguments={},known_consequences={'refund':h['service_request']['reserved_payment']}))
        acts=list(super().legal_actions(state,human_id,include_routes=include_routes))
        acts.extend(source_npcs.courtesy_actions(self,state,human_id))
        for npc in source_npcs.visible_actors(state,h['map_id']):
            if npc.get('dialogue') and abs(npc['x']-h['x'])+abs(npc['y']-h['y'])<=1:
                acts.append(LegalAction(action='speak_to_source_resident',arguments={'npc_id':npc['npc_id']},known_consequences={'source_dialogue':True,'duration_seconds':10}))
        acts.extend(pickups.actions(h,self.maps[h['map_id']]))
        acts.extend(scenarios.scenario_actions(state,h,self.maps))
        from ..mechanics.acquisition import acquisition_actions
        acts.extend(acquisition_actions(h))
        acts.extend([LegalAction(action='rest',arguments={},known_consequences={'energy_recovered':20,'duration_seconds':300})])
        radius=1 if self.maps[h['map_id']].events.get('requires_flash') and not h.get('field',{}).get('flash_active') else 6
        for hid,o in sorted(state.humans.items()):
            if hid!=human_id and o.get('map_id')==h['map_id'] and abs(o['x']-h['x'])+abs(o['y']-h['y'])<=radius:
                acts.append(LegalAction(action='talk_to',arguments={'human_id':hid,'text':'<message, <=200 chars>'},known_consequences={'duration_seconds':30}))
                if sum(a.action=='talk_to' for a in acts)>=64:break
        from .conversation import reply_options
        acts.extend(reply_options(h, acts))
        mid=h['map_id']
        if h.get('role') in {'worker','shop_staff','service_staff','resident'}:
            acts.append(LegalAction(action='work',arguments={},known_consequences={'duration_seconds':3600,'pay':100}))
        if self.shop_prices(mid) and not self.sole_assigned_staff(state,human_id,mid,'shop'):

            for item,price in self.shop_prices(mid).items():
                if h['money']>=price:
                    from ..mechanics.inventory import add
                    try: add(h['inventory'],item,1)
                    except ValueError: continue
                    acts.append(LegalAction(action='shop_buy',arguments={'item':item,'quantity':1},known_consequences={'price':price}))
        if self.service_kind(mid)=='healing' and not self.sole_assigned_staff(state,human_id,mid,'healing'):acts.append(LegalAction(action='heal_party',arguments={},known_consequences={'queues_service':True,'duration_seconds':60,'price':0,'on_staff_service':{'party_hp':'full','status':'cleared','move_pp':'full','fainted_pokemon':'revived'},'requires_staff_decision':True}))
        if first_starter_eligible(state,h) and ('OaksLab' in mid):
            for species in ['Bulbasaur','Charmander','Squirtle']:acts.append(LegalAction(action='choose_starter',arguments={'species':species},known_consequences={'level':5,'one_per_trainer':True}))
        acts.extend(self.service_actions(state,human_id))
        acts.extend(self.gameplay_actions(state,human_id))
        acts.extend(self.entity_inventory_actions(state, human_id))
        if include_routes: acts.extend(self.pc_approach_actions(state, human_id))
        from .care import route_actions
        for suggestion in route_actions(self,state,human_id,include_routes):
            acts=[a for a in acts if (a.action,a.arguments)!=(suggestion.action,suggestion.arguments)]
            acts.append(suggestion)
        from .pokemon_sources import route_actions as pokemon_routes
        acts.extend(pokemon_routes(self,state,human_id,acts,include_routes))
        acts = workplaces.actions(self, state, human_id, acts, include_routes)
        # Bounded menus preserve service, care and a range of alternatives.
        replies = {'respond_to', 'trade_accept', 'trade_decline', 'item_trade_accept', 'item_trade_decline'}
        basic={'wait','rest','walk_to','turn_to','enter_map','cancel_service','cancel_movement','leave_service_post'}
        conversations={id(a) for a in [a for a in acts if a.action=='talk_to'][:4]}
        def priority(a):
            destination=a.known_consequences.get('destination_kind')
            if a.action in {'serve_customer','take_service_post'} or destination=='workplace':return 0
            if a.action=='heal_party' or destination=='healing':return 1
            if a.action in basic or id(a) in conversations:return 2
            if destination in {'starter','training','pokemon_source'} or a.action in {'choose_starter','receive_source_gift','train','challenge_trainer','accept_challenge','decline_challenge','start_battle','league_enter'}:return 2
            if a.action in replies:return 3
            if a.action in {'shop_sell','shop_sell_page'}:return 4
            if a.action in PC_ACTIONS or destination=='PC' or a.known_consequences.get('opens_interaction')=='PC':return 5
            if a.action=='release_pokemon':return 6
            return 7
        acts.sort(key=priority)
        from .task_continuity import options as task_options
        ordinary = acts[:120]
        return tuple(ordinary + task_options(h, ordinary))

    def legal_actions_for_validation(self,state,human_id,action):
        from inspect import signature
        if 'include_routes' not in signature(self.legal_actions).parameters:
            return self.legal_actions(state,human_id)
        if action in {'travel_to','journey_to','plan_next_step'}:
            return self.legal_actions(state,human_id)
        actions=self.legal_actions(state,human_id,include_routes=False)
        # Full observations cap the menu at 128 entries. Omitting route entries
        # must not expose an action that the full current menu would have hidden.
        # Conservatively include local approaches, direct geographic neighbors,
        # nearby services, starter/active journeys, PC/care and workplace routes.
        # A short validation menu must not expose choices truncated in the full one.
        h=state.humans[human_id];gm=self.maps[h['map_id']]
        neighbors=len({target for target in gm.exits.values() if target in self.maps})
        omitted_upper_bound=(16+32+4+neighbors+7+len(gm.events.get('mansion_switch',{}).get('statues',[])) if gm.source_revision else 0)+7
        cutoff=max(0,120-omitted_upper_bound)
        if any(a.action==action for a in actions[cutoff:]):
            return self.legal_actions(state,human_id)
        return actions

    def build_action_event(self,store,run_id,human_id,*,action,arguments,observation_version,expected_state_version,decision_explanation,decision_provenance,scripted_test_mind=False,defer_time=False):
        if action in {'walk_to','travel_to','enter_map','wait','set_goal','remember','set_aspiration','set_commitment','complete_commitment','abandon_commitment','surf','stop_surf','cut','push_boulder','ride_elevator','open_card_door','journey_to','fly_to','flash','ride_bicycle','dismount_bicycle','toggle_mansion_switch','turn_to'}:
            return super().build_action_event(store,run_id,human_id,action=action,arguments=arguments,observation_version=observation_version,expected_state_version=expected_state_version,decision_explanation=decision_explanation,decision_provenance=decision_provenance,scripted_test_mind=scripted_test_mind,defer_time=defer_time)
        _,state,head=store.load_run(run_id)
        if scripted_test_mind:raise EngineError('scripted production minds are forbidden')
        prov=dict(decision_provenance)
        if prov.get('kind') not in {'model','user'} or (prov.get('kind')=='model' and not prov.get('model_id')):raise EngineError('missing decision provenance')
        if not decision_explanation.strip():raise EngineError('explanation required')
        if observation_version!=state.state_version or expected_state_version!=state.state_version:raise StaleActionError('stale action')
        h=self._require_human(state,human_id);args=dict(arguments)
        legal=[a for a in self.legal_actions_for_validation(state,human_id,action) if a.action==action]
        if not legal:raise EngineError('Trade individual changed or partner unavailable' if action=='trade_accept' else 'action unavailable in this location')
        changes=[];duration=1;prefix=f'humans.{human_id}';kind='world.public_event'
        def seth(key,value):changes.append({'op':'set','path':f'{prefix}.{key}','value':value})
        from .task_continuity import TASK_ACTIONS, action_changes as task_changes
        if action in TASK_ACTIONS:
            changes.extend(task_changes(self,state,human_id,action,args,decision_explanation,prov));kind='human.goal_set'
        elif action in {'take_service_post','leave_service_post'}:
            changes.extend(workplaces.post_changes(self,state,human_id,action,args));duration=5;kind='human.moved'
        elif action in {'rest','work'}:
            try:extra,activity=scheduling.start_activity(state,human_id,action,args,prov,decision_explanation)
            except scheduling.ScheduleError as exc:raise EngineError(str(exc)) from exc
            changes.extend(extra);duration=0
        elif action=='wait_until_ready':
            if args:raise EngineError('wait_until_ready takes no arguments')
            try:duration=scheduling.wait_target(state,human_id)-state.simulated_time
            except scheduling.ScheduleError as exc:raise EngineError(str(exc)) from exc
        elif action=='cancel_activity':
            if args:raise EngineError('cancel_activity takes no arguments')
            try:extra,receipt=scheduling.cancel_activity(state,human_id)
            except scheduling.ScheduleError as exc:raise EngineError(str(exc)) from exc
            changes.extend(extra);duration=0
            seth('last_activity_cancellation',receipt)
        elif action=='ask_resident_to_make_way':
            if not any(a.arguments==args for a in legal):raise EngineError('Source resident passage unavailable')
            extra,plan=source_npcs.courtesy_changes(self,state,human_id,args)
            changes.extend(extra);duration=1;kind='human.moved'
            if plan['human_to']!=plan['human_from']:
                from .movement_encounters import intercept
                evidence={'map_id':h['map_id'],'start':plan['human_from'],'steps':[plan['human_to']],'duration_seconds':1}
                changes,duration,evidence,encounter_kind=intercept(self,state,human_id,'travel_to',{'x':plan['human_to'][0],'y':plan['human_to'][1]},prov,decision_explanation,evidence,changes,duration)
                if encounter_kind:kind=encounter_kind
                plan={**plan,'walking':evidence}
            seth('last_source_passage',plan)
        elif action=='speak_to_source_resident':
            if not any(a.arguments==args for a in legal):raise EngineError('Source resident is not nearby')
            npc=state.npcs[args['npc_id']];dialogue=npc['dialogue']
            from .conversation import next_memory_slot
            receipt={'npc_id':npc['npc_id'],'text':dialogue['text'],'source':dialogue,'time':state.simulated_time,'kind':'source_dialogue'}
            seth(f'memories.{next_memory_slot(h.get("memories",{}))}',receipt)
            seth('last_source_dialogue',receipt);duration=10;kind='human.talked'
        elif action in {'talk_to','respond_to'}:
            if action == 'respond_to':
                from .conversation import validate_reply
                validate_reply(h, args, legal)
            if set(args)!=( {'human_id','text','speech_id','disposition'} if action == 'respond_to' else {'human_id','text'} ) or not isinstance(args['text'],str) or not 0<len(args['text'])<=200:raise EngineError('invalid conversation')
            target=args['human_id']
            if not any(a.arguments.get('human_id')==target for a in legal):raise EngineError('person not nearby')
            relation=dict(h.get('relationships',{}).get(target,{}));relation['familiarity']=relation.get('familiarity',0)+1
            from .conversation import next_memory_slot
            speech_id=f'speech-{state.state_version}-{human_id}'
            speech={'text':args['text'],'time':state.simulated_time,'speech_id':speech_id,
                    'source_state_version':state.state_version,'source':'recorded_speech'}
            if action == 'respond_to':
                speech.update(reply_to=args['speech_id'], response_disposition=args['disposition'], semantic_answer_verified=False)
            seth(f'relationships.{target}',relation)
            seth(f'memories.{next_memory_slot(h.get("memories",{}))}',
                 {**speech,'kind':'subjective','other':target,'direction':'spoken'})
            listener=state.humans[target]
            changes.append({'op':'set','path':f'humans.{target}.memories.{next_memory_slot(listener.get("memories",{}))}',
                'value':{**speech,'kind':'heard_speech','other':human_id,'speaker_name':h['name'],'direction':'heard'}})
            seth('status.social',min(100,h['status'].get('social',75)+10));duration=30;kind='human.talked'
        elif action=='use_scenario':
            try:effect=scenarios.scenario_effects(state,h,self.maps,args)
            except scenarios.ScenarioError as exc:raise EngineError(str(exc)) from exc
            changes.extend(effect['changes']);duration=effect['duration'];kind='world.public_event'
            seth(f'scenarios.receipts.{effect["scenario_id"]}',{k:effect[k] for k in ['scenario_id','source','adaptation']})
        elif action in {'acquire_key_gift','choose_fossil','submit_fossil','collect_revived_fossil','buy_coins','redeem_prize'}:
            from ..mechanics.acquisition import acquisition_effects,AcquisitionError
            try:updated,mon,receipt=acquisition_effects(h,action,args,random.Random(state.world_facts['seed']+state.state_version))
            except AcquisitionError as exc:raise EngineError(str(exc)) from exc
            for key in ('inventory','acquisition','money','party','box','pokedex'):
                if updated.get(key)!=h.get(key):seth(key,updated[key])
            if mon:changes.append({'op':'set','path':f'pokemon.{mon["pokemon_id"]}','value':mon})
            seth('last_acquisition',receipt);duration=30;kind='human.inventory_changed'
        elif action=='pick_up_item':
            try:changes.extend(pickups.changes(h,self.maps[h['map_id']],args))
            except ValueError as exc:raise EngineError(str(exc)) from exc
            kind='human.inventory_changed'
        elif action in {'shop_buy','heal_party','serve_customer','cancel_service','wait_for_service'}:
            extra,kind,duration=self.service_changes(state,human_id,action,args);changes.extend(extra)
        elif action=='choose_starter':
            if not first_starter_eligible(state,h) or 'OaksLab' not in h['map_id']:raise EngineError('Starter already claimed or unavailable in this location')
            if not any(a.arguments==args for a in legal):raise EngineError('invalid starter')
            from ..mechanics import create_pokemon
            pid=f'pokemon-{human_id}-starter';p=create_pokemon(args['species'],5,human_id,random.Random(state.world_facts['seed']+state.state_version),identifier=pid)
            changes.append({'op':'set','path':f'pokemon.{pid}','value':p});seth('party',[pid]);seth('pokedex',sorted(set(h.get('pokedex',[])+[p['species']])));kind='human.party_changed'
        else:
            try:extra,kind,duration=self.gameplay_changes(state,human_id,action,args);changes.extend(extra)
            except (ValueError,KeyError) as exc:raise EngineError(str(exc)) from exc
        # Validate all authoritative bag gains, including held-item returns,
        # service deliveries, pickups, source gifts and entity barter.
        from ..mechanics.inventory import validate_gains
        inventories = {actor: human.get('inventory', {}) for actor, human in state.humans.items()}
        for change in changes:
            path = change.get('path', '').split('.')
            if change.get('op') == 'set' and len(path) == 3 and path[0] == 'humans' and path[2] == 'inventory':
                try: validate_gains(inventories.get(path[1], {}), change['value'])
                except ValueError as exc: raise EngineError(str(exc)) from exc
                inventories[path[1]] = change['value']
        # Build without committing; RuntimeController owns the one commit boundary.
        changes,completions=self.resolve_time_effects(state,changes,duration) if not defer_time else (changes,[])
        changes.append({'op':'advance_clock','seconds':0 if defer_time else duration});seth('last_decision',{'action':action,'arguments':args,'explanation':decision_explanation,'provenance':prov,'observation_version':observation_version})
        from .entity_systems import map_visit_changes
        changes.extend(map_visit_changes(state,changes))
        changes=expand_entity_sets(changes)
        if not defer_time:
            from .individual_life import record_decision
            record_decision(h,human_id,action,args,decision_explanation,state.simulated_time,changes,source_state_version=state.state_version)
            from .task_continuity import settle_changes
            changes += settle_changes(state,changes)
        new=state.with_advanced_version(changes);idx=state.state_version;eid=f'evt-{idx}-{content_hash(changes)[:24]}'
        update=StateUpdate(run_id=run_id,event_id=eid,event_index=idx,prior_state_version=idx,prior_state_hash=state.state_hash,previous_head=head,state_version=new.state_version,state_hash=new.state_hash,changes=changes).validate()
        event=CanonicalEvent(run_id=run_id,event_id=eid,event_index=idx,state_version=new.state_version,previous_head=head,event_kind=kind,tick=new.tick,simulated_time=new.simulated_time,real_wall_time=self._wall_time(),causation={'human_id':human_id,'action':action,'action_arguments':args,'decision_explanation':decision_explanation,'provenance':prov},affected=[{'human_id':actor} for actor in sorted({human_id}|{c['path'].split('.')[1] for c in changes if c.get('path','').startswith('humans.')})]+[{'npc_id':npc} for npc in sorted({c['path'].split('.')[1] for c in changes if c.get('path','').startswith('npcs.')})],before={},after={},deterministic_inputs={'duration_seconds':duration,**({'activity_completions':completions} if completions else {})},transaction={'kind':'state_update',**update.to_dict()},visibility={'public':True}).validate()
        return event,new


def expand_entity_sets(changes):
    result=[]
    for change in changes:
        parts=change.get('path','').split('.')
        if change.get('op')=='set' and len(parts)==2 and parts[0] in {'humans','pokemon','npcs','maps','items','economies','factions'}:
            for key,value in change['value'].items():result.append({'op':'set','path':change['path']+'.'+key,'value':value})
        else:result.append(change)
    return result
