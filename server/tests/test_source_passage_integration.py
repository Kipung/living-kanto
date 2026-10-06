"""Source courtesy remains a human choice and revalidates its physical outcome."""
import pytest
from test_gameplay import game,state,locate,act
from living_kanto.simulation.engine import StaleActionError


def perry_setup(game):
    current=state(game)
    npc=next(n for n in current.npcs.values() if n['source']['source_script']=='Route13_EventScript_Perry')
    locate(game,'human-001','Route13',(15,5))
    return npc['npc_id']


def test_real_courtesy_action_and_replay_open_route(game):
    engine,store=game;nid=perry_setup(game)
    after=act(game,'human-001','ask_resident_to_make_way',{'npc_id':nid})
    assert (after.npcs[nid]['x'],after.npcs[nid]['y'])==(16,6)
    assert after.humans['human-001']['last_source_passage']['kind']=='step_aside'
    after=act(game,'human-001','walk_to',{'direction':'east'})
    assert (after.humans['human-001']['x'],after.humans['human-001']['y'])==(16,5)
    assert store.replay(after.run_id).state_hash==after.state_hash


def test_courtesy_exchange_consumes_normal_walking_step(game):
    nid=perry_setup(game)
    locate(game,'human-002','Route13',(16,6))
    before=state(game);after=act(game,'human-001','ask_resident_to_make_way',{'npc_id':nid})
    assert after.humans['human-001']['last_source_passage']['kind']=='exchange_tiles'
    assert (after.humans['human-001']['x'],after.humans['human-001']['y'])==(16,5)
    assert after.humans['human-001'].get('field_steps')!=before.humans['human-001'].get('field_steps')
    assert (after.npcs[nid]['x'],after.npcs[nid]['y'])==(15,5)


def test_changed_recess_cannot_silently_turn_step_aside_into_exchange(game):
    engine,store=game;nid=perry_setup(game)
    engine.activate_shared_clock(store,'gameplay-test')
    current=state(game);obs,token=engine.capture_decision_boundary(current,'human-001')
    assert any(a.action=='ask_resident_to_make_way' for a in obs.legal_actions)
    locate(game,'human-002','Route13',(16,6));before=state(game)
    choice={'action':'ask_resident_to_make_way','arguments':{'npc_id':nid},'decision_explanation':'Test requested source courtesy'}
    with pytest.raises(StaleActionError,match='passage occupancy'):
        engine.build_revalidated_action_event(store,'gameplay-test','human-001',choice,obs.state_version,token,{'kind':'user','author':'test'})
    assert state(game).state_hash==before.state_hash
