"""Driver orchestration tests never perform model inference or mutation."""
from types import SimpleNamespace
from pathlib import Path
import importlib.util
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
spec=importlib.util.spec_from_file_location('focused_driver',ROOT/'tools/trial_autonomous_progression.py')
driver=importlib.util.module_from_spec(spec);spec.loader.exec_module(driver)


def test_declared_zero_badge_level_five_candidate_selection():
    original=SimpleNamespace(humans={
        'a':{'role':'aspiring_trainer','badges':[],'party':['mon']},
        'b':{'role':'aspiring_trainer','badges':['boulder'],'party':['mon']},
        'c':{'role':'resident','badges':[],'party':['mon']}},pokemon={'mon':{'level':5,'origin':{'kind':'declared_initial_setup'}}})
    current=SimpleNamespace(humans={'a':{'badges':[]},'b':{'badges':[]},'c':{'badges':[]}})
    assert driver.eligible_candidates(original,current)==['a']
    current.humans['a']['badges']=['cascade']
    assert driver.eligible_candidates(original,current)==[]


def test_required_opponent_is_scheduled_without_selecting_move():
    class Engine:
        def active_battle(self,state,focal):return {'wild':False,'opponent':'leader'}
        def battle_actions(self,state,actor):return ['opaque-legal-choice'] if actor=='leader' else []
    state=SimpleNamespace(humans={'focal':{},'leader':{}})
    assert driver.required_actor(Engine(),state,'focal')==('leader','required_opponent_decision')


def test_service_actor_selection_preserves_model_choice():
    class Engine:
        def active_battle(self,state,focal):return None
        def legal_actions(self,state,actor):return [SimpleNamespace(action='serve_customer'),SimpleNamespace(action='talk_to')]
    state=SimpleNamespace(humans={'focal':{'service_request':{'map_id':'center'}},'staff':{'role':'service_staff','map_id':'center'}})
    assert driver.required_actor(Engine(),state,'focal')==('staff','local_service_staff_decision')


def test_incomplete_soak_guard_creates_no_database(tmp_path,monkeypatch):
    import json
    import pytest
    report=tmp_path/'soak.json';report.write_text(json.dumps({'run_id':'trial','complete':False}))
    database=tmp_path/'absent.db'
    monkeypatch.setattr(sys,'argv',['driver','--database',str(database),'--run-id','trial','--soak-report',str(report),'--output',str(tmp_path/'trial.json')])
    with pytest.raises(SystemExit) as exc:driver.main()
    assert exc.value.code==2 and not database.exists()
