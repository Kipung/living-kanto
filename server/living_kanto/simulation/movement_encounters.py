"""Scan the actual accepted route, stopping before every later step/warp."""
import copy,random
from ..mechanics.encounters import walking_encounter
from ..mechanics.field_steps import field_steps
from .field import actor_map

def intercept(engine,state,hid,action,args,provenance,explanation,evidence,changes,duration):
 if action not in ('walk_to','travel_to','journey_to') or not evidence or not hasattr(engine,'start_walking_encounter'):return changes,duration,evidence,None
 h=state.humans[hid];actor=copy.deepcopy(h);rng=random.Random(state.world_facts.get('seed',1)+state.state_version*1009);party=[state.pokemon[p] for p in h.get('party',[]) if p in state.pokemon]
 segments=evidence.get('journey') or [{'map_id':h['map_id'],'start':[h['x'],h['y']],'steps':evidence.get('steps',[]),'transfer_completed':False}];walked=[];elapsed=0;hit=None;blackout=False;forced=False
 for segment in segments:
  actor.update(map_id=segment['map_id'],x=segment['start'][0],y=segment['start'][1]);actual=[];m=actor_map(engine.maps[actor['map_id']],actor)
  for p in segment['steps']:
   actor.update(x=p[0],y=p[1]);actual.append(p);elapsed+=1
   behavior=int(m.cells.get(tuple(p),{}).get('behavior',0));forced=forced or behavior in range(0x50,0x58)
   actor,party,blackout=field_steps(actor,party,rng,forced=forced)
   if behavior==0x58 or behavior not in range(0x50,0x54) and not any(int(m.cells.get(tuple(q),{}).get('behavior',0)) in range(0x54,0x58) for q in actual):forced=False
   if blackout:break
   actor,hit=walking_encounter(actor,m.cells.get(tuple(p),{}),engine.encounter_table(actor['map_id']),party,rng,surfing=actor.get('status',{}).get('surfing',False),bicycle=actor.get('status',{}).get('bicycle',False))
   if hit or blackout:break
  walked.append({**segment,'steps':actual,'transfer_completed':False if hit or blackout else segment.get('transfer_completed',False)})
  if hit or blackout:break
  if segment.get('transfer_completed'):
   for c in segment.get('checkpoint_changes',[]):
    parts=c['path'].split('.')[2:];o=actor
    for k in parts[:-1]:o=o.setdefault(k,{})
    o[parts[-1]]=copy.deepcopy(c['value'])
   actor.update(map_id=segment['destination_map'],x=segment['destination'][0],y=segment['destination'][1]);actor['field']=copy.deepcopy(segment.get('field_after',actor.get('field',{})));actor['status']=copy.deepcopy(segment.get('status_after',actor.get('status',{})));elapsed+=1+sum(len(s.get('steps',[])) for s in segment.get('script_steps',[]))
 for mon in party:
  original=state.pokemon[mon['pokemon_id']]
  for key,value in mon.items():
   if original.get(key)!=value:changes.append({'op':'set','path':f'pokemon.{mon["pokemon_id"]}.{key}','value':value})
 if not hit and not blackout:
  changes.append({'op':'set','path':f'humans.{hid}.field_steps','value':actor.get('field_steps',{})})
  changes.append({'op':'set','path':f'humans.{hid}.field_encounter','value':actor.get('field_encounter',{})});return changes,duration,evidence,None
 if action=='walk_to':actor['facing']=args['direction']
 prefix=f'humans.{hid}.';changes=[c for c in changes if not c.get('path','').startswith(prefix)]
 if action=='journey_to' and not blackout:actor['active_plan']={'kind':'journey','destination_map':args['map_id'],'accepted_state_version':(h.get('active_plan') or {}).get('accepted_state_version',state.state_version) if provenance.get('continuation_of_state_version') is not None else state.state_version,'explanation':explanation,'provenance':provenance}
 else:actor['active_plan']=None
 for k,v in actor.items():
  if h.get(k)!=v:changes.append({'op':'set','path':prefix+k,'value':v})
 preview=state.with_advanced_version(changes)
 if blackout:
  extra,recovery=engine.recover_whiteout(preview,hid,party,reason='field_poison');kind='human.fainted';battle_duration=0
 else:extra,kind,battle_duration=engine.start_walking_encounter(preview,hid,hit)
 changes.extend(extra)
 if action=='journey_to':evidence={**evidence,'journey':walked,'interrupted':True,'interruption_reason':'field poison whiteout' if blackout else 'source wild encounter'}
 else:evidence={**evidence,'steps':walked[0]['steps'],'interrupted':True,'interruption_reason':'field poison whiteout' if blackout else 'source wild encounter'}
 evidence.update(duration_seconds=elapsed+battle_duration,encounter=hit)
 if blackout:evidence['whiteout']=recovery
 return changes,elapsed+battle_duration,evidence,kind
