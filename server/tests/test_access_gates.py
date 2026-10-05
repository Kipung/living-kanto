import pytest
from living_kanto.simulation.access import transfer_gate,AccessDenied,BADGES

def h(mid):return {'human_id':'a','map_id':mid,'inventory':{},'badges':[]}
def test_tea_delivery_consumed_once_and_private():
 actor=h('Route5_SouthEntrance')
 with pytest.raises(AccessDenied):transfer_gate(actor,'SaffronCity')
 actor['inventory']={'tea':{'quantity':1}}
 changes=transfer_gate(actor,'SaffronCity')
 assert changes[0]['value']['tea']['quantity']==0
 actor['access']={'saffron_tea':True};actor['inventory']={}
 assert not transfer_gate(actor,'SaffronCity')
 with pytest.raises(AccessDenied):transfer_gate(h('Route5_SouthEntrance'),'SaffronCity')
def test_ticket_and_key_not_bypassed_by_location():
 actor=h('VermilionCity')
 with pytest.raises(AccessDenied):transfer_gate(actor,'SSAnne_1F_Corridor')
 actor['inventory']={'SS_TICKET':{'quantity':1}}
 assert not transfer_gate(actor,'SSAnne_1F_Corridor')
 with pytest.raises(AccessDenied):transfer_gate(actor,'CinnabarIsland_Gym')
 actor['inventory']['secret_key']={'quantity':1}
 assert not transfer_gate(actor,'CinnabarIsland_Gym')
def test_giovanni_and_league_require_actual_badges():
 actor=h('ViridianCity')
 with pytest.raises(AccessDenied):transfer_gate(actor,'ViridianCity_Gym')
 actor['badges']=sorted(BADGES-{'earth'})
 assert not transfer_gate(actor,'ViridianCity_Gym')
 with pytest.raises(AccessDenied):transfer_gate(actor,'Route23')
 actor['badges'].append('earth')
 assert not transfer_gate(actor,'Route23')

def test_normal_engine_source_transfer_cannot_bypass_tea_or_ticket(tmp_path):
 from pathlib import Path
 from living_kanto.simulation.world import WorldEngine
 from living_kanto.simulation.engine import EngineError
 from living_kanto.store.run_store import RunStore
 from living_kanto.contracts.state import StateUpdate
 engine=WorldEngine(Path(__file__).resolve().parents[2]/'content');store=RunStore(tmp_path/'gates.db');engine.initialize(store,'gates',mode='survival')
 _,state,head=store.load_run('gates');actor=state.humans['human-001']
 class FixtureStore:
  def load_run(self,run):return None,state,head
 for mid,x,y,target,item in [('Route5_SouthEntrance',3,9,'SaffronCity','tea'),('VermilionCity',22,34,'SSAnne_Exterior','ss_ticket')]:
  actor.update(map_id=mid,x=x,y=y,inventory={},access={});state.state_hash=state.compute_state_hash()
  kwargs={'action':'enter_map','arguments':{'map_id':target},'observation_version':0,'expected_state_version':0,'decision_explanation':'Attempt a real map exit','decision_provenance':{'kind':'user'}}
  with pytest.raises(EngineError):engine.build_action_event(FixtureStore(),'gates','human-001',**kwargs)
  actor['inventory']={item:{'item_id':item,'quantity':1}};state.state_hash=state.compute_state_hash()
  event,new=engine.build_action_event(FixtureStore(),'gates','human-001',**kwargs)
  assert new.humans['human-001']['map_id']==target
  assert StateUpdate.from_dict(event.transaction).apply_to(state).state_hash==new.state_hash
  if item=='tea':assert new.humans['human-001']['inventory']['tea']['quantity']==0 and new.humans['human-001']['access']['saffron_tea']
 store.close()

def test_safari_transfer_requires_actual_paid_visit():
 actor=h('SafariZone_Entrance')
 with pytest.raises(AccessDenied):transfer_gate(actor,'SafariZone_Center')
 actor['safari']={'active':True,'balls':30,'steps':600}
 assert not transfer_gate(actor,'SafariZone_Center')
 actor['safari']['active']=False
 with pytest.raises(AccessDenied):transfer_gate(actor,'SafariZone_SecretHouse')
