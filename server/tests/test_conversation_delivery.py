"""Speech delivery is factual; a listener's reply remains a separate choice."""
import copy
from test_gameplay import game, state, locate, scenario, act
from test_shared_clock_engine import activate, choose


def test_speech_delivered_privately_atomically_and_replays(game):
    e,store=game
    locate(game,'human-001','PalletTown',(10,10));locate(game,'human-002','PalletTown',(11,10))
    locate(game,'human-003','PewterCity',(15,16))
    scenario(game,[{'op':'set','path':'humans.human-002.memories','value':{'0':{'text':'Original A'},'2':{'text':'Original B'}}}])
    before=state(game);old_listener=copy.deepcopy(before.humans['human-002']);old_outsider=copy.deepcopy(before.humans['human-003'])
    after=act(game,'human-001','talk_to',{'human_id':'human-002','text':'Could you help me find the Center?'})
    heard=after.humans['human-002']['memories']['3']
    assert heard['direction']=='heard' and heard['other']=='human-001'
    assert heard['text']=='Could you help me find the Center?'
    assert after.humans['human-002']['memories']['2']==old_listener['memories']['2']
    assert after.humans['human-002']['goal']==old_listener['goal']
    assert after.humans['human-002']['party']==old_listener['party']
    for key in ('memories','goal','relationships','party','money'):
        assert after.humans['human-003'][key]==old_outsider[key]
    context=e.observation_for(after,'human-002').self_state['conversation_context']
    assert context['recent_received'][0]['text']==heard['text']
    assert not e.observation_for(after,'human-003').self_state['conversation_context']['recent_received']
    assert store.replay('gameplay-test').state_hash==after.state_hash


def test_delivery_invalidates_listener_pending_observation_without_auto_reply(game):
    e,_=game
    locate(game,'human-001','PalletTown',(10,10));locate(game,'human-002','PalletTown',(11,10))
    activate(game)
    obs,token=e.capture_decision_boundary(state(game),'human-002')
    choose(game,'human-001','talk_to',{'human_id':'human-002','text':'What is your favorite type?'})
    from living_kanto.simulation.engine import StaleActionError
    import pytest
    with pytest.raises(StaleActionError):
        choose(game,'human-002','wait',{},token=token,version=obs.state_version)
    after=state(game)
    assert after.humans['human-002'].get('last_decision',{}).get('action')!='talk_to'
    assert e.observation_for(after,'human-002').self_state['conversation_context']['recent_received']
    # A newly observed listener is free to decline engagement by waiting.
    refreshed=choose(game,'human-002','wait',{})
    assert refreshed.humans['human-002']['last_decision']['action']=='wait'
