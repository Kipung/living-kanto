"""Accepted intents advance on one persisted shared clock, without model calls.

Legacy manual command timing remains unchanged until explicit activation.
Source forced warp scripts remain atomic transfers with recorded duration; their
walking approach and normal/forced tile paths are individually scheduled.
"""
import copy,random
from ..contracts import CanonicalEvent,StateUpdate
from ..contracts.base import content_hash
from ..contracts.human import LegalAction
from .engine import EngineError,StaleActionError,ACTION_SECONDS
from .field import actor_map,permission,WATER,DIRECTIONS
from .pathfinding import shortest_path
from .routeplanner import plan_journey
from .maps import resolve_transfer,MapLoadError
from .access import AccessDenied
from .field_scripts import transition_effects
from .movement_encounters import intercept
from . import scheduling

class SharedClockMixin:
    @staticmethod
    def shared_clock_enabled(state):return bool(state.world_facts.get('shared_clock',{}).get('enabled'))

    def activate_shared_clock(self,store,run_id):
        _,s,_=store.load_run(run_id)
        if self.shared_clock_enabled(s):return None
        changes=[{'op':'set','path':'world_facts.shared_clock','value':{'enabled':True,'activated_at':s.simulated_time,'activated_version':s.state_version+1,'tile_seconds':ACTION_SECONDS}}]
        for hid,h in sorted(s.humans.items()):
            plan=h.get('active_plan')
            if not plan or plan.get('kind')!='journey':continue
            steps=self._plan_movement(s,hid,'journey_to',{'map_id':plan['destination_map']})
            intent={'kind':'scheduled_movement','intent_id':f'legacy-movement-{s.state_version}-{hid}','action':'journey_to','arguments':{'map_id':plan['destination_map']},'explanation':plan['explanation'],'provenance':plan['provenance'],'accepted_at':s.simulated_time,'accepted_state_version':plan['accepted_state_version'],'next_due_at':s.simulated_time+1,'cursor':0,'steps':steps,'paused_for_battle':bool(h.get('battle_id'))}
            changes.extend([{'op':'set','path':f'humans.{hid}.movement_intent','value':intent},{'op':'set','path':f'humans.{hid}.active_plan','value':None}])
        status=store.get_status(run_id);store.set_status(run_id,'running')
        try:return self.commit_changes(store,run_id,changes,kind='world.shared_clock_activated',actor='engine',explanation='Enable shared-clock accepted-intent execution; migrate existing accepted journeys',provenance={'kind':'engine'},expected_version=s.state_version)[0]
        finally:store.set_status(run_id,status)

    def shared_legal_override(self,state,hid):
        h=state.humans[hid]
        if h.get('movement_intent') and not h.get('battle_id'):
            if h['movement_intent'].get('forced_movement'):return ()
            return (LegalAction(action='cancel_movement',arguments={},known_consequences={'retains_reached_position':True}),)
        if h.get('ready_at',0)>state.simulated_time and not h.get('activity') and not h.get('service_request'):return ()
        return None

    def shared_actor_ready(self,state,hid):
        h=state.humans[hid]
        if h.get('movement_intent') and not h.get('battle_id'):return False
        if h.get('activity') or h.get('ready_at',0)>state.simulated_time:return False
        if h.get('service_request'):return True  # Explicit cancellation remains a real human choice.
        if h.get('battle_id'):
            battle=state.world_facts.get('battles',{}).get(h['battle_id'])
            if not battle:return False
            session=battle['session']
            return not battle.get('outcome') and hid not in session.get('pending',{})
        return True

    @staticmethod
    def _actor_dependency(state,hid):
        h=state.humans[hid]
        # Clock-derived needs/bookkeeping do not invalidate an in-flight mind.
        keys=('map_id','x','y','facing','party','box','inventory','money','badges','goal','memories','field','access','activity','service_request','movement_intent','battle_id')
        owned={pid:state.pokemon[pid] for pid in h.get('party',[])+h.get('box',[]) if pid in state.pokemon}
        return content_hash({'actor':{k:h.get(k) for k in keys},'traversal_status':{k:h.get('status',{}).get(k) for k in ('surfing','source_forced_surfing','bicycle')},'pokemon':owned})

    def capture_decision_boundary(self,state,hid):
        observation=self.observation_for(state,hid)
        token={'actor':self._actor_dependency(state,hid),'targets':{other:content_hash({'map_id':h.get('map_id'),'x':h.get('x'),'y':h.get('y'),'party':h.get('party'),'battle_id':h.get('battle_id'),'activity':h.get('activity'),'service_request':h.get('service_request')}) for other,h in state.humans.items() if other!=hid},'queue_heads':{mid:content_hash(q[0]) for mid,q in state.world_facts.get('service_queues',{}).items() if q},'original_observation_hash':content_hash(observation.to_dict())}
        if state.humans[hid].get('battle_id'):
            from ..mechanics import BattleSession
            b=state.world_facts['battles'][state.humans[hid]['battle_id']]
            token['battle_request']=content_hash(BattleSession(b['session']).observation(hid))
        return observation,token

    def _validate_boundary(self,state,hid,choice,token):
        if token.get('actor')!=self._actor_dependency(state,hid):raise StaleActionError('local actor dependency changed')
        args=choice.get('arguments',{});action=choice['action']
        target=args.get('human_id')
        if target and target in token.get('targets',{}):
            h=state.humans.get(target,{})
            current=content_hash({k:h.get(k) for k in ('map_id','x','y','party','battle_id','activity','service_request')})
            if current!=token['targets'][target]:raise StaleActionError('local interaction target changed')
        if action=='serve_customer':
            mid=state.humans[hid]['map_id'];queue=self.service_queue(state,mid)
            if not queue or token.get('queue_heads',{}).get(mid)!=content_hash(queue[0]):raise StaleActionError('local service queue head changed')
        if 'battle_request' in token:
            from ..mechanics import BattleSession
            b=state.world_facts['battles'][state.humans[hid]['battle_id']]
            if token['battle_request']!=content_hash(BattleSession(b['session']).observation(hid)):raise StaleActionError('own battle request changed')

    def _shared_event(self,state,head,changes,*,kind,causation,details=None):
        from .world import expand_entity_sets
        changes=expand_entity_sets(changes)
        # apply_changes already constructs and validates an independent state.
        # Preserve the prior-hash gate, then advance its version in place rather
        # than copying the entire validated world into/from another plain dict.
        state.verify();new=state.apply_changes(copy.deepcopy(changes));new.state_hash='';new.state_version=state.state_version+1;new.validate();new.state_hash=new.compute_state_hash()
        idx=state.state_version;eid=f'evt-{idx}-{content_hash(changes)[:24]}'
        update=StateUpdate(run_id=state.run_id,event_id=eid,event_index=idx,prior_state_version=idx,prior_state_hash=state.state_hash,previous_head=head,state_version=new.state_version,state_hash=new.state_hash,changes=changes).validate()
        event=CanonicalEvent(run_id=state.run_id,event_id=eid,event_index=idx,state_version=new.state_version,previous_head=head,event_kind=kind,tick=new.tick,simulated_time=new.simulated_time,real_wall_time=self._wall_time(),causation=causation,affected=[{'human_id':hid} for hid in sorted({c['path'].split('.')[1] for c in changes if c.get('path','').startswith('humans.')})],before={},after={},deterministic_inputs=details or {},transaction={'kind':'state_update',**update.to_dict()},visibility={'public':True}).validate()
        return event,new

    def build_revalidated_action_event(self,store,run_id,hid,choice,original_observation_version,dependency_token,provenance):
        _,s,head=store.load_run(run_id);self._validate_boundary(s,hid,choice,dependency_token)
        prov={**provenance,'original_observation_version':original_observation_version,'original_observation_hash':dependency_token['original_observation_hash'],'validation_boundary_version':s.state_version}
        action=choice['action'];args=choice.get('arguments',{});explanation=choice.get('decision_explanation','Accepted human intention')
        if not self.shared_clock_enabled(s):return self.build_action_event(store,run_id,hid,action=action,arguments=args,observation_version=s.state_version,expected_state_version=s.state_version,decision_explanation=explanation,decision_provenance=prov)
        if prov.get('kind') not in ('user','model') or (prov.get('kind')=='model' and not prov.get('model_id')):raise EngineError('accepted intent requires human provenance')
        if action=='cancel_movement':
            if args or not s.humans[hid].get('movement_intent') or s.humans[hid]['movement_intent'].get('forced_movement'):raise EngineError('no accepted movement to cancel')
            changes=[{'op':'set','path':f'humans.{hid}.movement_intent','value':None}];kind='human.movement_cancelled';details={}
        elif action in ('walk_to','travel_to','journey_to','enter_map'):
            if not self.shared_actor_ready(s,hid):raise EngineError('actor already executing an accepted intention')
            if action not in {a.action for a in self.legal_actions(s,hid)}:raise EngineError('movement action unavailable')
            steps=self._plan_movement(s,hid,action,args)
            intent={'kind':'scheduled_movement','intent_id':f'movement-{s.state_version}-{hid}','action':action,'arguments':copy.deepcopy(args),'explanation':explanation,'provenance':prov,'accepted_at':s.simulated_time,'accepted_state_version':s.state_version,'next_due_at':s.simulated_time+ACTION_SECONDS,'cursor':0,'steps':steps,'paused_for_battle':False}
            changes=[{'op':'set','path':f'humans.{hid}.movement_intent','value':intent}];kind='human.movement_started';details={'accepted_movement':{'human_id':hid,'intent_id':intent['intent_id'],'step_count':len(steps)}}
        else:
            event,_=self.build_action_event(store,run_id,hid,action=action,arguments=args,observation_version=s.state_version,expected_state_version=s.state_version,decision_explanation=explanation,decision_provenance=prov,defer_time=True)
            changes=copy.deepcopy(event.transaction['changes']);duration=event.deterministic_inputs.get('duration_seconds',0);changes=[c for c in changes if c.get('op')!='advance_clock'];kind=event.event_kind;details={**event.deterministic_inputs,'short_action_timing':{'effective_at':s.simulated_time,'busy_until':s.simulated_time+duration,'adaptation':'validated short-action effects at acceptance; shared-clock actor cooldown'}}
            for change in changes:
                value=change.get('value')
                if isinstance(value,dict) and isinstance(value.get('completed_at'),int) and value['completed_at']>s.simulated_time:
                    value['busy_until']=value['completed_at'];value['completed_at']=s.simulated_time;value['effective_at']=s.simulated_time
            if duration:changes.append({'op':'set','path':f'humans.{hid}.ready_at','value':s.simulated_time+duration})
            preview=s.apply_changes(changes)
            participants={hid}
            if action=='serve_customer':
                queue=self.service_queue(s,s.humans[hid]['map_id'])
                if queue:participants.add(queue[0]['human_id'])
            for bid,before_battle in s.world_facts.get('battles',{}).items():
                after_battle=preview.world_facts.get('battles',{}).get(bid,{})
                if after_battle.get('turn')!=before_battle.get('turn') or after_battle.get('outcome')!=before_battle.get('outcome'):
                    participants.update(actor for actor in (before_battle['challenger'],before_battle['opponent']) if actor in s.humans)
            for bid,new_battle in preview.world_facts.get('battles',{}).items():
                if bid not in s.world_facts.get('battles',{}):participants.update(actor for actor in (new_battle['challenger'],new_battle['opponent']) if actor in s.humans)
            if duration:
                for actor in participants:changes.append({'op':'set','path':f'humans.{actor}.ready_at','value':s.simulated_time+duration})
            for actor in participants:
                before=s.humans[actor];after=preview.humans[actor]
                if before.get('battle_id') and not after.get('battle_id') and after.get('movement_intent'):
                    intent=copy.deepcopy(after['movement_intent'])
                    if after.get('last_whiteout')!=before.get('last_whiteout') or intent['cursor']>=len(intent['steps']):intent=None
                    else:intent.update(next_due_at=s.simulated_time+ACTION_SECONDS,paused_for_battle=False)
                    changes.append({'op':'set','path':f'humans.{actor}.movement_intent','value':intent})
        changes.append({'op':'set','path':f'humans.{hid}.last_decision','value':{'action':action,'arguments':args,'explanation':explanation,'provenance':prov,'observation_version':original_observation_version}})
        return self._shared_event(s,head,changes,kind=kind,causation={'human_id':hid,'action':action,'action_arguments':args,'decision_explanation':explanation,'provenance':prov,'observation_version':original_observation_version},details=details)

    def _plan_movement(self,state,hid,action,args):
        h=state.humans[hid];m=actor_map(self.maps[h['map_id']],h);surfing=bool(h.get('status',{}).get('surfing')) and (permission(state,h,'SURF') or h.get('status',{}).get('source_forced_surfing',False))
        if action=='enter_map':
            if set(args)!={'map_id'} or m.exit_target(h['x'],h['y'])!=args['map_id']:raise EngineError('source exit unavailable')
            return [{'kind':'transfer','map_id':h['map_id'],'source':[h['x'],h['y']],'destination_map':args['map_id']}]
        if action=='walk_to':
            if set(args)!={'direction'} or args['direction'] not in DIRECTIONS:raise EngineError('invalid walking direction')
            path=m.step_path((h['x'],h['y']),args['direction'],surfing=surfing)
            if not path:raise EngineError('walking destination blocked')
            return [{'kind':'tile','map_id':h['map_id'],'position':list(p),'facing':args['direction']} for p in path]
        if action=='travel_to':
            if set(args)!={'x','y'} or any(type(args[k])is not int for k in args):raise EngineError('travel destination requires integer coordinates')
            try:path=shortest_path(m,(h['x'],h['y']),(args['x'],args['y']),surfing=surfing)
            except ValueError as exc:raise EngineError(str(exc)) from exc
            if not path:raise EngineError('already at destination')
            return [{'kind':'tile','map_id':h['map_id'],'position':list(p)} for p in path]
        if set(args)!={'map_id'}:raise EngineError('journey requires destination map')
        try:segments=plan_journey(self.maps,h,args['map_id'],state=state)
        except ValueError as exc:raise EngineError(str(exc)) from exc
        steps=[]
        for segment in segments:
            steps.extend({'kind':'tile','map_id':segment['map_id'],'position':p} for p in segment['steps'])
            steps.append({'kind':'transfer','map_id':segment['map_id'],'source':segment['source_exit'],'destination_map':segment['destination_map']})
        return steps

    def _forced_context(self,h,intent,game_map,point):
        """Persist cartridge lastSpinTile momentum until STOP or collision.

        Reference: field_player_avatar.c TryUpdatePlayerSpinDirection and
        DoForcedMovement. Currents instead end when leaving a current tile.
        Older saves infer missing typed metadata once from accepted past steps.
        """
        spin={0x54:'east',0x55:'west',0x56:'north',0x57:'south'}
        current={0x50:'east',0x51:'west',0x52:'north',0x53:'south'}
        mode=intent.get('forced_mode');direction=intent.get('forced_direction')
        if 'forced_mode' not in intent:
            last=None
            for past in intent['steps'][:intent.get('cursor',0)] if 'steps' in intent else []:
                if past['kind']!='tile':mode=direction=None;last=None;continue
                source=self.maps[past['map_id']];position=tuple(past['position']);behavior=int(source.cells.get(position,{}).get('behavior',0));last=(source,position)
                if behavior in spin:mode,direction='spin',spin[behavior]
                elif behavior in current:mode,direction='current',current[behavior]
                elif behavior==0x58 or mode=='current':mode=direction=None
            if last and mode and direction and last[0]._step_basic(last[1],direction,surfing=bool(h.get('status',{}).get('surfing')) or bool(h.get('status',{}).get('source_forced_surfing'))) is None:mode=direction=None
        behavior=int(game_map.cells.get(tuple(point),{}).get('behavior',0))
        before=mode is not None or behavior in spin or behavior in current
        if behavior in spin:mode,direction='spin',spin[behavior]
        elif behavior in current:mode,direction='current',current[behavior]
        elif behavior==0x58 or mode=='current':mode=direction=None
        if mode and direction and game_map._step_basic(tuple(point),direction,surfing=bool(h.get('status',{}).get('surfing')) or bool(h.get('status',{}).get('source_forced_surfing'))) is None:mode=direction=None
        return before,mode,direction

    def _ordinary_tile_effects(self,state,hid,intent,cell,evidence,changes,rng,forced_context=None):
        """Reuse pure source counters without copying immutable route/history.

        Encounter terrain stays on the existing interceptor. Poison whiteout
        also falls back to it with RNG restored, preserving its exact recovery.
        """
        from ..mechanics.field_steps import field_steps
        from ..mechanics.encounters import walking_encounter
        h=state.humans[hid]
        compact={key:h[key] for key in ('human_id','map_id','field_steps','field_encounter','battle_id','safari') if key in h}
        compact.update(x=evidence['steps'][0][0],y=evidence['steps'][0][1])
        party=[state.pokemon[pid] for pid in h.get('party',[]) if pid in state.pokemon]
        before_rng=rng.getstate()
        before,mode,direction=forced_context if forced_context is not None else self._forced_context(h,intent,actor_map(self.maps[h['map_id']],h),evidence['steps'][0])
        actor,party,blackout=field_steps(compact,party,rng,forced=before)
        if blackout:
            rng.setstate(before_rng)
            return None
        actor,hit=walking_encounter(actor,cell,self.encounter_table(h['map_id']),party,rng,surfing=h.get('status',{}).get('surfing',False),bicycle=h.get('status',{}).get('bicycle',False))
        if hit:
            rng.setstate(before_rng)
            return None
        for mon in party:
            original=state.pokemon[mon['pokemon_id']]
            for key,value in mon.items():
                if original.get(key)!=value:changes.append({'op':'set','path':f"pokemon.{mon['pokemon_id']}.{key}",'value':value})
        changes.extend([{'op':'set','path':f'humans.{hid}.field_steps','value':actor.get('field_steps',{})},{'op':'set','path':f'humans.{hid}.field_encounter','value':actor.get('field_encounter',{})}])
        return changes,{**evidence,'forced_movement':mode is not None,'forced_mode':mode,'forced_direction':direction}

    def next_shared_due(self,state):
        times=[]
        for h in state.humans.values():
            movement=h.get('movement_intent')
            if movement and not h.get('battle_id') and not movement.get('paused_for_battle'):times.append(max(state.simulated_time+1,movement['next_due_at']))
            if h.get('ready_at',0)>state.simulated_time:times.append(h['ready_at'])
        due=scheduling.next_due(state)
        if due is not None:times.append(max(state.simulated_time+1,due))
        return min(times) if times else None

    def tick_shared_time(self,store,run_id,target_time):
        _,s,head=store.load_run(run_id)
        if not self.shared_clock_enabled(s):raise EngineError('shared clock is not active')
        if type(target_time)is not int or target_time<s.simulated_time:raise EngineError('clock target must be a future integer boundary')
        if target_time==s.simulated_time:return None
        due=self.next_shared_due(s);target=min(target_time,s.simulated_time+10,due if due is not None else target_time)
        changes=[];routes=[];working=s
        rng=random.Random(s.world_facts.get('seed',1)+s.state_version*1009)
        for hid,h in sorted(s.humans.items()):
            # Planned steps/provenance are immutable after acceptance; only
            # scalar execution fields change. Do not clone the route every tile.
            intent=copy.copy(h.get('movement_intent'))
            if not intent or h.get('battle_id') or intent.get('paused_for_battle') or intent['next_due_at']>target:continue
            step=intent['steps'][intent['cursor']];prefix=f'humans.{hid}.';extra=[];evidence=None;kind=None
            if step['kind']=='tile':
                m=actor_map(self.maps[h['map_id']],h);p=tuple(step['position'])
                surfing=bool(h.get('status',{}).get('surfing')) and (permission(working,h,'SURF') or h.get('status',{}).get('source_forced_surfing',False))
                valid=any(m._step_basic((h['x'],h['y']),d,surfing=surfing)==p for d in DIRECTIONS)
                if step['map_id']!=h['map_id'] or not valid:
                    changes.append({'op':'set','path':prefix+'movement_intent','value':None});routes.append({'human_id':hid,'interruption':'source terrain changed'});continue
                dx,dy=p[0]-h['x'],p[1]-h['y'];facing=step.get('facing') or next((d for d,delta in DIRECTIONS.items() if delta==(dx,dy)),h.get('facing','south'))
                extra=[{'op':'set','path':prefix+'x','value':p[0]},{'op':'set','path':prefix+'y','value':p[1]},{'op':'set','path':prefix+'facing','value':facing}]
                if h.get('status',{}).get('surfing') and int(m.cells.get(p,{}).get('behavior',0)) not in WATER:extra.append({'op':'set','path':prefix+'status.surfing','value':False})
                evidence={'map_id':h['map_id'],'start':[h['x'],h['y']],'steps':[list(p)],'duration_seconds':1}
                cell=m.cells.get(p,{})
                forced_context=self._forced_context(h,intent,m,p)
                ordinary=self._ordinary_tile_effects(working,hid,intent,cell,evidence,extra,rng,forced_context=forced_context) if int(cell.get('encounter_type',0))==0 else None
                if ordinary is not None:extra,evidence=ordinary
                else:
                    source_state=working
                    if forced_context[0] and not h['movement_intent'].get('forced_movement') and int(cell.get('behavior',0)) not in range(0x50,0x58):
                        # Rare legacy recovery on encounter terrain: the old
                        # interceptor needs the recovered pre-step forced flag.
                        source_state=working.apply_changes([{'op':'set','path':prefix+'movement_intent.forced_movement','value':True}]);source_state.state_hash=source_state.compute_state_hash()
                    extra,_,evidence,kind=intercept(self,source_state,hid,'travel_to',{'x':p[0],'y':p[1]},intent['provenance'],intent['explanation'],evidence,extra,1,rng=rng)
                    evidence.update(forced_movement=forced_context[1] is not None,forced_mode=forced_context[1],forced_direction=forced_context[2])
                if not kind and int(m.cells.get(p,{}).get('behavior',0))==0x66:
                    dst,nx,ny=resolve_transfer(self.maps,m,*p,m.exit_target(*p),surfing=True);actor,scripts=transition_effects(self.maps,h,m,p,dst,(nx,ny))
                    for key in ('map_id','x','y','field','status','facing'):extra.append({'op':'set','path':prefix+key,'value':actor[key]})
                    evidence.update(fall_warp={'destination_map':dst,'landing':[nx,ny]},source_scripts=scripts)
                    script_duration=sum(len(x.get('steps',[])) for x in scripts)
                    intent['next_due_at']=target+1+script_duration
                    if script_duration:extra.append({'op':'set','path':prefix+'ready_at','value':target+script_duration})
                    following=intent['steps'][intent['cursor']+1:intent['cursor']+2]
                    if following and following[0]['kind']=='transfer' and following[0]['map_id']==h['map_id'] and following[0]['source']==list(p):intent['cursor']+=1
            else:
                m=actor_map(self.maps[h['map_id']],h);p=tuple(step['source'])
                try:
                    if h['map_id']!=step['map_id'] or (h['x'],h['y'])!=p:raise EngineError('accepted source transfer origin changed')
                    dst,nx,ny=resolve_transfer(self.maps,m,*p,step['destination_map'],surfing=bool(h.get('status',{}).get('surfing')) or int(m.cells.get(p,{}).get('behavior',0))==0x66)
                    from .access import transfer_gate
                    extra.extend(transfer_gate(h,dst,working));actor,scripts=transition_effects(self.maps,h,m,p,dst,(nx,ny))
                except (EngineError,MapLoadError,AccessDenied):
                    changes.append({'op':'set','path':prefix+'movement_intent','value':None});routes.append({'human_id':hid,'intent_id':intent['intent_id'],'interruption':'source transfer no longer available'});continue
                for key in ('map_id','x','y','field','status','facing'):extra.append({'op':'set','path':prefix+key,'value':actor[key]})
                visited=list(dict.fromkeys(h.get('field',{}).get('visited_maps',[])+[h['map_id'],actor['map_id']]));extra.append({'op':'set','path':prefix+'field.visited_maps','value':visited})
                extra.append({'op':'set','path':prefix+'last_entry.from_map','value':h['map_id']});evidence={'transfer':{'source_map':h['map_id'],'source':list(p),'destination_map':actor['map_id'],'destination':[actor['x'],actor['y']]},'source_scripts':scripts}
                script_duration=sum(len(x.get('steps',[])) for x in scripts)
                intent['next_due_at']=target+1+script_duration
                if script_duration:extra.append({'op':'set','path':prefix+'ready_at','value':target+script_duration})
            final_map=next((c['value'] for c in reversed(extra) if c.get('path')==prefix+'map_id'),h['map_id'])
            if final_map!=h['map_id']:
                from ..mechanics.acquisition import LAB,transition_acquisition
                if h['map_id']==LAB and final_map=='CinnabarIsland_PokemonLab_Entrance' and h.get('acquisition',{}).get('reviving'):extra.append({'op':'set','path':prefix+'acquisition','value':transition_acquisition(h,LAB,final_map)})
                if self.maps[final_map].events.get('map_type') in {'MAP_TYPE_ROUTE','MAP_TYPE_TOWN','MAP_TYPE_OCEAN_ROUTE','MAP_TYPE_CITY'}:extra.append({'op':'set','path':prefix+'field.flash_active','value':False})
                if not self.maps[final_map].events.get('allow_cycling',False):extra.append({'op':'set','path':prefix+'status.bicycle','value':False})
            if evidence and 'forced_movement' in evidence:
                for key in ('forced_movement','forced_mode','forced_direction'):
                    if key in evidence:intent[key]=evidence[key]
            intent['cursor']+=1
            if kind=='human.fainted':intent=None
            elif kind:intent.update(paused_for_battle=True,next_due_at=target+1)
            elif intent['cursor']>=len(intent['steps']):intent=None
            elif intent['next_due_at']<=target:intent['next_due_at']=target+1
            changes.extend(extra)
            if intent is None:changes.append({'op':'set','path':prefix+'movement_intent','value':None})
            else:
                for key,value in intent.items():
                    if key not in h['movement_intent'] or h['movement_intent'].get(key)!=value:changes.append({'op':'set','path':prefix+'movement_intent.'+key,'value':value})
            # Own position/owned-party deltas cannot affect another actor's next
            # accepted tile. Refresh the verified working world only when an
            # earlier actor mutated shared facts (e.g. another wild battle).
            if any(c.get('path','').startswith('world_facts.') for c in extra):
                from .world import expand_entity_sets
                working=s.apply_changes(expand_entity_sets(changes));working.state_hash=working.compute_state_hash()
            routes.append({'human_id':hid,'route':evidence,'event_kind':kind or 'human.moved','intent_id':h['movement_intent']['intent_id'],'accepted_provenance':h['movement_intent']['provenance']})
        changes,receipts=self.resolve_time_effects(s,changes,target-s.simulated_time);changes.append({'op':'advance_clock','seconds':target-s.simulated_time})
        event,_=self._shared_event(s,head,changes,kind='world.shared_tick',causation={'human_id':'engine','action':'shared_tick','provenance':{'kind':'engine','engine_continuation':True}},details={'routes':routes,'activity_completions':receipts,'shared_time':{'from':s.simulated_time,'to':target,'elapsed':target-s.simulated_time}})
        self.commit(store,event);return event
