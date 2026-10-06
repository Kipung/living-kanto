"""Thought and immediate speech events retain continuity in optimized storage."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_concurrent_cognition import shared_world,activate,choose
from living_kanto.simulation import cognition
from living_kanto.store.run_store import RunStore


def test_v2_thought_and_speech_preserve_private_state_and_cold_replay(shared_world):
    engine,store=shared_world;activate(engine,store)
    store.optimize_storage('shared',checkpoint_interval=2)
    choose(engine,store,'alice','rest')
    before=store.load_run('shared')[1];obs,token=cognition.capture(engine,before,'alice')
    choice={'action':'remember','arguments':{'text':'Test reflection while resting.'},'decision_explanation':'Identified test thought'}
    event,_=cognition.build_event(engine,store,'shared','alice',choice,obs,token,
                                 {'kind':'model','model_id':'test-only','test_provider':True})
    engine.commit(store,event)
    choose(engine,store,'bob','talk_to',{'human_id':'alice','text':'Can you hear me?'})
    current=store.load_run('shared')[1]
    assert current.humans['alice']['activity']==before.humans['alice']['activity']
    assert any('Can you hear me?' in str(m) for m in current.humans['alice']['memories'].values())
    assert current.humans['alice']['cognition']['latest']['execution_authorized'] is False
    assert store.replay('shared').to_dict()==current.to_dict()
    cold=RunStore(store.path)
    try:assert cold.load_run('shared')[1].to_dict()==current.to_dict()
    finally:cold.close()
