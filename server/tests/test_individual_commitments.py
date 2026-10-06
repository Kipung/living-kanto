import json
import pytest
from living_kanto.simulation.engine import StaleActionError
from test_gameplay import game,state,act
from test_shared_clock_engine import activate,choose

def test_shared_commitment_persists_private_and_replays(game):
 e,store=game;activate(game)
 s=choose(game,'human-001','set_commitment',{'text':'Visit Viridian and record what I observe'})
 assert s.humans['human-001']['individual_life']['commitment']['status']=='active'
 obs=e.observation_for(s,'human-001').to_dict()
 assert obs['self_state']['individual_life']['commitment']['text'].startswith('Visit')
 other=e.observation_for(s,'human-002').to_dict()
 assert other['self_state']['individual_life']['commitment'] is None
 assert 'Visit Viridian and record what I observe' not in json.dumps(other)
 e.tick_shared_time(store,'gameplay-test',s.simulated_time+1)
 choose(game,'human-001','abandon_commitment',{'text':'I need to rest before travelling'})
 s=state(game);assert s.humans['human-001']['individual_life']['commitment']['status']=='abandoned'
 replay=store.replay('gameplay-test')
 assert replay.to_dict()==s.to_dict()

def test_manual_aspiration_does_not_grant_progress(game):
 before=state(game);after=act(game,'human-001','set_aspiration',{'text':'Become a trusted field researcher'})
 assert after.humans['human-001']['individual_life']['aspiration']['text'].startswith('Become')
 assert after.humans['human-001']['badges']==before.humans['human-001']['badges']


def test_reflection_invalidates_old_actor_proposal(game):
 e,store=game;activate(game);s=state(game)
 _,old=e.capture_decision_boundary(s,'human-001')
 choose(game,'human-001','set_commitment',{'text':'Rest before exploring'})
 with pytest.raises(StaleActionError):
  choose(game,'human-001','wait',{},token=old,version=s.state_version)
