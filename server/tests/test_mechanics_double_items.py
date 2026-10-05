import copy,random,pytest
from living_kanto.mechanics import BattleSession,create_pokemon
from living_kanto.mechanics.battle import BattleError

def test_source_double_item_occupies_one_battler_partner_still_acts():
    teams=[]
    for actor in ('a','b'):
        party=[create_pokemon('RATTATA',20,actor,random.Random(i),identifier=f'pokemon-item-{actor}-{i}') for i in (1,2)]
        for p in party:p['moves']=[{'move':'GROWL','pp':40,'max_pp':40}]
        teams.append({'actor_id':actor,'party':party})
    teams[0]['party'][0]['hp']-=10
    s=BattleSession.start(teams,[1,2,3,4],doubles=True)
    p=copy.deepcopy(teams[0]['party'][0]);p['hp']=p['stats']['hp']
    with pytest.raises(BattleError):s.submit_item('a',p,'POTION',{},expected_version=0,partner_choice={'type':'move','slot':4})
    assert s.record['pending']=={}
    assert not s.submit_item('a',p,'POTION',{},expected_version=0,partner_choice={'type':'move','slot':1})['resolved']
    r=s.submit('b',{'type':'turn','choices':[{'type':'move','slot':1},{'type':'move','slot':1}]},expected_version=0)
    own=[p for p in r['pokemon'] if p['owner_id']=='a']
    assert own[0]['hp']==own[0]['max_hp'] and own[0]['moves'][0]['pp']==40
    assert own[1]['moves'][0]['pp']==39
    linked=BattleSession.start(teams,[1,2,3,4],doubles=True,challenge={'kind':'personal'})
    with pytest.raises(BattleError,match='prohibit'):linked.submit_item('a',p,'POTION',{},expected_version=0,partner_choice={'type':'move','slot':1})
