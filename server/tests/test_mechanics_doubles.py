import random
import pytest
from living_kanto.mechanics import BattleSession, BattleError, create_pokemon


def doubles():
    rng=random.Random(15)
    teams=[{'actor_id':a,'party':[create_pokemon('BULBASAUR',20,a,rng),create_pokemon('SQUIRTLE',20,a,rng),create_pokemon('PIDGEY',20,a,rng)]} for a in ('a','b')]
    for team in teams:
        for p in team['party']:p['moves']=[{'move':'TACKLE','pp':35,'max_pp':35}]
    return BattleSession.start(teams,[1,2,3,4],doubles=True)


def choices(first=1,second=1):
    return {'type':'turn','choices':[{'type':'move','slot':first,'target':1},{'type':'move','slot':second,'target':2}]}


def test_doubles_opponent_choices_hidden_and_two_actors_resolve():
    s=doubles();before=s.observation('b')
    assert len(s.observation('a')['request']['active'])==2
    assert not s.submit('a',choices(),expected_version=0)['resolved']
    assert s.observation('b')==before
    r=s.submit('b',choices(),expected_version=0)
    assert r['resolved']
    assert len(r['pokemon'])==6
    assert sum(m['pp'] for p in r['pokemon'] if p['owner_id']=='a' for m in p['moves']) < sum(m['pp'] for p in s.record['teams'][0]['party'] for m in p['moves'])


def test_doubles_incomplete_turn_duplicate_switch_and_invalid_target_do_not_commit():
    s=doubles();before=s.to_dict()
    for action in ({'type':'move','slot':1},{'type':'turn','choices':[{'type':'switch','slot':3},{'type':'switch','slot':3}]}, {'type':'turn','choices':[{'type':'move','slot':1,'target':3},{'type':'move','slot':1,'target':2}]}):
        with pytest.raises(BattleError):s.submit('a',action,expected_version=0)
        assert s.to_dict()==before


def test_doubles_restart_pending_and_ally_target():
    s=doubles();a=choices();a['choices'][0]['target']=-2
    s.submit('a',a,expected_version=0)
    restored=BattleSession(s.to_dict())
    r1=s.submit('b',choices(),expected_version=0)
    r2=restored.submit('b',choices(),expected_version=0)
    assert r1==r2 and s.to_dict()==restored.to_dict()

def test_gen_three_surf_hits_both_foes_but_leaves_partner_unhurt():
    rng=random.Random(41)
    own=[create_pokemon('BLASTOISE',100,'a',rng),create_pokemon('BULBASAUR',20,'a',rng)]
    foes=[create_pokemon('GEODUDE',5,'b',rng),create_pokemon('GEODUDE',5,'b',rng)]
    own[0]['moves']=[{'move':'SURF','pp':15,'max_pp':15}]
    for p in [own[1],*foes]:p['moves']=[{'move':'DEFENSE_CURL','pp':40,'max_pp':40}]
    s=BattleSession.start([{'actor_id':'a','party':own},{'actor_id':'b','party':foes}],[1,2,3,4],doubles=True)
    turn={'type':'turn','choices':[{'type':'move','slot':1},{'type':'move','slot':1}]}
    s.submit('a',turn,expected_version=0);result=s.submit('b',turn,expected_version=0)
    assert result['ended'] and result['winner']=='a'
    assert next(p for p in result['pokemon'] if p['pokemon_id']==own[1]['pokemon_id'])['hp']==own[1]['hp']
    assert all(p['hp']==0 for p in result['pokemon'] if p['owner_id']=='b')
