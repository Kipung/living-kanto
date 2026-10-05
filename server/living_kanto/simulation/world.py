"""Shared world orchestration. All mutations use the canonical event/store boundary."""
from __future__ import annotations
import json, random, copy
from pathlib import Path
from collections import deque
from typing import Mapping, Any
from ..contracts import CanonicalEvent, StateUpdate, RunMetadata, WorldState
from ..contracts.base import content_hash
from ..contracts.human import LegalAction
from .engine import SimulationEngine, EngineError, StaleActionError, GENESIS_HEAD
from .maps import GameMap
from .gameplay import GameplayMixin
from .services import ServiceMixin
from . import pickups,scenarios,scheduling
from ..mechanics import BattleSession

ROLE_COUNTS = {'aspiring_trainer':30,'gym_leader':8,'elite_four':4,'initial_champion':1,'professor':1,'service_staff':20,'shop_staff':10,'worker':10,'resident':16}

class WorldEngine(ServiceMixin,GameplayMixin,SimulationEngine):
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
            if choice['action'] not in {a.action for a in self.legal_actions(state,choice['human_id'])}:raise EngineError('Batch actor is not ready for this activity')
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
        self.place_initial_population(humans)
        state=WorldState(run_id=run_id,state_version=0,state_hash='',tick=0,simulated_time=0,mode=mode,phase='paused',clock={'seconds':0},humans=humans,pokemon=pokemon,maps={k.lower():v.content_summary() for k,v in self.maps.items() if k!='pallet-town'},world_facts={'seed':seed,'rng_counter':0,'creative_modified':False,'initial_population':100,'rules':'firered-gen3','release_verified':False,'championship':{'current_champion':'human-043','hall_of_fame':[],'tenures':[]}})
        state.state_hash=state.compute_state_hash();state.verify()
        meta=RunMetadata(run_id=run_id,world_id='living-kanto',world_revision='037335f4c725d7c9aecdac87066f2002b4bd7e14',engine_version='world-0.2',code_revision='direct-build',mode=mode,created_at=self._wall_time(),population_target=100,population_actual=100,data_directory='.',content_manifest_hash=content_hash({k:v.source_sha256 for k,v in self.maps.items()}),notes='Initial officeholders are setup facts. Release evidence remains incomplete.')
        store.create_run(meta,state);store.set_status(run_id,'paused');return state

    def commit_changes(self,store,run_id,changes,*,kind,actor,explanation,provenance,expected_version,details=None):
        _,state,head=store.load_run(run_id)
        if type(expected_version) is not int or expected_version!=state.state_version: raise StaleActionError('state changed; refresh before acting')
        changes=expand_entity_sets(copy.deepcopy(changes))
        if actor in state.humans:
            changes.append({'op':'set','path':f'humans.{actor}.last_decision','value':{'action':kind,'explanation':explanation,'provenance':dict(provenance),'observation_version':expected_version}})
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
        if 'player' in state.humans and self.active_battle(state,'player') and self.battle_actions(state,'player'):
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
        obs.goals=tuple(copy.deepcopy(h.get('goals',[])))
        obs.self_state.update(self.service_private_info(state,human_id))
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
        return obs

    def legal_actions(self,state,human_id):
        battle=self.battle_actions(state,human_id)
        if battle is not None:return battle
        h=self._require_human(state,human_id)
        if scheduling.current_activity(h):
            if h.get('role')=='user_trainer':
                return (LegalAction(action='wait_until_ready',arguments={},known_consequences={'ready_at':h['ready_at']}),LegalAction(action='cancel_activity',arguments={},known_consequences={'no_completion_reward':True}))
            return ()
        if h.get('service_request'):
            # Every human may withdraw their own queued intention, including legacy self-requests.
            return (LegalAction(action='cancel_service',arguments={},known_consequences={'refund':h['service_request']['reserved_payment']}),)
        acts=list(super().legal_actions(state,human_id))
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
        mid=h['map_id']
        if h.get('role') in {'worker','shop_staff','service_staff','resident'}:
            acts.append(LegalAction(action='work',arguments={},known_consequences={'duration_seconds':3600,'pay':100}))
        if self.shop_prices(mid) and not self.sole_assigned_staff(state,human_id,mid,'shop'):

            for item,price in self.shop_prices(mid).items():
                if h['money']>=price:acts.append(LegalAction(action='shop_buy',arguments={'item':item,'quantity':1},known_consequences={'price':price}))
        if self.service_kind(mid)=='healing' and not self.sole_assigned_staff(state,human_id,mid,'healing'):acts.append(LegalAction(action='heal_party',arguments={},known_consequences={'queues_service':True,'duration_seconds':60}))
        if not h['party'] and ('OaksLab' in mid):
            for species in ['Bulbasaur','Charmander','Squirtle']:acts.append(LegalAction(action='choose_starter',arguments={'species':species},known_consequences={'level':5,'one_per_trainer':True}))
        acts.extend(self.service_actions(state,human_id))
        acts.extend(self.gameplay_actions(state,human_id))
        return tuple(acts[:128])

    def build_action_event(self,store,run_id,human_id,*,action,arguments,observation_version,expected_state_version,decision_explanation,decision_provenance,scripted_test_mind=False):
        if action in {'walk_to','travel_to','enter_map','wait','set_goal','remember','surf','stop_surf','cut','push_boulder','ride_elevator','open_card_door','journey_to','fly_to','flash','ride_bicycle','dismount_bicycle','toggle_mansion_switch','turn_to'}:
            return super().build_action_event(store,run_id,human_id,action=action,arguments=arguments,observation_version=observation_version,expected_state_version=expected_state_version,decision_explanation=decision_explanation,decision_provenance=decision_provenance,scripted_test_mind=scripted_test_mind)
        _,state,head=store.load_run(run_id)
        if scripted_test_mind:raise EngineError('scripted production minds are forbidden')
        prov=dict(decision_provenance)
        if prov.get('kind') not in {'model','user'} or (prov.get('kind')=='model' and not prov.get('model_id')):raise EngineError('missing decision provenance')
        if not decision_explanation.strip():raise EngineError('explanation required')
        if observation_version!=state.state_version or expected_state_version!=state.state_version:raise StaleActionError('stale action')
        h=self._require_human(state,human_id);args=dict(arguments)
        legal=[a for a in self.legal_actions(state,human_id) if a.action==action]
        if not legal:raise EngineError('action unavailable in this location')
        changes=[];duration=1;prefix=f'humans.{human_id}';kind='world.public_event'
        def seth(key,value):changes.append({'op':'set','path':f'{prefix}.{key}','value':value})
        if action in {'rest','work'}:
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
        elif action=='talk_to':
            if set(args)!={'human_id','text'} or not isinstance(args['text'],str) or not 0<len(args['text'])<=200:raise EngineError('invalid conversation')
            target=args['human_id']
            if not any(a.arguments['human_id']==target for a in legal):raise EngineError('person not nearby')
            relation=dict(h.get('relationships',{}).get(target,{}));relation['familiarity']=relation.get('familiarity',0)+1
            seth(f'relationships.{target}',relation);seth(f'memories.{len(h["memories"])}',{'text':args['text'],'kind':'subjective','other':target,'time':state.simulated_time});seth('status.social',min(100,h['status'].get('social',75)+10));duration=30;kind='human.talked'
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
        elif action in {'shop_buy','heal_party','serve_customer','cancel_service'}:
            extra,kind,duration=self.service_changes(state,human_id,action,args);changes.extend(extra)
        elif action=='choose_starter':
            if not any(a.arguments==args for a in legal):raise EngineError('invalid starter')
            from ..mechanics import create_pokemon
            pid=f'pokemon-{human_id}-starter';p=create_pokemon(args['species'],5,human_id,random.Random(state.world_facts['seed']+state.state_version),identifier=pid)
            changes.append({'op':'set','path':f'pokemon.{pid}','value':p});seth('party',[pid]);seth('pokedex',[p['species']]);kind='human.party_changed'
        else:
            try:extra,kind,duration=self.gameplay_changes(state,human_id,action,args);changes.extend(extra)
            except (ValueError,KeyError) as exc:raise EngineError(str(exc)) from exc
        # Build without committing; RuntimeController owns the one commit boundary.
        changes,completions=self.resolve_time_effects(state,changes,duration)
        changes.append({'op':'advance_clock','seconds':duration});seth('last_decision',{'action':action,'arguments':args,'explanation':decision_explanation,'provenance':prov,'observation_version':observation_version})
        changes=expand_entity_sets(changes)
        new=state.with_advanced_version(changes);idx=state.state_version;eid=f'evt-{idx}-{content_hash(changes)[:24]}'
        update=StateUpdate(run_id=run_id,event_id=eid,event_index=idx,prior_state_version=idx,prior_state_hash=state.state_hash,previous_head=head,state_version=new.state_version,state_hash=new.state_hash,changes=changes).validate()
        event=CanonicalEvent(run_id=run_id,event_id=eid,event_index=idx,state_version=new.state_version,previous_head=head,event_kind=kind,tick=new.tick,simulated_time=new.simulated_time,real_wall_time=self._wall_time(),causation={'human_id':human_id,'action':action,'action_arguments':args,'decision_explanation':decision_explanation,'provenance':prov},affected=[{'human_id':human_id}],before={},after={},deterministic_inputs={'activity_completions':completions} if completions else {},transaction={'kind':'state_update',**update.to_dict()},visibility={'public':True}).validate()
        return event,new


def expand_entity_sets(changes):
    result=[]
    for change in changes:
        parts=change.get('path','').split('.')
        if change.get('op')=='set' and len(parts)==2 and parts[0] in {'humans','pokemon','npcs','maps','items','economies','factions'}:
            for key,value in change['value'].items():result.append({'op':'set','path':change['path']+'.'+key,'value':value})
        else:result.append(change)
    return result
