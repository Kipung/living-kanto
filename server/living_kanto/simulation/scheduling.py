"""Deferred daily-life activities and integer-time needs.

Human needs/pay/timing are declared simulation adaptations, not cartridge rules.
Activities retain the accepted intent's model/user provenance. Completion is an
engine consequence; it is never a newly invented human decision.
"""
import copy
DURATIONS={'rest':300,'work':3600}
NEED_PERIODS={'energy':3600,'social':1800}
WORK_ROLES={'worker','shop_staff','service_staff','resident'}
class ScheduleError(ValueError):pass

def current_activity(h):
 a=h.get('activity')
 return a if isinstance(a,dict) and a.get('kind') in DURATIONS else None

def start_activity(state,hid,kind,args,provenance,explanation):
 if kind not in DURATIONS or args:raise ScheduleError('Daily activity requires a known kind and empty arguments')
 h=state.humans[hid]
 if current_activity(h) or h.get('battle_id') or h.get('service_request'):raise ScheduleError('Finish or cancel the existing activity before beginning another')
 if provenance.get('kind') not in ('model','user') or provenance.get('kind')=='model' and not provenance.get('model_id') or not explanation.strip() or len(explanation)>2000:raise ScheduleError('Activity requires accepted human decision provenance')
 energy=int(h.get('status',{}).get('energy',100))
 if kind=='work' and (h.get('role') not in WORK_ROLES or energy<20):raise ScheduleError('This work role needs at least 20 energy')
 a={'human_id':hid,'intent_id':f'activity-{state.state_version}-{hid}','kind':kind,'start_at':state.simulated_time,'ready_at':state.simulated_time+DURATIONS[kind],'accepted_state_version':state.state_version,'provenance':copy.deepcopy(provenance),'explanation':explanation,'arguments':{},'reserved_energy':20 if kind=='work' else 0}
 p='humans.'+hid;changes=[{'op':'set','path':p+'.activity','value':a},{'op':'set','path':p+'.ready_at','value':a['ready_at']},{'op':'set','path':p+'.status.activity','value':'working' if kind=='work' else 'resting'}]
 if kind=='work':changes.append({'op':'set','path':p+'.status.energy','value':energy-20})
 return changes,copy.deepcopy(a)

def next_due(state):
 times=[a['ready_at'] for h in state.humans.values() if (a:=current_activity(h))]
 return min(times) if times else None

def elapsed_needs(state,target_time):
 """Apply elapsed time once; persisted remainders make chunking invariant."""
 if type(target_time) is not int or target_time<state.simulated_time:raise ScheduleError('Needs cannot advance backwards')
 changes=[]
 for hid,h in sorted(state.humans.items()):
  saved=h.get('needs_clock',{});at=int(saved.get('at',state.simulated_time));delta=target_time-at
  if delta<0:raise ScheduleError('Human needs clock is ahead of world time')
  if delta==0:continue
  remainder=copy.deepcopy(saved.get('remainders',{}));status=h.get('status',{});a=current_activity(h)
  for need,period in NEED_PERIODS.items():
   active_delta=delta
   if need=='energy' and a and a['kind']=='rest':active_delta=max(0,target_time-max(at,a['ready_at']))
   total=int(remainder.get(need,0))+active_delta;loss,remainder[need]=divmod(total,period);value=max(0,min(100,int(status.get(need,100))-loss))
   if value!=status.get(need,100):changes.append({'op':'set','path':f'humans.{hid}.status.{need}','value':value})
  changes.append({'op':'set','path':f'humans.{hid}.needs_clock','value':{'at':target_time,'remainders':remainder}})
 return changes

def due_completions(state,target_time=None):
 """Drain chronologically, without emitting a clock mutation.

    Parent records its actual clock delta once. Internal boundary snapshots make
    capped rest recovery and later elapsed decay independent of event chunking.
 """
 target=state.simulated_time if target_time is None else target_time
 if type(target) is not int or target<state.simulated_time:raise ScheduleError('Completion cannot advance backwards')
 changes=[];receipts=[];working=state
 due=sorted((a['ready_at'],hid,a) for hid,h in state.humans.items() if (a:=current_activity(h)) and a['ready_at']<=target)
 for due_at,hid,a in due:
  boundary=max(working.simulated_time,due_at);delta=elapsed_needs(working,boundary)
  intermediate=working.apply_changes(delta)
  h=intermediate.humans[hid];p='humans.'+hid
  if a['kind']=='work':delta.append({'op':'set','path':p+'.money','value':min(999999,int(h.get('money',0))+100)})
  else:delta.append({'op':'set','path':p+'.status.energy','value':min(100,int(h.get('status',{}).get('energy',100))+20)})
  delta += [{'op':'set','path':p+'.activity','value':None},{'op':'set','path':p+'.ready_at','value':boundary},{'op':'set','path':p+'.status.activity','value':'ready'}]
  changes.extend(delta)
  working=working.apply_changes(delta+[{'op':'advance_clock','seconds':boundary-working.simulated_time}])
  receipts.append({'human_id':hid,'intent_id':a['intent_id'],'activity_kind':a['kind'],'started_at':a['start_at'],'due_at':a['ready_at'],'completed_at':boundary,'recorded_at':target,'accepted_state_version':a['accepted_state_version'],'decision_explanation':a['explanation'],'provenance':{**copy.deepcopy(a['provenance']),'engine_continuation':True,'continuation_of_state_version':a['accepted_state_version']},'reward':{'money':100} if a['kind']=='work' else {'energy':20}})
 changes.extend(elapsed_needs(working,target))
 return changes,receipts

