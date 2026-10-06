from pathlib import Path
from types import SimpleNamespace
import copy
import pytest
from living_kanto.simulation.world import WorldEngine
from living_kanto.simulation.engine import EngineError,SimulationEngine
from living_kanto.contracts.human import LegalAction
from living_kanto.store.run_store import RunStore

@pytest.fixture(scope='module')
def engine():return WorldEngine(Path(__file__).resolve().parents[2]/'content')

@pytest.fixture
def world(engine,tmp_path):
 store=RunStore(tmp_path/'validation.db');engine.initialize(store,'validation',mode='survival')
 _,state,head=store.load_run('validation')
 h=state.humans['human-001'];h.update(map_id='PalletTown',x=10,y=8,inventory={},badges=[],party=[],status={})
 state.humans['human-002'].update(map_id='PalletTown',x=11,y=8)
 state.state_hash=state.compute_state_hash()
 class Snapshot:
  def load_run(self,run_id):return None,state,head
 yield Snapshot(),state
 store.close()

@pytest.mark.parametrize('action,args',[('wait',{}),('rest',{}),('talk_to',{'human_id':'human-002','text':'Hello'}),('walk_to',{'direction':'north'})])
def test_validation_skips_route_menu_and_matches_full_outcome(engine,world,monkeypatch,action,args):
 store,state=world
 kwargs=dict(action=action,arguments=args,observation_version=state.state_version,expected_state_version=state.state_version,decision_explanation='Fixture choice',decision_provenance={'kind':'user'})
 # Use full current menu as the comparison baseline.
 with monkeypatch.context() as patch:
  patch.setattr(engine,'legal_actions_for_validation',lambda state,hid,action:engine.legal_actions(state,hid))
  expected_event,expected_state=engine.build_action_event(store,'validation','human-001',**kwargs)
 def forbidden(*args,**kwargs):raise AssertionError('Non-route validation planned route menus')
 monkeypatch.setattr('living_kanto.simulation.engine.plan_journey',forbidden)
 monkeypatch.setattr('living_kanto.simulation.engine.shortest_path',forbidden)
 event,result=engine.build_action_event(store,'validation','human-001',**kwargs)
 assert result.state_hash==expected_state.state_hash
 assert event.transaction==expected_event.transaction
 assert event.deterministic_inputs==expected_event.deterministic_inputs


def test_observation_default_still_includes_routes(engine,world):
 _,s=world
 full=engine.legal_actions(s,'human-001');fast=engine.legal_actions(s,'human-001',include_routes=False)
 assert any(a.action=='journey_to' for a in full)
 assert {a.action for a in fast}.isdisjoint({'travel_to','journey_to'})
 assert [a.to_dict() for a in fast]==[a.to_dict() for a in full if a.action not in {'travel_to','journey_to'}]


def test_fast_validation_rejects_unavailable_progression_and_invalid_direction(engine,world,monkeypatch):
 store,s=world
 def forbidden(*a,**kw):raise AssertionError('Unexpected menu planning')
 monkeypatch.setattr('living_kanto.simulation.engine.plan_journey',forbidden)
 for action,args in [('walk_to',{'direction':'invalid'}),('surf',{}),('choose_starter',{'species':'Bulbasaur'})]:
  with pytest.raises(EngineError):engine.build_action_event(store,'validation','human-001',action=action,arguments=args,observation_version=s.state_version,expected_state_version=s.state_version,decision_explanation='Fixture',decision_provenance={'kind':'user'})


def test_uncertain_truncation_falls_back_to_exact_full_menu(engine,world,monkeypatch):
 _,s=world
 gm=engine.maps[s.humans['human-001']['map_id']];assert gm.source_revision
 filler=[LegalAction(action='wait',arguments={}) for _ in range(94)]
 hidden=LegalAction(action='rare_action',arguments={})
 calls=[]
 def menu(state,hid,*,include_routes=True):
  calls.append(include_routes)
  return tuple(filler+[LegalAction(action='journey_to',arguments={}) for _ in range(34)]) if include_routes else tuple(filler+[hidden])
 monkeypatch.setattr(engine,'legal_actions',menu)
 result=engine.legal_actions_for_validation(s,'human-001','rare_action')
 assert calls==[False,True]
 assert not any(a.action=='rare_action' for a in result)


def test_legacy_legal_action_override_retains_full_validation(engine,world,monkeypatch):
 _,s=world
 monkeypatch.setattr(engine,'legal_actions',lambda state,hid:(LegalAction(action='wait',arguments={}),))
 assert engine.legal_actions_for_validation(s,'human-001','wait')[0].action=='wait'
