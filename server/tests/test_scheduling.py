import pytest
from living_kanto.contracts.state import WorldState
from living_kanto.simulation.scheduling import start_activity,due_completions,elapsed_needs,start_batch,ScheduleError,cancel_activity,next_due,wait_target

def world():
 s=WorldState(run_id='schedule',humans={k:{'human_id':k,'role':'worker','money':100,'status':{'energy':100,'social':100}} for k in ('a','b')});s.state_hash=s.compute_state_hash();return s
PROV={'kind':'model','model_id':'identified-test-model','test_provider':True}
def apply(s,changes,t=None):return s.with_advanced_version(changes+([{'op':'advance_clock','seconds':t-s.simulated_time}] if t is not None else []))

def test_work_reserves_energy_now_and_pays_only_after_real_due_boundary():
 s=world();delta,a=start_activity(s,'a','work',{},PROV,'Earn money through work');started=apply(s,delta)
 assert started.simulated_time==0 and started.humans['a']['money']==100 and started.humans['a']['status']['energy']==80
 assert next_due(started)==3600 and wait_target(started,'a')==3600
 delta,receipts=due_completions(started,3599);early=apply(started,delta,3599);assert not receipts and early.humans['a']['money']==100
 delta,receipts=due_completions(early,3600);finished=apply(early,delta,3600)
 assert finished.humans['a']['money']==200 and finished.humans['a']['activity'] is None
 assert finished.humans['b']['status']=={'energy':99,'social':98}
 assert receipts[0]['provenance']['continuation_of_state_version']==0 and receipts[0]['provenance']['model_id']=='identified-test-model'
 assert s.humans['a']['money']==100

def test_fixed_point_needs_are_identical_under_different_event_chunking():
 s=world();whole=apply(s,elapsed_needs(s,3700),3700);chunks=s
 for target in (1,599,1200,3600,3700):chunks=apply(chunks,elapsed_needs(chunks,target),target)
 for hid in s.humans:
  assert chunks.humans[hid]['status']==whole.humans[hid]['status']
  assert chunks.humans[hid]['needs_clock']==whole.humans[hid]['needs_clock']

def test_rest_reward_is_deferred_cancelled_work_never_pays():
 s=world();s.humans['a']['status']['energy']=50;s.state_hash=s.compute_state_hash();delta,_=start_activity(s,'a','rest',{},PROV,'Rest');resting=apply(s,delta)
 assert resting.humans['a']['status']['energy']==50
 with pytest.raises(ScheduleError):start_activity(resting,'a','work',{},PROV,'Work')
 delta,receipts=due_completions(resting,300);rested=apply(resting,delta,300);assert rested.humans['a']['status']['energy']==70 and receipts[0]['reward']=={'energy':20}
 delta,_=start_activity(rested,'a','work',{},PROV,'Work');working=apply(rested,delta);delta,receipt=cancel_activity(working,'a');cancelled=apply(working,delta)
 delta,receipts=due_completions(cancelled,4000);finished=apply(cancelled,delta,4000)
 assert finished.humans['a']['money']==100 and not receipts and receipt['no_completion_reward']

def test_same_snapshot_disjoint_activity_batch_is_atomic_and_rejects_stale_or_conflicting_actors():
 s=world();choices=[{'human_id':hid,'action':kind,'arguments':{},'observation_version':0,'expected_state_version':0,'provenance':PROV,'decision_explanation':'Chosen daily activity'} for hid,kind in [('a','work'),('b','rest')]]
 delta,receipt=start_batch(s,choices);started=apply(s,delta)
 assert started.state_version==1 and started.simulated_time==0 and len(receipt['decisions'])==2
 assert started.humans['a']['money']==100 and started.humans['b']['activity']['ready_at']==300
 for invalid in ([choices[0],choices[0]],[dict(choices[0],expected_state_version=1),choices[1]]):
  with pytest.raises(ScheduleError):start_batch(s,invalid)
 assert s.humans['a']['status']['energy']==100