def cancel_activity(state,hid):
 a=current_activity(state.humans[hid])
 if not a:raise ScheduleError('No pending daily activity to cancel')
 if a['ready_at']<=state.simulated_time:raise ScheduleError('Activity is already due; complete it before cancellation')
 p='humans.'+hid
 return [{'op':'set','path':p+'.activity','value':None},{'op':'set','path':p+'.ready_at','value':state.simulated_time},{'op':'set','path':p+'.status.activity','value':'ready'}],{'intent_id':a['intent_id'],'cancelled_at':state.simulated_time,'accepted_state_version':a['accepted_state_version'],'no_completion_reward':True}

def wait_target(state,hid):
 a=current_activity(state.humans[hid])
 if not a:raise ScheduleError('No pending activity to wait for')
 return max(state.simulated_time,a['ready_at'])

def start_batch(state,choices):
 """Atomic disjoint daily-activity starts from one authoritative baseline.

    No service, ownership, battle, item, or shared-resource claims are supported.
    Every actor reserves only their own energy/activity state. Conflicts fail the
    entire batch before any change is persisted; caller then reobserves actors.
 """
 if not choices or len(choices)>8:raise ScheduleError('Activity batch must contain 1 through 8 actors')
 changes=[];receipts=[];seen=set()
 for choice in sorted(choices,key=lambda c:c['human_id']):
  hid=choice['human_id']
  if hid in seen:raise ScheduleError('Batch repeats an actor')
  seen.add(hid)
  if choice.get('observation_version')!=state.state_version or choice.get('expected_state_version')!=state.state_version:raise ScheduleError('Batch choices must share the exact current observation/state version')
  delta,receipt=start_activity(state,hid,choice['action'],choice.get('arguments',{}),choice['provenance'],choice['decision_explanation']);changes.extend(delta);receipts.append(receipt)
 writes=[c['path'] for c in changes]
 if len(writes)!=len(set(writes)):raise ScheduleError('Batch writes overlap')
 return changes,{'baseline_state_version':state.state_version,'decisions':receipts,'disjoint_write_paths':writes}

def build_batch_event(state,head,choices,wall_time):
 """Build one atomic work/rest start event; the caller commits it under lock."""
 from ..contracts.base import content_hash
 from ..contracts.events import CanonicalEvent
 from ..contracts.state import StateUpdate
 changes,receipt=start_batch(state,choices)
 decisions=[]
 for choice in sorted(choices,key=lambda c:c['human_id']):
  row={'human_id':choice['human_id'],'action':choice['action'],'arguments':copy.deepcopy(choice.get('arguments',{})),'explanation':choice['decision_explanation'],'provenance':copy.deepcopy(choice['provenance']),'observation_version':state.state_version}
  decisions.append(row);changes.append({'op':'set','path':f'humans.{row["human_id"]}.last_decision','value':{k:v for k,v in row.items() if k!='human_id'}})
 new=state.with_advanced_version(changes);idx=state.state_version;eid=f'evt-{idx}-{content_hash(changes)[:24]}'
 update=StateUpdate(run_id=state.run_id,event_id=eid,event_index=idx,prior_state_version=idx,prior_state_hash=state.state_hash,previous_head=head,state_version=new.state_version,state_hash=new.state_hash,changes=changes).validate()
 event=CanonicalEvent(run_id=state.run_id,event_id=eid,event_index=idx,state_version=new.state_version,previous_head=head,event_kind='activity.batch_started',tick=new.tick,simulated_time=new.simulated_time,real_wall_time=wall_time,causation={'human_id':'engine','decision_explanation':'Start disjoint accepted daily activities from one observation boundary','provenance':{'kind':'engine','records_accepted_human_decisions':True},'decisions':decisions},affected=[{'human_id':d['human_id']} for d in decisions],before={},after={},deterministic_inputs=receipt,transaction={'kind':'state_update',**update.to_dict()},visibility={'private_to':[d['human_id'] for d in decisions]}).validate()
 assert update.apply_to(state).state_hash==new.state_hash
 return event,new
