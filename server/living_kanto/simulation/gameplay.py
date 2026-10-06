"""Pokémon battle, encounter and ownership orchestration over canonical deltas."""
import copy,json,random
from ..contracts.human import LegalAction
from .engine import EngineError
from ..contracts.base import content_hash
from ..mechanics.reference import normalize
from ..mechanics.encounters import select_encounter,fishing_bite
from ..mechanics.safari import enter_safari,start_safari_encounter,safari_turn,safari_observation
from ..mechanics.item_rules import (apply_item,teach_machine,trade_exchange,ItemError,item_catalog,item_effects,machine_learnsets,teach_tutor,tutor_learnsets)
from ..mechanics import BattleSession,BattleError,create_pokemon,catch_attempt,experience_reward,grant_experience,heal,evolution_options,evolve

class GameplayMixin:
    def active_battle(self,state,hid):
        bid=state.humans[hid].get('battle_id')
        return state.world_facts.get('battles',{}).get(bid) if bid else None

    def battle_actions(self,state,hid):
        safari=state.humans[hid].get('safari',{})
        if safari.get('encounter'):
            return tuple(LegalAction(action='safari_action',arguments={'choice':choice},known_consequences={'safari_only':True,'consumes_ball':choice=='ball'}) for choice in ('ball','bait','rock','run') if choice!='ball' or safari['balls']>0)
        record=self.active_battle(state,hid)
        if not record:return None
        session=BattleSession(record['session']);obs=session.observation(hid)
        if obs['submitted'] or session.ended:return ()
        req=obs['request'] or {};acts=[]
        if req.get('wait'):return ()
        if session.record.get('doubles'):
            from ..mechanics.challenges import double_turn_choices
            combinations=double_turn_choices(session,hid)
            if not combinations:return ()
            options=[[],[]]
            for combination in combinations:
                for index,choice in enumerate(combination['choices']):
                    if choice not in options[index]:options[index].append(choice)
            turns=[LegalAction(action='battle_turn',arguments=combinations[0],known_consequences={'battle_version':session.version,'two_active_slot_choices':True,'active_slot_options':options,'submit_two_choices':True,'simulator_validates_pair':True})]
            turns.extend(self.special_battle_item_actions(state,hid,session,record,combinations=combinations))
            return tuple(turns)
        forced=req.get('forceSwitch',[False])[0]
        if not forced:
            for i,m in enumerate((req.get('active') or [{}])[0].get('moves',[]),1):
                if not m.get('disabled') and m.get('pp',1)>0:acts.append(LegalAction(action='battle_move',arguments={'slot':i},known_consequences={'move':m['move'],'battle_version':session.version}))
        if not (req.get('active') or [{}])[0].get('trapped'):
            for i,p in enumerate(req.get('side',{}).get('pokemon',[]),1):
                if not p.get('active') and 'fnt' not in p.get('condition',''):acts.append(LegalAction(action='battle_switch',arguments={'slot':i},known_consequences={'battle_version':session.version}))
        if record.get('wild') and not forced:

            h=state.humans[hid]
            if not record.get('uncatchable') and (len(h['party'])<6 or len(h['box'])<420):
                for ball in ('poke_ball','great_ball','ultra_ball','master_ball','premier_ball','luxury_ball','dive_ball','net_ball','nest_ball','repeat_ball','timer_ball'):
                    if h['inventory'].get(ball,{}).get('quantity',0)>0:acts.append(LegalAction(action='catch',arguments={'ball':ball},known_consequences={'consumes':1}))
            acts.append(LegalAction(action='flee_battle',arguments={},known_consequences={'attempt_escape':True}))
        if not forced:
            acts.extend(self.inventory_actions(state,hid,battle=session))
            acts.extend(self.special_battle_item_actions(state,hid,session,record))
        return tuple(acts)

    def special_battle_item_actions(self,state,hid,session,record,*,combinations=None):
        from ..mechanics.special_items import prepare_battle_special
        request=session.observation(hid)['request'] or {}
        if not request.get('active') or request.get('wait') or any(request.get('forceSwitch',[])):return []
        actions=[]
        for item in ('poke_flute','poke_doll','fluffy_tail'):
            try:prepare_battle_special(state.humans[hid],item,wild=record.get('wild'),link_like=record.get('personal_duel',False))
            except ItemError:continue
            choices=[{'item':item}]
            if combinations is not None and item=='poke_flute':
                choices=[]
                for pair in combinations:
                    for index,choice in enumerate(pair['choices']):
                        if choice['type']!='move':continue
                        args={'item':item,'acting_slot':index+1,'partner_choice':pair['choices'][1-index]}
                        if args not in choices:choices.append(args)
            for args in choices:
                actions.append(LegalAction(action='use_field_item',arguments=args,known_consequences={'battle_turn':True,'consumes':0 if item=='poke_flute' else 1,'guaranteed_escape':item!='poke_flute','sleep_cure_both_parties':item=='poke_flute','soundproof_immune':item=='poke_flute'}))
        return actions

    def gameplay_actions(self,state,hid):
        h=state.humans[hid];acts=[]
        party=[state.pokemon[p] for p in h['party'] if p in state.pokemon]
        mid=h['map_id']
        if mid=='FuchsiaCity_SafariZone_Entrance' and not h.get('safari',{}).get('active') and h['money']>=500:
            acts.append(LegalAction(action='safari_enter',arguments={},known_consequences={'price':500,'safari_balls':30,'walking_steps':600}))
        if h.get('safari',{}).get('active') and mid.startswith('SafariZone_') and self.grass_cell(mid,h['x'],h['y']):
            acts.append(LegalAction(action='train',arguments={},known_consequences={'safari_encounter':True}))
        if party and any(p['hp']>0 for p in party):
            table=self.encounter_table(mid)
            method=self.encounter_method(state,hid)
            if table and method and any(row.get({'land':'land_mons','surf':'water_mons'}[method]) for row in table) and not mid.startswith('SafariZone_'):acts.append(LegalAction(action='train',arguments={},known_consequences={'actual_encounter':True,'method':method}))
            if self.near_water(mid,h['x'],h['y']) and any(row.get('fishing_mons') for row in table):
                for rod in ('old_rod','good_rod','super_rod'):
                    if h['inventory'].get(rod,{}).get('quantity',0)>0:acts.append(LegalAction(action='fish',arguments={'rod':rod},known_consequences={'source_rod_slots':True,'bite_chance_percent':50,'reusable_rod':True}))
            if mid=='PokemonTower_6F' and not h.get('access',{}).get('tower_marowak_defeated') and h['inventory'].get('silph_scope',{}).get('quantity',0)>0 and min(abs(h['x']-x)+abs(h['y']-y) for x,y in ((11,15),(12,16)))<=1:
                acts.append(LegalAction(action='start_ghost_battle',arguments={},known_consequences={'species':'MAROWAK','level':30,'uncatchable':True}))
            if mid in ('Route12','Route16') and h['inventory'].get('poke_flute',{}).get('quantity',0)>0:
                from .field import objects
                for obj in objects(self.maps[mid],h):
                    if obj['kind']=='snorlax' and abs(h['x']-obj['x'])+abs(h['y']-obj['y'])<=1:acts.append(LegalAction(action='start_snorlax_battle',arguments={'object_id':obj['key']},known_consequences={'species':'SNORLAX','level':30,'reusable_poke_flute':True,'source_blocker_clears_on_waking':True}))
            from ..mechanics.statics import electrode_templates
            for eid,template in electrode_templates().items():
                if template['map_id']==mid and abs(h['x']-template['x'])+abs(h['y']-template['y'])<=1 and eid not in h.get('field',{}).get('electrode_cleared',[]):acts.append(LegalAction(action='start_electrode_battle',arguments={'electrode_id':eid},known_consequences={'species':'ELECTRODE','level':template['level'],'per_trainer_source_static':True}))
            from ..mechanics.statics import static_templates
            for sid,template in static_templates().items():
                if sid=='articuno' and not {'FLAG_HIDE_SEAFOAM_B4F_BOULDER_1','FLAG_HIDE_SEAFOAM_B4F_BOULDER_2'}.issubset(set(h.get('field',{}).get('revealed_boulders',[]))):continue # Source current stops after both boulders arrive.
                if sid=='mewtwo' and not any(entry['champion_id']==hid for entry in state.world_facts.get('championship',{}).get('hall_of_fame',[])):continue # Explicit mainland postchamp adaptation replaces excluded Sevii quest.
                claim=state.world_facts.get('static_encounters',{}).get(sid,{})
                if template['map_id']==mid and abs(h['x']-template['x'])+abs(h['y']-template['y'])<=1 and claim.get('status','available')=='available':
                    acts.append(LegalAction(action='start_static_battle',arguments={'static_id':sid},known_consequences={'species':template['species'],'level':template['level'],'one_world_individual':True}))
            for other in state.humans.values():
                if other['human_id']==hid or other.get('battle_id') or other.get('activity') or other.get('service_request') or other['map_id']!=mid:continue
                if abs(other['x']-h['x'])+abs(other['y']-h['y'])>self.interaction_radius(h):continue
                if other.get('official_challenge_team'):
                    if other.get('source_office')=='fossil_researcher' and not h.get('access',{}).get('fossil_researcher_defeated'):acts.append(LegalAction(action='start_battle',arguments={'human_id':other['human_id']},known_consequences={'source_trainer':'Miguel','fossil_reward_requires_victory':True}))
                    if other.get('source_office')=='dojo_master' and not h.get('access',{}).get('dojo_master_defeated'):acts.append(LegalAction(action='start_battle',arguments={'human_id':other['human_id']},known_consequences={'source_trainer':'Koichi','dojo_reward_requires_victory':True}))
                    badge=other.get('gym_badge')
                    if badge and badge not in h['badges']:acts.append(LegalAction(action='start_battle',arguments={'human_id':other['human_id']},known_consequences={'gym':other['name'],'badge_requires_victory':True}))
        if party and 'IndigoPlateau' in mid and len(set(h['badges']))==8 and not h.get('league',{}).get('active'):
            acts.append(LegalAction(action='league_enter',arguments={},known_consequences={'five_official_battles':True}))
        if party and h.get('league',{}).get('active'):
            from ..mechanics.progression import next_league_opponent
            wanted=next_league_opponent(h)
            for other in state.humans.values():
                role=other['name'].replace(' ','').replace('.','')
                if wanted=='Champion':role='Champion' if other['human_id']==state.world_facts['championship']['current_champion'] else role
                if role==wanted and other['map_id']==mid and not other.get('battle_id') and not other.get('activity') and not other.get('service_request'):
                    acts.append(LegalAction(action='start_battle',arguments={'human_id':other['human_id']},known_consequences={'league':wanted}))
        if not h.get('battle_id'):
            from ..mechanics.held_items import holdable
            held_options=[name for name,row in h['inventory'].items() if row.get('quantity',0)>0 and name.upper() in item_catalog() and holdable(name)]
            held_options.sort(key=lambda name:(item_catalog()[name.upper()].get('holdEffect')=='HOLD_EFFECT_NONE',name))
            selected=h.get('pc_storage',{}).get('selected_pokemon')
            for pid in h['party']+([selected] if self.at_storage_pc(h) and selected in h['box'] else []):
                p=state.pokemon[pid]
                if p.get('held_item'):
                    from ..mechanics.held_items import change_held_item
                    try: change_held_item(h,p)
                    except ItemError: pass
                    else: acts.append(LegalAction(action='take_held_item',arguments={'pokemon_id':pid},known_consequences={'returns_item':p['held_item'],'same_individual':True}))
                from ..mechanics.held_items import change_held_item
                options=[]
                for name in held_options:
                    if name.upper()==p.get('held_item'):continue
                    try:change_held_item(h,p,name)
                    except ItemError:continue
                    options.append(name)
                if options:acts.append(LegalAction(action='give_held_item',arguments={'pokemon_id':pid,'item':options[0]},known_consequences={'available_items':options,'returns_current_item':p.get('held_item') or None,'validated_item_selection':True}))
        if not h.get('battle_id'):
            from ..mechanics.source_gifts import available_gifts
            for gift in available_gifts(h):acts.append(LegalAction(action='receive_source_gift',arguments={'gift_id':gift['gift_id']},known_consequences={'species':gift['species'],'level':gift['level'],'one_per_trainer':True,'source_script':gift['source_script']}))
        selected=h.get('pc_storage',{}).get('selected_pokemon')
        for pid in h['party']+([selected] if self.at_storage_pc(h) and selected in h['box'] else []):
            p=state.pokemon[pid]
            for option in evolution_options(p):acts.append(LegalAction(action='evolve',arguments={'pokemon_id':pid,'species':option},known_consequences={'same_individual':True}))
            for move in p.get('pending_moves',[]):
                if len(p['moves'])<4:acts.append(LegalAction(action='learn_move',arguments={'pokemon_id':pid,'move':move['move'],'slot':len(p['moves'])+1},known_consequences={'appends_move':True}))
                for slot in range(1,len(p['moves'])+1):acts.append(LegalAction(action='learn_move',arguments={'pokemon_id':pid,'move':move['move'],'slot':slot},known_consequences={'replaces':p['moves'][slot-1]['move']}))
        acts.extend(self.pc_actions(state,hid))
        from ..mechanics.mail import mail_actions
        acts.extend(mail_actions(state,hid,at_pc=self.at_storage_pc(h) and h.get('pc_storage',{}).get('mode')=='mail'))
        from ..mechanics.tutors import tutor_stations
        for station in tutor_stations():
            if station['map_id']!=mid or station['tutor_id'] in h.get('used_tutors',[]) or abs(h['x']-station['x'])+abs(h['y']-station['y'])>1:continue
            if station['move']=='MIMIC' and h['inventory'].get('poke_doll',{}).get('quantity',0)<1:continue
            for mon in party:
                if station['move'] not in tutor_learnsets()[mon['species']]:continue
                slots=[None] if len(mon['moves'])<4 else list(range(1,5))
                for slot in slots:
                    args={'pokemon_id':mon['pokemon_id'],'tutor_id':station['tutor_id']}
                    if slot is not None:args['replace_slot']=slot
                    try:teach_tutor(h,mon,station['move'],tutor_id=station['tutor_id'],replace_slot=slot)
                    except ItemError:continue
                    acts.append(LegalAction(action='learn_from_tutor',arguments=args,known_consequences={'move':station['move'],'one_use_per_trainer':True,'source_service':True}))
        from ..mechanics.utility_items import use_vs_seeker,use_fame_checker,use_town_map,use_teachy_tv,use_powder_jar,teachy_topics
        from .hidden_items import use_itemfinder
        for item,function in [('itemfinder',lambda:use_itemfinder(h,self.maps[mid],self.maps)),('vs_seeker',lambda:use_vs_seeker(state,h)),('fame_checker',lambda:use_fame_checker(state,h,vision_radius=self.interaction_radius(h))),('town_map',lambda:use_town_map(h,self.maps)),('powder_jar',lambda:use_powder_jar(h))]:
            try:function()
            except ItemError:continue
            acts.append(LegalAction(action='use_field_item',arguments={'item':item},known_consequences={'reusable':True,'reads_own_device':True}))
        for topic in teachy_topics(h):
            try:use_teachy_tv(h,topic)
            except ItemError:continue
            acts.append(LegalAction(action='use_field_item',arguments={'item':'teachy_tv','topic':topic},known_consequences={'reusable':True,'educational_topic':topic}))
        from ..mechanics.special_items import use_party_flute
        try:use_party_flute(h,party)
        except ItemError:pass
        else:acts.append(LegalAction(action='use_field_item',arguments={'item':'poke_flute'},known_consequences={'reusable':True,'wakes_own_party':True}))
        from ..mechanics.field_items import apply_field_item
        for item in ('repel','super_repel','max_repel','black_flute','white_flute'):
            try:apply_field_item(h,item)
            except ItemError:continue
            acts.append(LegalAction(action='use_field_item',arguments={'item':item},known_consequences={'repel_steps':item_catalog()[item.upper()]['holdEffectParam'] if item.endswith('repel') else None,'reusable':item.endswith('flute')}))
        from ..mechanics.escape import escape_destination
        destination=escape_destination(h,'ESCAPE_ROPE')
        if destination and h['inventory'].get('escape_rope',{}).get('quantity',0)>0:acts.append(LegalAction(action='use_field_item',arguments={'item':'escape_rope'},known_consequences={'consumes':1,'source_escape_destination':destination}))
        for mon in party:
            for move in ('DIG','TELEPORT'):
                destination=escape_destination(h,move)
                if destination and any(slot['move']==move for slot in mon['moves']):acts.append(LegalAction(action='use_field_move',arguments={'pokemon_id':mon['pokemon_id'],'move':move},known_consequences={'source_destination':destination,'consumes_pp':False}))
        acts.extend(self.inventory_actions(state,hid))
        acts.extend(self.trade_actions(state,hid))
        from ..mechanics.challenges import available
        from ..mechanics.utility_items import invitation_live
        offers={key:offer for key,offer in state.world_facts.get('trainer_challenges',{}).items() if invitation_live(state,offer)}
        for offer_id,offer in offers.items():
            if offer['status']=='pending' and offer['recipient']==hid:
                if available(state,offer['proposer'],hid,offer['doubles'],radius=self.interaction_radius(h),maps=self.maps):acts.append(LegalAction(action='accept_challenge',arguments={'challenge_id':offer_id},known_consequences={'challenger':offer['proposer'],'challenger_name':state.humans[offer['proposer']]['name'],'personal_parties':True,'doubles':offer['doubles'],'no_prize_or_exp':'source_link_like'}))
                acts.append(LegalAction(action='decline_challenge',arguments={'challenge_id':offer_id},known_consequences={'ends_offer':True}))
        for offer_id,offer in offers.items():
            if offer['status']=='pending' and offer['proposer']==hid:acts.append(LegalAction(action='decline_challenge',arguments={'challenge_id':offer_id},known_consequences={'withdraws_own_challenge':True}))
        if not any(o['proposer']==hid and o['status']=='pending' for o in offers.values()):
            for other in state.humans:
                for doubles in (False,True):
                    if available(state,hid,other,doubles,radius=self.interaction_radius(h),maps=self.maps):acts.append(LegalAction(action='challenge_trainer',arguments={'human_id':other,'doubles':doubles},known_consequences={'requires_other_acceptance':True,'personal_parties':True,'no_prize_or_exp':'source_link_like'}))
        return acts

    def encounter_table(self,mid):
        if not hasattr(self,'_region'):self._region=json.loads((self.content_root/'region.json').read_text())
        return [row for row in self._region['encounters'] if row['map']==mid]

    def grass_cell(self,mid,x,y):
        if not hasattr(self,'_grass'):self._grass={}
        if mid not in self._grass:
            p=self.content_root/'maps'/f'{mid}.json'
            self._grass[mid]={(c['x'],c['y']) for c in json.loads(p.read_text())['cells'] if c.get('encounter_type')==1} if p.exists() else set()
        return (x,y) in self._grass[mid]

    def gameplay_changes(self,state,hid,action,args,*,encounter_override=None):
        h=state.humans[hid];prefix=f'humans.{hid}';changes=[];rng=random.Random(state.world_facts.get('seed',1)+state.state_version*1009)
        def seth(key,value):changes.append({'op':'set','path':prefix+'.'+key,'value':value})
        def setp(p):
            for k,v in p.items():changes.append({'op':'set','path':f'pokemon.{p["pokemon_id"]}.{k}','value':v})
        battle=self.active_battle(state,hid)
        from .entity_systems import PC_ACTIONS, ITEM_TRADE_ACTIONS
        if action in {'write_mail','read_mail','mail_to_pc','mail_attach','mail_discard'}:
            from ..mechanics.mail import propose_mail
            if (action in {'mail_to_pc','mail_attach'} or 'mail_id' in args) and not self.at_storage_pc(h):
                raise EngineError('PC mailbox requires a physical PC')
            updated,mons,receipt=propose_mail(h,state.pokemon,action,args,new_mail_id=f'mail-{state.state_version}-{hid}')
            for key in ('inventory','mailbox'):
                if updated.get(key)!=h.get(key):seth(key,updated[key])
            for p in mons.values():
                setp(p)
                if 'mail' not in p:changes.append({'op':'set','path':f'pokemon.{p["pokemon_id"]}.mail','value':None})
            seth('last_mail_action',receipt)
            return changes,'human.inventory_changed',1
        if action in ('register_item','unregister_item'):
            from ..mechanics.inventory import quantity
            if action == 'register_item':
                if set(args) != {'item'} or args['item'].upper() not in item_catalog() or not item_catalog()[args['item'].upper()].get('registrability') or not quantity(h['inventory'],args['item']):
                    raise EngineError('Only an owned source registrable key item can be registered')
                seth('registered_item',args['item'].lower())
            else:
                if args: raise EngineError('Unregister takes no arguments')
                seth('registered_item',None)
            return changes,'human.inventory_changed',1
        if action in PC_ACTIONS:
            return self.pc_changes(state,hid,action,args)
        if action in ITEM_TRADE_ACTIONS:
            return self.item_trade_changes(state,hid,action,args)
        if action == 'shop_sell_page':
            if not self.shop_prices(h['map_id']) or set(args)!={'page'} or type(args['page']) is not int:
                raise EngineError('Selling page requires an available shop and integer page')
            offered=self.entity_inventory_actions(state,hid)
            if not any(a.action==action and a.arguments==args for a in offered):raise EngineError('Selling page unavailable')
            preferences=copy.deepcopy(h.get('trade_preferences',{}));preferences['sell_page']=args['page'];seth('trade_preferences',preferences)
            return changes,'human.inventory_changed',1
        if action == 'shop_sell':
            from ..mechanics.inventory import sell_items
            if not self.shop_prices(h['map_id']) or set(args) != {'item', 'quantity'} or h.get('battle_id'):
                raise EngineError('Selling requires an available shop')
            updated = sell_items(h,args['item'],args['quantity']);seth('inventory',updated['inventory']);seth('money',updated['money'])
            return changes,'human.shopped',1
        if action=='safari_enter':
            if args or not any(a.action==action for a in self.gameplay_actions(state,hid)):raise EngineError('Safari admission unavailable')
            updated=enter_safari(h);seth('money',updated['money']);seth('safari',updated['safari']);seth('map_id','SafariZone_Center');seth('x',26);seth('y',30)
            return changes,'human.entered_map',30
        if action=='safari_action':
            if set(args)!={'choice'}:raise EngineError('Invalid Safari action')
            encounter=h.get('safari',{}).get('encounter')
            if not encounter:raise EngineError('No active Safari encounter')
            pid=encounter['pokemon_id'];updated,p,result=safari_turn(h,state.pokemon[pid],args['choice'],rng)
            for key in ('safari','party','box','pokedex'):seth(key,updated[key])
            setp(p)
            if not updated['safari']['active']:seth('map_id','FuchsiaCity_SafariZone_Entrance');seth('x',4);seth('y',3)
            return changes,'human.caught_pokemon' if result['caught'] else 'battle.turn',30
        if action=='use_field_move' or (action=='use_field_item' and args.get('item')=='escape_rope'):
            from ..mechanics.escape import use_escape
            if not any(a.action==action and a.arguments==args for a in self.gameplay_actions(state,hid)):raise EngineError('Field escape intention unavailable')
            kind='ESCAPE_ROPE' if action=='use_field_item' else args['move']
            updated,receipt=use_escape(h,kind)
            if updated['map_id'] not in self.maps or not self.maps[updated['map_id']].is_walkable(updated['x'],updated['y']):raise EngineError('Source escape destination unavailable')
            for key in ('map_id','x','y','status','field','inventory','active_plan'):seth(key,updated.get(key))
            seth('last_field_escape',receipt)
            return changes,'human.field_move',5
        if action=='use_field_item' and not battle:
            if set(args)!=({'item','topic'} if args.get('item')=='teachy_tv' else {'item'}):raise EngineError('Invalid field item arguments')
            if args['item'] in ('town_map','teachy_tv','powder_jar'):
                from ..mechanics.utility_items import use_town_map,use_teachy_tv,use_powder_jar
                if args['item']=='town_map':updated,receipt=use_town_map(h,self.maps)
                elif args['item']=='teachy_tv':updated,receipt=use_teachy_tv(h,args['topic'])
                else:updated,receipt=use_powder_jar(h)
                for key,value in updated.items():
                    if h.get(key)!=value:seth(key,value)
                return changes,'human.used_item',1
            if args['item'] in ('itemfinder','vs_seeker','fame_checker'):
                from .hidden_items import use_itemfinder
                from ..mechanics.utility_items import use_vs_seeker,use_fame_checker
                if args['item']=='itemfinder':updated,receipt=use_itemfinder(h,self.maps[h['map_id']],self.maps)
                elif args['item']=='vs_seeker':
                    updated,offers,receipt=use_vs_seeker(state,h)
                    if offers!=state.world_facts.get('trainer_challenges',{}):changes.append({'op':'set','path':'world_facts.trainer_challenges','value':offers})
                else:updated,receipt=use_fame_checker(state,h,vision_radius=self.interaction_radius(h))
                for key,value in updated.items():
                    if h.get(key)!=value:seth(key,value)
                return changes,'human.used_item',1
            if args['item']=='poke_flute':
                from ..mechanics.special_items import use_party_flute
                updated,party=use_party_flute(h,[state.pokemon[pid] for pid in h['party']])
                for mon in party:setp(mon)
                return changes,'human.used_item',1
            from ..mechanics.field_items import apply_field_item
            updated,result=apply_field_item(h,args['item']);seth('inventory',updated['inventory']);seth('field_encounter',updated['field_encounter']);return changes,'human.used_item',1
        if action in {'challenge_trainer','accept_challenge','decline_challenge'}:
            if not any(a.action==action and a.arguments==args for a in self.gameplay_actions(state,hid)):raise EngineError('Challenge unavailable')
            offers=copy.deepcopy(state.world_facts.get('trainer_challenges',{}))
            if action=='challenge_trainer':
                cid=f'challenge-{state.state_version}-{hid}'
                offers[cid]={'proposer':hid,'recipient':args['human_id'],'doubles':args['doubles'],'status':'pending'}
            else:
                cid=args['challenge_id'];offer=offers[cid];offer['status']='declined' if action=='decline_challenge' else 'accepted'
                if action=='accept_challenge':
                    from ..mechanics.challenges import start_personal_duel
                    # Factory receives the pending offer; acceptance and battle are one event.
                    candidate=dict(offer,status='pending');bid=f'battle-{state.state_version}-{offer["proposer"]}'
                    session=start_personal_duel(state,candidate,rng,bid,maps=self.maps,radius=self.interaction_radius(h))
                    record={'battle_id':bid,'challenger':offer['proposer'],'opponent':hid,'wild':False,'personal_duel':True,'session':session.to_dict(),'turn':0,'outcome':None}
                    changes.append({'op':'set','path':f'world_facts.battles.{bid}','value':record})
                    for actor in (offer['proposer'],hid):changes.append({'op':'set','path':f'humans.{actor}.battle_id','value':bid})
            # Bounded live offers; accepted/declined records remain in event replay.
            pending={k:v for k,v in offers.items() if v['status']=='pending'}
            closed=[(k,v) for k,v in offers.items() if v['status']!='pending'][-100:]
            offers={**pending,**dict(closed)}
            changes.append({'op':'set','path':'world_facts.trainer_challenges','value':offers})
            return changes,'battle.started' if action=='accept_challenge' else 'world.public_event',30 if action=='accept_challenge' else 1
        if action=='learn_from_tutor':
            if battle or not any(a.action==action and a.arguments==args for a in self.gameplay_actions(state,hid)):raise EngineError('Tutor service unavailable')
            from ..mechanics.tutors import tutor_stations
            station=next(t for t in tutor_stations() if t['tutor_id']==args['tutor_id'])
            updated,p,result=teach_tutor(h,state.pokemon[args['pokemon_id']],station['move'],tutor_id=station['tutor_id'],replace_slot=args.get('replace_slot'))
            if station['move']=='MIMIC':
                inv=copy.deepcopy(h['inventory']);inv['poke_doll']['quantity']-=1;seth('inventory',inv)
            seth('used_tutors',updated['used_tutors']);setp(p);return changes,'human.party_changed',30
        if action in {'use_item','teach_machine'} and not battle:
            if set(args)-{'pokemon_id','item','move_slot','replace_slot','evolution_target'}:raise EngineError('Unknown item argument')
            pid=args.get('pokemon_id')
            if pid not in h['party']+(h['box'] if self.at_storage_pc(h) else []) or pid not in state.pokemon:raise EngineError('Pokemon not owned or stored individual requires a physical PC')
            if action=='teach_machine':
                updated,p,event=teach_machine(h,state.pokemon[pid],args.get('item',''),replace_slot=args.get('replace_slot'))
            else:
                updated,p,event=apply_item(h,state.pokemon[pid],args.get('item',''),move_slot=args.get('move_slot'),evolution_target=args.get('evolution_target'))
            seth('inventory',updated['inventory']);setp(p)
            return changes,'human.used_item' if action=='use_item' else 'human.party_changed',1
        if action in {'trade_offer','trade_accept','trade_decline'}:
            return self.trade_changes(state,hid,action,args)
        if action=='league_enter':
            if args:raise EngineError('league entry takes no arguments')
            from ..mechanics.progression import begin_league
            trainer=copy.deepcopy(h);begin_league(trainer);seth('league',trainer['league']);return changes,'league.result',1
        if action in ('give_held_item','take_held_item'):
            from ..mechanics.held_items import change_held_item
            if set(args)!=({'pokemon_id','item'} if action=='give_held_item' else {'pokemon_id'}):raise EngineError('Invalid held item arguments')
            pid=args['pokemon_id']
            if pid not in h['party']+(h['box'] if self.at_storage_pc(h) else []):raise EngineError('Held item target unavailable')
            updated,p=change_held_item(h,state.pokemon[pid],args.get('item'));setp(p);seth('inventory',updated['inventory'])
            return changes,'human.party_changed',1
        if action=='receive_source_gift':
            from ..mechanics.source_gifts import receive_gift
            updated,p=receive_gift(h,args['gift_id'],rng);setp(p)
            for key in ('party','box','pokedex','source_gifts'):seth(key,updated[key])
            return changes,'human.party_changed',30
        if action in {'evolve','learn_move','store_deposit','store_withdraw','release_pokemon'}:
            legal=self.gameplay_actions(state,hid)
            if not any(a.action==action and a.arguments==args for a in legal):raise EngineError('invalid Pokémon lifecycle choice')
            pid=args['pokemon_id'];p=copy.deepcopy(state.pokemon[pid])
            if action=='evolve':evolve(p,args['species']);setp(p);return changes,'human.party_changed',1
            if action=='learn_move':
                from ..mechanics import reference_data
                move=args['move'];pp=reference_data()['moves'][move]['pp'];newmove={'move':move,'pp':pp,'max_pp':pp};
                if args['slot']==len(p['moves'])+1:p['moves'].append(newmove)
                else:
                    from ..mechanics.item_rules import _teach
                    _teach(p,move,args['slot'])
                p['pending_moves']=[m for m in p.get('pending_moves',[]) if m['move']!=move];setp(p);return changes,'human.party_changed',1
            if action=='release_pokemon':
                from ..mechanics.storage import release_pokemon
                updated,p=release_pokemon(h,p,[state.pokemon[pid] for pid in h['party']+h['box']],simulated_time=state.simulated_time)
                seth('party',updated['party']);seth('box',updated['box']);setp(p)
                for sid,claim in state.world_facts.get('static_encounters',{}).items():
                    if claim['pokemon_id']==pid:changes.append({'op':'set','path':f'world_facts.static_encounters.{sid}','value':{**claim,'status':'released','released_by':hid,'owner_id':None,'battle_id':None}})
                return changes,'human.party_changed',1
            party=list(h['party']);box=list(h['box']);source,dest=(party,box) if action=='store_deposit' else (box,party);source.remove(pid);dest.append(pid);seth('party',party);seth('box',box);return changes,'human.stored',1
        if action in {'train','start_battle','fish','start_ghost_battle','start_static_battle','start_snorlax_battle','start_electrode_battle'}:
            if battle:raise EngineError('already in a battle')
            if not any(a.action==action and a.arguments==args for a in self.gameplay_actions(state,hid)):raise EngineError('encounter/challenge unavailable')
            bid=f'battle-{state.state_version}-{hid}';wild=action!='start_battle';opponent=None
            if wild:
                tables=self.encounter_table(h['map_id'])
                method='fish' if action=='fish' else self.encounter_method(state,hid) or 'land'
                if action=='fish' and not fishing_bite(rng):
                    seth('last_fishing',{'rod':args['rod'],'bite':False});return changes,'world.public_event',30
                if action=='start_electrode_battle':
                    from ..mechanics.statics import electrode_templates
                    template=electrode_templates()[args['electrode_id']];encounter={'species':'SPECIES_ELECTRODE','min_level':template['level'],'max_level':template['level']}
                elif action=='start_snorlax_battle':encounter={'species':'SPECIES_SNORLAX','min_level':30,'max_level':30}
                elif action=='start_static_battle':
                    from ..mechanics.statics import static_templates
                    template=static_templates()[args['static_id']];encounter={'species':'SPECIES_'+template['species'],'min_level':template['level'],'max_level':template['level']}
                elif action=='start_ghost_battle':encounter={'species':'SPECIES_MAROWAK','min_level':30,'max_level':30}
                else:encounter=encounter_override or select_encounter(tables,method,rng,rod=args.get('rod'))
                species=encounter['species'].removeprefix('SPECIES_');opponent=f'wild-{bid}';pid=f'pokemon-{bid}'
                p=create_pokemon(species,rng.randint(encounter['min_level'],encounter['max_level']),None,rng,identifier=pid)
                if action!='start_static_battle':
                    from ..mechanics.held_items import assign_wild_held_item
                    assign_wild_held_item(p,rng)
                if action=='start_static_battle':
                    claim=state.world_facts.get('static_encounters',{}).get(args['static_id'],{})
                    pid=claim.get('pokemon_id',f'pokemon-static-{args["static_id"]}')
                    if pid in state.pokemon:p=copy.deepcopy(state.pokemon[pid]);heal(p)
                    else:p['pokemon_id']=pid
                if action=='start_ghost_battle':
                    from ..mechanics.pokemon import calculate_stats,NATURES
                    p['ivs']={stat:31 for stat in p['ivs']}
                    while p['personality']%25!=12 or (p['personality']&255)>=127:p['personality']=rng.randrange(2**32)
                    p['nature']='Serious';p['gender']='F'
                    from ..mechanics.reference import data
                    abilities=data()['species']['MAROWAK']['abilities'];p['ability_slot']=p['personality']&1;p['ability']=abilities[p['ability_slot']]
                    p['stats']=calculate_stats('MAROWAK',30,p['ivs'],p['evs'],12);p['hp']=p['stats']['hp']
                setp(p)
                if h.get('safari',{}).get('active') and h['map_id'].startswith('SafariZone_'):
                    updated=start_safari_encounter(h,p);seth('safari',updated['safari']);return changes,'encounter.triggered',30
                opponent_party=[copy.deepcopy(p)];opponent_party[0]['owner_id']=opponent
            else:
                opponent=args['human_id'];o=state.humans[opponent]
                if o.get('battle_id'):raise EngineError('opponent already busy')
                championship=state.world_facts.get('championship',{})
                opponent_party=copy.deepcopy(championship['challenge_team']) if opponent==championship.get('current_champion') and championship.get('challenge_team') else [copy.deepcopy(state.pokemon[pid]) for pid in o['official_challenge_team']]
                for mon in opponent_party:heal(mon)
                changes.append({'op':'set','path':f'humans.{opponent}.battle_id','value':bid})
            own=[copy.deepcopy(state.pokemon[p]) for p in h['party']]
            own.sort(key=lambda p:p['hp']<=0)
            challenge=None
            if not wild:
                from ..mechanics.progression import next_league_opponent
                if o.get('source_office')=='fossil_researcher':challenge={'kind':'fossil','source_trainer':'Miguel'}
                elif o.get('source_office')=='dojo_master':challenge={'kind':'dojo','source_trainer':'Koichi'}
                elif o.get('gym_badge'):challenge={'kind':'gym','gym':o['name'].replace(' ','').replace('.','')}
                elif h.get('league',{}).get('active'):challenge={'kind':'league','opponent':next_league_opponent(h)}
            if challenge and challenge['kind'] in ('gym','league'):
                from ..mechanics.friendship import change_friendship
                for mon in own:change_friendship(mon,'LEAGUE_BATTLE',map_id=h['map_id']);setp(mon)
            session=BattleSession.start([{'actor_id':hid,'party':own,'badge_ids':list(h['badges'])},{'actor_id':opponent,'party':opponent_party}],seed=[rng.randrange(65536) for _ in range(4)],battle_id=bid,challenge=challenge)
            record={'battle_id':bid,'challenger':hid,'opponent':opponent,'wild':wild,'session':session.to_dict(),'turn':0,'outcome':None,'uncatchable':action=='start_ghost_battle','ghost_trial':action=='start_ghost_battle','encounter_method':method if wild else None}
            if action=='start_electrode_battle':
                field=copy.deepcopy(h.get('field',{}));field.setdefault('electrode_cleared',[]).append(args['electrode_id']);seth('field',field)
                record['electrode_id']=args['electrode_id']
            if action=='start_snorlax_battle':
                field=copy.deepcopy(h.get('field',{}));field.setdefault('snorlax_cleared',[]).append(args['object_id']);seth('field',field)
                record['snorlax_object']=args['object_id']
            if action=='start_static_battle':
                record['static_id']=args['static_id']
                if args['static_id']=='mewtwo':record['static_adaptation']='individual Hall of Fame entry replaces excluded Sevii Ruby/Sapphire completion'
                changes.append({'op':'set','path':f'world_facts.static_encounters.{args["static_id"]}','value':{'pokemon_id':pid,'status':'battling','battle_id':bid}})
            changes.append({'op':'set','path':f'world_facts.battles.{bid}','value':record});seth('battle_id',bid);return changes,'battle.started',30
        if not battle:raise EngineError('not in a battle')
        pokemon_updates={}
        pending_items={a['item']['pokemon']['pokemon_id']:a['item']['pokemon'] for a in (battle['session'].get('pending') or {}).values() if a.get('item')}
        session=BattleSession(battle['session']);record=copy.deepcopy(battle);bid=record['battle_id'];ended=False;winner=None;response=None
        if not any(a.action==action and (action=='battle_turn' or a.arguments==args) for a in (self.battle_actions(state,hid) or ())):raise EngineError('battle action unavailable')
        if action=='battle_turn' and set(args)!={'choices'}:raise EngineError('Invalid doubles turn arguments')
        if action=='use_field_item':
            from ..mechanics.special_items import prepare_battle_special
            updated,effects=prepare_battle_special(h,args['item'],wild=record.get('wild'),link_like=record.get('personal_duel',False))
            seth('inventory',updated['inventory'])
            if effects.get('guaranteed_escape'):
                ended=True;record['outcome']='fled';record['last_escape_succeeded']=True
                record['last_escape_item']=args['item'].upper()
            else:
                own=next(team for team in session.record['teams'] if team['actor_id']==hid)
                pid=next(row['pokemon_id'] for row,request in zip(own['party'],session.observation(hid)['request']['side']['pokemon']) if request.get('active'))
                response=session.submit_item(hid,state.pokemon[pid],'POKE_FLUTE',effects,expected_version=session.version,acting_slot=args.get('acting_slot',1),partner_choice=args.get('partner_choice'))
                if record['wild'] and not response['resolved']:
                    response=session.submit(record['opponent'],self.wild_choice(session,record['opponent'],rng),expected_version=session.version)
        elif action=='use_item':
            pid=args['pokemon_id'];trainer=copy.deepcopy(h)
            own=next(team for team in session.record['teams'] if team['actor_id']==hid)
            trainer['party']=[p['pokemon_id'] for p in own['party']]
            current=copy.deepcopy(state.pokemon[pid])
            context=session.item_context(hid,pid)
            updated,p,event=apply_item(trainer,current,args['item'],move_slot=args.get('move_slot'),battle=True,battle_conditions=context)
            pending_items[pid]=p
            seth('inventory',updated['inventory'])
            response=session.submit_item(hid,p,event['item'],event['battle_effects'],expected_version=session.version)
            # Persist bond/PP-Up metadata while HP/status/PP remain hidden in pending turn.
            current['friendship']=p['friendship'];setp(current)
            if record['wild'] and not response['resolved']:
                response=session.submit(record['opponent'],self.wild_choice(session,record['opponent'],rng),expected_version=session.version)
        elif action=='catch':
            pid=record['session']['teams'][1]['party'][0]['pokemon_id'];p=copy.deepcopy(state.pokemon[pid]);inv=copy.deepcopy(h['inventory']);inv[args['ball']]['quantity']-=1;seth('inventory',inv)
            result=catch_attempt(p,args['ball'].upper(),rng,turn=record['turn'],already_caught=p['species'] in h['pokedex']);record['last_catch']=result
            if result['caught']:
                p['owner_id']=hid;p['original_trainer_id']=p.get('original_trainer_id') or hid;p['ownership_history'].append(hid);p['pokeball']=args['ball'].upper();p['origin_map_id']=h['map_id'];setp(p);party=list(h['party']);box=list(h['box']);(party if len(party)<6 else box).append(pid);seth('party',party);seth('box',box);seth('pokedex',sorted(set(h['pokedex']+[p['species']])));ended=True;record['outcome']='caught'
            else:
                response=session.consume_trainer_turn(hid,self.wild_choice(session,record['opponent'],rng),expected_version=session.version)
        elif action=='flee_battle':
            own_req=session.observation(hid)['request']['side']['pokemon'];active_idx=next(i for i,p in enumerate(own_req) if p.get('active'))
            pid=[p for p in session.record['result']['pokemon'] if p['owner_id']==hid][active_idx]['pokemon_id'];own=state.pokemon[pid];wild=state.pokemon[session.record['teams'][1]['party'][0]['pokemon_id']]
            tries=record.get('escape_attempts',0);record['escape_attempts']=tries+1
            speed=own['stats']['spe'];foe_speed=wild['stats']['spe'];chance=(speed*128//max(1,foe_speed)+tries*30)%256
            escaped=own['ability']=='RUN_AWAY' or own.get('held_item')=='SMOKE_BALL' or speed>=foe_speed or chance>rng.randrange(256)
            record['last_escape_succeeded']=escaped
            if escaped:ended=True;record['outcome']='fled'
            else:response=session.consume_trainer_turn(hid,self.wild_choice(session,record['opponent'],rng),expected_version=session.version)
        else:
            response=session.submit(hid,{'type':'turn','choices':args['choices']} if action=='battle_turn' else {'type':'move' if action=='battle_move' else 'switch','slot':args['slot']},expected_version=session.version)
            if record['wild'] and not response['resolved']:
                wildobs=session.observation(record['opponent']);req=wildobs['request'] or {};available=[i for i,m in enumerate((req.get('active')or[{}])[0].get('moves',[]),1) if not m.get('disabled') and m.get('pp',1)>0]
                response=session.submit(record['opponent'],{'type':'move','slot':rng.choice(available) if available else 1},expected_version=session.version)
        if response and response['resolved']:
                record['turn']+=1
                for update in response['pokemon']:
                    pid=update['pokemon_id'];p=copy.deepcopy(pending_items.get(pid,state.pokemon[pid]));p['hp']=update['hp'];p['status']=update['status'];p['held_item']=update['held_item']
                    if not record.get('personal_duel') and p['owner_id']==record['challenger'] and state.pokemon[pid]['hp']>0 and p['hp']<=0:
                        from ..mechanics.friendship import change_friendship
                        previous=BattleSession(battle['session']);foe_request=(previous.observation(record['opponent'])['request'] or {}).get('side',{}).get('pokemon',[])
                        opponents=[mon for mon in previous.record['result']['pokemon'] if mon['owner_id']==record['opponent']]
                        levels={mon['pokemon_id']:mon['level'] for mon in previous.record['teams'][1]['party']}
                        level=max((levels[mon['pokemon_id']] for mon,entry in zip(opponents,foe_request) if entry.get('active')),default=p['level'])
                        change_friendship(p,'FAINT_LARGE' if level-p['level']>29 else 'FAINT_SMALL',map_id=h['map_id'])
                    for m,new in zip(p['moves'],update['moves']):m['pp']=new['pp'];m['max_pp']=new['max_pp']
                    pokemon_updates[pid]=p;setp(p)
                ended=session.ended;winner=session.winner;record['outcome']=winner if ended else None
        record['session']=session.to_dict()
        if response and response['resolved'] and not record.get('personal_duel'):
            challenger=record['challenger'];opponent=record['opponent']
            participants=set(record.get('participants',[]))
            prior_req=BattleSession(battle['session']).observation(challenger)['request'] or {}
            prior_result=BattleSession(battle['session']).record['result']['pokemon']
            ordered_own=[p for p in prior_result if p['owner_id']==challenger]
            for index,entry in enumerate(prior_req.get('side',{}).get('pokemon',[])):
                if entry.get('active'):participants.add(ordered_own[index]['pokemon_id'])
            record['participants']=sorted(participants)
            from ..mechanics.experience import experience_distribution,active_ids
            participation=copy.deepcopy(record.get('participants_by_foe',{}))
            for snapshot in (BattleSession(battle['session']),session):
                active_own=active_ids(snapshot,challenger)
                for foe_id in active_ids(snapshot,opponent):participation[foe_id]=sorted(set(participation.get(foe_id,[])).union(active_own))
            record['participants_by_foe']=participation
            rewarded=set(record.get('rewarded_defeats',[]))
            defeated=[p for p in record['session']['teams'][1]['party'] if pokemon_updates.get(p['pokemon_id'],state.pokemon[p['pokemon_id']])['hp']<=0 and p['pokemon_id'] not in rewarded]
            from ..mechanics.pokemon import grant_evs
            level_updates=[]
            for foe in defeated:
                current_party=[pokemon_updates.get(pid,state.pokemon[pid]) for pid in state.humans[challenger]['party']]
                awards=experience_distribution(foe,current_party,participation.get(foe['pokemon_id'],[]),challenger,trainer_battle=not record['wild'])
                record.setdefault('experience_awards',{})[foe['pokemon_id']]=awards
                for pid,reward in awards.items():
                    p=copy.deepcopy(pokemon_updates.get(pid,state.pokemon[pid]));old_level=p['level'];grant_evs(p,foe['species']);p['pending_moves']=p.get('pending_moves',[])+grant_experience(p,reward,map_id=state.humans[challenger]['map_id']);pokemon_updates[pid]=p;setp(p)
                    if p['level']!=old_level:level_updates.append(p)
                rewarded.add(foe['pokemon_id'])
            record['rewarded_defeats']=sorted(rewarded)
            if level_updates:
                latest={p['pokemon_id']:p for p in level_updates}
                session.synchronize_individuals(list(latest.values()));record['session']=session.to_dict()
        if ended:
            changes.append({'op':'set','path':f'humans.{record["challenger"]}.battle_id','value':None})
            if not record['wild']:changes.append({'op':'set','path':f'humans.{record["opponent"]}.battle_id','value':None})
            record['ended']=True
            if record.get('static_id'):
                sid=record['static_id'];pid=record['session']['teams'][1]['party'][0]['pokemon_id']
                status='caught' if record['outcome']=='caught' else 'defeated' if winner==record['challenger'] else 'available'
                changes.append({'op':'set','path':f'world_facts.static_encounters.{sid}','value':{'pokemon_id':pid,'status':status,'battle_id':None}})
            if winner==record['challenger']:
                if record.get('ghost_trial'):
                    access=copy.deepcopy(state.humans[winner].get('access',{}));access['tower_marowak_defeated']=True
                    changes.append({'op':'set','path':f'humans.{winner}.access','value':access})
                if not record['wild'] and not record.get('personal_duel'):
                    other=state.humans[record['opponent']];badge=other.get('gym_badge')
                    from ..mechanics.progression import official_prize
                    role=('Miguel' if other.get('source_office')=='fossil_researcher' else 'Koichi' if other.get('source_office')=='dojo_master' else (session.record.get('challenge') or {}).get('opponent')) or other['name'].replace(' ','').replace('.','')
                    participants=set(record.get('participants',[]))
                    amulet=any(p['pokemon_id'] in participants and p.get('held_item')=='AMULET_COIN' for p in session.record['teams'][0]['party'])
                    prize=official_prize(role,session.record['teams'][1]['party'][-1]['level'],doubles=session.record.get('doubles',False),amulet_coin=amulet)
                    record['prize_money']=prize
                    changes.append({'op':'set','path':f'humans.{winner}.money','value':min(999999,state.humans[winner]['money']+prize)})
                    if (session.record.get('challenge') or {}).get('kind') in ('dojo','fossil'):
                        access=copy.deepcopy(state.humans[winner].get('access',{}));access['fossil_researcher_defeated' if other.get('source_office')=='fossil_researcher' else 'dojo_master_defeated']=True
                        changes.append({'op':'set','path':f'humans.{winner}.access','value':access})
                    if badge:
                        # Badge only follows the canonical simulator's completed victory.
                        from ..mechanics.progression import award_gym_badge
                        trainer=copy.deepcopy(state.humans[winner]);award_gym_badge(trainer,other['name'].replace(' ','').replace('.',''),session,other['human_id'])
                        for key in ['badges','progression_battles']:changes.append({'op':'set','path':f'humans.{winner}.{key}','value':trainer[key]})
            if not record['wild'] and (session.record.get('challenge') or {}).get('kind')=='league':
                from ..mechanics.progression import record_league_result
                challenger=record['challenger'];trainer=copy.deepcopy(state.humans[challenger]);championship=copy.deepcopy(state.world_facts['championship']);eligible=[copy.deepcopy(pokemon_updates.get(pid,state.pokemon[pid])) for pid in trainer['party']]
                record_league_result(trainer,session,record['opponent'],championship,eligible_team=eligible)
                for key in ['league','progression_battles']:changes.append({'op':'set','path':f'humans.{challenger}.{key}','value':trainer[key]})
                changes.append({'op':'set','path':'world_facts.championship','value':championship})
            if winner==record['opponent'] and not record.get('personal_duel'):
                loser=record['challenger']
                recovery,receipt=self.recover_whiteout(state,loser,pokemon_updates,reason='battle_loss',battle_id=bid)
                changes.extend(recovery);record['whiteout_money_loss']=receipt['money_loss'];record['whiteout_respawn']=receipt

        changes.append({'op':'set','path':f'world_facts.battles.{bid}','value':record})
        return changes,'battle.ended' if ended else 'battle.turn',0 if response and not response['resolved'] else 30

    def recover_whiteout(self,state,hid,party_overrides=None,reason='field_poison',*,battle_id=None):
        """Source loss/heal/respawn consequence; never a staff/model choice.

        Field walking passes its newly damaged individual records so the same
        atomic receipt contains poison fainting followed by correct recovery.
        """
        from ..mechanics.progression import whiteout_loss
        trainer=state.humans[hid];overrides=party_overrides or {}
        if isinstance(overrides,list):overrides={p['pokemon_id']:p for p in overrides}
        party=[copy.deepcopy(overrides.get(pid,state.pokemon[pid])) for pid in trainer['party']]
        loss=whiteout_loss(trainer,party);station=trainer.get('last_heal_station')
        respawn_map=station['map_id'] if station else 'PalletTown_PlayersHouse_1F'
        if respawn_map not in self.maps:raise EngineError('saved whiteout checkpoint map unavailable')
        point=(8,5) if not station else (13,12) if respawn_map=='IndigoPlateau_PokemonCenter_1F' else (5,4) if respawn_map=='OneIsland_PokemonCenter_1F' else (7,4)
        changes=[]
        for mon in party:
            heal(mon)
            for key,value in mon.items():changes.append({'op':'set','path':f'pokemon.{mon["pokemon_id"]}.{key}','value':value})
        for key,value in {'money':trainer['money']-loss,'map_id':respawn_map,'x':point[0],'y':point[1],'active_plan':None,'battle_id':None,'status.surfing':False,'status.source_forced_surfing':False,'status.bicycle':False,'status.cycling_road':False,'field.flash_active':False,'status.activity':'whiteout_recovered'}.items():
            changes.append({'op':'set','path':f'humans.{hid}.{key}','value':value})
        receipt={'battle_id':battle_id,'reason':reason,'money_loss':loss,'respawn_map':respawn_map,'x':point[0],'y':point[1],'checkpoint_request_id':station.get('request_id') if station else None,'source':'pret/pokefirered/src/overworld.c:DoWhiteOut;src/heal_location.c:SetWhiteoutRespawnWarpAndHealerNpc','adaptation':'last completed physical healing; initial Pallet mother fallback when no checkpoint'}
        changes.append({'op':'set','path':f'humans.{hid}.last_whiteout','value':receipt})
        return changes,receipt

    @staticmethod
    def wild_choice(session,actor,rng):
        obs=session.observation(actor);req=obs['request'] or {}
        available=[i for i,m in enumerate((req.get('active')or[{}])[0].get('moves',[]),1) if not m.get('disabled') and m.get('pp',1)>0]
        return {'type':'move','slot':rng.choice(available) if available else 1}


    def inventory_actions(self,state,hid,*,battle=None):
        trainer=state.humans[hid];actions=[]
        if battle:
            trainer=copy.deepcopy(trainer)
            own=next(team for team in battle.record['teams'] if team['actor_id']==hid)
            trainer['party']=[p['pokemon_id'] for p in own['party']]
            ids=trainer['party']
        else:
            selected=trainer.get('pc_storage',{}).get('selected_pokemon')
            ids=trainer['party']+([selected] if self.at_storage_pc(trainer) and selected in trainer['box'] else [])
        for name,row in trainer['inventory'].items():
            quantity=row.get('quantity',0) if isinstance(row,dict) else row
            if quantity<=0:continue
            key=name.upper().removeprefix('ITEM_')
            if key not in item_catalog():continue
            machine='move' in item_catalog()[key]
            if machine and battle:continue
            for pid in ids:
                pokemon=state.pokemon[pid]
                if machine:
                    if key not in machine_learnsets()[pokemon['species']]:continue
                    choices=[None] if len(pokemon['moves'])<4 else list(range(1,5))
                    for slot in choices:
                        try:teach_machine(trainer,pokemon,key,replace_slot=slot)
                        except ItemError:continue
                        args={'pokemon_id':pid,'item':name}
                        if slot is not None:args['replace_slot']=slot
                        actions.append(LegalAction(action='teach_machine',arguments=args,known_consequences={'move':item_catalog()[key]['move'],'reusable':key.startswith('HM')}))
                elif key in item_effects():
                    effect=' '.join(item_effects()[key].values())
                    choices=list(range(1,len(pokemon['moves'])+1)) if ('ITEM4_HEAL_PP_ONE' in effect or 'ITEM4_PP_UP' in effect or 'ITEM5_PP_MAX' in effect) else [None]
                    context=battle.item_context(hid,pid) if battle else None
                    for slot in choices:
                        try:apply_item(trainer,pokemon,key,move_slot=slot,battle=bool(battle),battle_conditions=context)
                        except ItemError:continue
                        args={'pokemon_id':pid,'item':name}
                        if slot is not None:args['move_slot']=slot
                        actions.append(LegalAction(action='use_item',arguments=args,known_consequences={'consumes':0 if key.endswith('_FLUTE') else 1,'battle_turn':bool(battle)}))
        return actions

    def interaction_radius(self,h):
        return 1 if self.maps[h['map_id']].events.get('requires_flash') and not h.get('field',{}).get('flash_active') else 6

    def at_storage_pc(self,trainer):
        from .field import DIRECTIONS
        dx,dy=DIRECTIONS.get(trainer.get('facing','south'),(0,1))
        cell=self.maps[trainer['map_id']].cells.get((trainer['x']+dx,trainer['y']+dy),{})
        return cell.get('behavior')==0x83 # source MB_PC, front interaction tile.

    def start_walking_encounter(self,state,hid,encounter):
        # Internal source helper, never a model-supplied override.
        method=self.encounter_method(state,hid)
        if method is None:raise EngineError('No qualifying encounter terrain')
        field={'land':'land_mons','surf':'water_mons'}[method]
        if not any(row.get(field) and any(mon['species']==encounter['species'] and mon['min_level']<=encounter['min_level']<=encounter['max_level']<=mon['max_level'] for mon in row[field]['mons']) for row in self.encounter_table(state.humans[hid]['map_id'])):raise EngineError('Walking encounter not in source table')
        return self.gameplay_changes(state,hid,'train',{},encounter_override=encounter)

    def water_cells(self,mid):
        if not hasattr(self,'_water'):self._water={}
        if mid not in self._water:
            path=self.content_root/'maps'/f'{mid}.json'
            self._water[mid]={(c['x'],c['y']) for c in json.loads(path.read_text())['cells'] if c.get('encounter_type')==2} if path.exists() else set()
        return self._water[mid]

    def near_water(self,mid,x,y):
        water=self.water_cells(mid)
        return any((nx,ny) in water for nx,ny in ((x,y),(x-1,y),(x+1,y),(x,y-1),(x,y+1)))

    def encounter_method(self,state,hid):
        h=state.humans[hid];mid=h['map_id']
        if self.grass_cell(mid,h['x'],h['y']):return 'land'
        if (h['x'],h['y']) in self.water_cells(mid):
            surf_known=any(any(m['move']=='SURF' for m in state.pokemon[pid]['moves']) for pid in h['party'])
            if surf_known and 'soul' in h['badges']:return 'surf'
        return None