def test_already_due_drain_does_not_advance_clock_and_ties_sort_by_human_id():
 s=world();delta=[]
 for hid in ('b','a'):d,_=start_activity(s,hid,'rest',{},PROV,'Rest');delta+=d
 running=apply(s,delta);elapsed=apply(running,elapsed_needs(running,300),300);changes,receipts=due_completions(elapsed)
 assert [r['human_id'] for r in receipts]==['a','b'] and not any(c['op']=='advance_clock' for c in changes)
 assert apply(elapsed,changes).simulated_time==300

def test_capped_rest_recovery_then_later_decay_is_chunking_invariant():
 s=world();s.humans['a']['status']['energy']=95;s.state_hash=s.compute_state_hash();delta,_=start_activity(s,'a','rest',{},PROV,'Rest');start=apply(s,delta)
 changes,receipts=due_completions(start,7500);late=apply(start,changes,7500)
 changes,_=due_completions(start,300);early=apply(start,changes,300);changes,_=due_completions(early,7500);early=apply(early,changes,7500)
 assert late.humans['a']['status']==early.humans['a']['status']
 assert late.humans['a']['status']['energy']==98 and receipts[0]['completed_at']==300 and receipts[0]['recorded_at']==7500

def test_production_world_work_receipt_deferred_completion_and_replay(tmp_path):
 from pathlib import Path
 from living_kanto.simulation.world import WorldEngine
 from living_kanto.store.run_store import RunStore
 from living_kanto.contracts.state import StateUpdate
 e=WorldEngine(Path(__file__).resolve().parents[2]/'content');store=RunStore(tmp_path/'schedule.db');e.initialize(store,'schedule',mode='observer');store.set_status('schedule','running')
 _,initial,_=store.load_run('schedule');hid=next(hid for hid,h in initial.humans.items() if h['role']=='worker');money=initial.humans[hid]['money']
 event,start=e.build_action_event(store,'schedule',hid,action='work',arguments={},observation_version=0,expected_state_version=0,decision_explanation='Identified production-path scheduling test',decision_provenance=PROV)
 assert start.simulated_time==0 and start.humans[hid]['money']==money and start.humans[hid]['activity']['ready_at']==3600
 assert not e.legal_actions(start,hid)
 assert StateUpdate.from_dict(event.transaction).apply_to(initial).state_hash==start.state_hash
 e.commit(store,event);assert e.advance_activities(store,'schedule') is None
 completion=e.advance_activities(store,'schedule',allow_future=True);_,finished,_=store.load_run('schedule')
 assert finished.simulated_time==3600 and finished.humans[hid]['money']==money+100
 receipt=completion.causation['activity_completions'][0]
 assert receipt['provenance']['model_id']=='identified-test-model' and receipt['provenance']['continuation_of_state_version']==0
 assert finished.humans[hid]['last_decision']['action']=='work'
 assert StateUpdate.from_dict(completion.transaction).apply_to(start).state_hash==finished.state_hash
 store.close()

def test_atomic_batch_canonical_event_replays_and_preserves_every_real_decision_origin():
 from living_kanto.simulation.scheduling import build_batch_event
 from living_kanto.contracts.state import StateUpdate
 s=world();choices=[{'human_id':hid,'action':kind,'arguments':{},'observation_version':0,'expected_state_version':0,'provenance':PROV,'decision_explanation':'Identified model chose '+kind} for hid,kind in [('b','rest'),('a','work')]]
 event,new=build_batch_event(s,'0'*64,choices,'2026-10-05T00:00:00+00:00')
 assert event.event_kind=='activity.batch_started' and new.state_version==1 and new.simulated_time==0
 assert [d['human_id'] for d in event.causation['decisions']]==['a','b']
 assert all(d['provenance']['model_id']=='identified-test-model' and d['observation_version']==0 for d in event.causation['decisions'])
 assert StateUpdate.from_dict(event.transaction).apply_to(s).state_hash==new.state_hash
 assert new.humans['a']['money']==100
