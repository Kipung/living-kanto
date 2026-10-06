import copy
import random
import pytest
from living_kanto.mechanics import BattleSession, create_pokemon
from living_kanto.mechanics.item_rules import ItemError
from living_kanto.mechanics.special_items import use_party_flute, prepare_battle_special
from living_kanto.mechanics.acquisition import source_catalog, acquisition_actions, acquisition_effects, AcquisitionError
from test_gameplay import game, act, scenario, state, starter_and_encounter


def mon(actor, identifier, species='RATTATA', status='slp'):
    p=create_pokemon(species,30,actor,random.Random(2),identifier=identifier)
    p['status']=status;p['moves']=[{'move':'GROWL','pp':40,'max_pp':40}]
    return p


def test_field_flute_owned_party_only_reusable_and_soundproof_not_immune():
    party=[mon('a','first'),mon('a','second','VOLTORB')];party[1]['ability']='SOUNDPROOF'
    trainer={'human_id':'a','party':['first','second'],'inventory':{'poke_flute':{'quantity':1}}}
    before=copy.deepcopy((trainer,party));updated,awake=use_party_flute(trainer,party)
    assert [p['status'] for p in awake]==['','']
    assert updated['inventory']['poke_flute']['quantity']==1 and (trainer,party)==before
    with pytest.raises(ItemError):use_party_flute(trainer,party[:1])
    with pytest.raises(ItemError):use_party_flute({**trainer,'battle_id':'battle'},party)
    with pytest.raises(ItemError):use_party_flute({**trainer,'inventory':{}},party)


def test_battle_flute_private_pending_full_parties_soundproof_and_nightmare():
    parties=[[mon('a','a1'),mon('a','a2'),mon('a','a3','VOLTORB')],[mon('b','b1'),mon('b','b2')]]
    parties[0][2]['ability']='SOUNDPROOF'
    session=BattleSession.start([{'actor_id':actor,'party':party} for actor,party in zip(('a','b'),parties)],[1,2,3,4])
    # Nightmare is an active sleep-dependent volatile in the source.
    side=session.record['result']['state']['sides'][0]
    side['pokemon'][0]['volatiles']['nightmare']={'id':'nightmare','target':side['pokemon'][0].get('fullname')}
    trainer={'human_id':'a','inventory':{'poke_flute':{'quantity':1}}}
    updated,effects=prepare_battle_special(trainer,'poke_flute',wild=False)
    before=session.observation('b')
    assert not session.submit_item('a',parties[0][0],'POKE_FLUTE',effects,expected_version=0)['resolved']
    assert session.observation('b')==before
    session=BattleSession(session.to_dict())
    resolved=session.submit('b',{'type':'move','slot':1},expected_version=0)
    results={p['pokemon_id']:p for p in resolved['pokemon']}
    assert all(results[pid]['status']=='' for pid in ('a1','a2','b1','b2'))
    assert results['a3']['status']=='slp'
    assert results['a1']['moves'][0]['pp']==40 and results['b1']['moves'][0]['pp']==39
    assert 'nightmare' not in session.record['result']['state']['sides'][0]['pokemon'][0]['volatiles']
    assert updated['inventory']['poke_flute']['quantity']==1


def test_double_flute_one_turn_slot_partner_still_moves():
    parties=[[mon(actor,f'{actor}{i}') for i in (1,2,3)] for actor in ('a','b')]
    session=BattleSession.start([{'actor_id':actor,'party':party} for actor,party in zip(('a','b'),parties)],[1,2,3,4],doubles=True)
    effects=prepare_battle_special({'inventory':{'poke_flute':{'quantity':1}}},'poke_flute',wild=False)[1]
    session.submit_item('a',parties[0][0],'POKE_FLUTE',effects,expected_version=0,partner_choice={'type':'move','slot':1})
    r=session.submit('b',{'type':'turn','choices':[{'type':'move','slot':1},{'type':'move','slot':1}]},expected_version=0)
    own=[p for p in r['pokemon'] if p['owner_id']=='a']
    assert all(p['status']=='' for p in r['pokemon'])
    assert own[0]['moves'][0]['pp']==40 and own[1]['moves'][0]['pp']==39


@pytest.mark.parametrize('item',['poke_doll','fluffy_tail'])
def test_escape_items_wild_only_consumed_once_no_mutation(item):
    h={'inventory':{item:{'quantity':2}}};before=copy.deepcopy(h)
    updated,effects=prepare_battle_special(h,item,wild=True)
    assert effects['guaranteed_escape'] and updated['inventory'][item]['quantity']==1 and h==before
    with pytest.raises(ItemError):prepare_battle_special(h,item,wild=False)
    with pytest.raises(ItemError):prepare_battle_special(h,item,wild=True,link_like=True)


def test_wild_doll_engine_escape_no_foe_turn_and_replay(game):
    before=starter_and_encounter(game);engine,store=game;hid='human-001'
    scenario(game,[{'op':'set','path':f'humans.{hid}.inventory.poke_doll','value':{'quantity':1}}])
    before=state(game);record=engine.active_battle(before,hid);pid=before.humans[hid]['party'][0]
    hp=before.pokemon[pid]['hp'];pp=before.pokemon[pid]['moves'][0]['pp']
    after=act(game,hid,'use_field_item',{'item':'poke_doll'})
    assert after.humans[hid]['battle_id'] is None and after.humans[hid]['inventory']['poke_doll']['quantity']==0
    assert after.pokemon[pid]['hp']==hp and after.pokemon[pid]['moves'][0]['pp']==pp
    assert after.world_facts['battles'][record['battle_id']]['outcome']=='fled'
    assert after.world_facts['battles'][record['battle_id']]['turn']==0
    assert store.replay('gameplay-test').state_hash==after.state_hash


def test_prize_items_exact_source_cost_clerk_and_atomic_exchange():
    catalog=source_catalog();items=catalog['item_prizes']
    assert {item:items[item]['coins'] for item in ('TM13','TM23','TM24','TM30','TM35')}=={'TM13':4000,'TM23':3500,'TM24':4000,'TM30':4500,'TM35':4000}
    assert items['SMOKE_BALL']['coins']==800 and items['YELLOW_FLUTE']['coins']==1600
    station=catalog['stations']['tm_prizes']
    h={'human_id':'a',**{k:station[k] for k in ('map_id','x','y')},'inventory':{'coin_case':{'quantity':1}},'acquisition':{'coins':4000},'party':list(range(6)),'box':list(range(420))}
    before=copy.deepcopy(h)
    assert any(a.action=='redeem_prize' and a.arguments=={'item':'TM13'} for a in acquisition_actions(h))
    updated,p,receipt=acquisition_effects(h,'redeem_prize',{'item':'TM13'},random.Random(1))
    assert p is None and updated['acquisition']['coins']==0 and updated['inventory']['TM13']['quantity']==1 and h==before
    with pytest.raises(AcquisitionError):acquisition_effects(h,'redeem_prize',{'item':'TM13','species':'ABRA'},random.Random(1))
    with pytest.raises(AcquisitionError):acquisition_effects(h,'redeem_prize',{'item':'SMOKE_BALL'},random.Random(1))
    with pytest.raises(AcquisitionError):acquisition_effects(updated,'redeem_prize',{'item':'TM13'},random.Random(1))

@pytest.mark.parametrize('doubles',[False,True])
def test_engine_battle_flute_pending_private_and_full_party_commit_replay(game,doubles):
    engine,store=game
    parties=[[mon(actor,f'flute-{actor}-{i}') for i in range(3)] for actor in ('human-001','human-002')]
    session=BattleSession.start([{'actor_id':actor,'party':party} for actor,party in zip(('human-001','human-002'),parties)],[1,2,3,4],doubles=doubles,battle_id='flute-test')
    record={'battle_id':'flute-test','challenger':'human-001','opponent':'human-002','wild':False,'session':session.to_dict(),'turn':0,'outcome':None}
    changes=[{'op':'set','path':f'pokemon.{p["pokemon_id"]}','value':p} for party in parties for p in party]
    for actor,party in zip(('human-001','human-002'),parties):
        changes.extend([{'op':'set','path':f'humans.{actor}.party','value':[p['pokemon_id'] for p in party]}, {'op':'set','path':f'humans.{actor}.battle_id','value':'flute-test'}])
    changes.extend([{'op':'set','path':'humans.human-001.inventory.poke_flute','value':{'quantity':1}}, {'op':'set','path':'world_facts.battles.flute-test','value':record}])
    scenario(game,changes)
    before=state(game);opponent_before=BattleSession(engine.active_battle(before,'human-002')['session']).observation('human-002')
    choice=next(a for a in engine.battle_actions(before,'human-001') if a.action=='use_field_item' and a.arguments['item']=='poke_flute')
    pending=act(game,'human-001',choice.action,choice.arguments)
    assert all(pending.pokemon[p['pokemon_id']]['status']=='slp' for party in parties for p in party)
    assert BattleSession(engine.active_battle(pending,'human-002')['session']).observation('human-002')==opponent_before
    opposite=next(a for a in engine.battle_actions(pending,'human-002') if a.action in ('battle_move','battle_turn'))
    after=act(game,'human-002',opposite.action,opposite.arguments)
    assert all(after.pokemon[p['pokemon_id']]['status']=='' for party in parties for p in party)
    assert after.humans['human-001']['inventory']['poke_flute']['quantity']==1
    assert store.replay('gameplay-test').state_hash==after.state_hash


def test_engine_field_flute_wakes_party_preserves_box(game):
    party=mon('human-001','field-flute-party','VOLTORB');party['ability']='SOUNDPROOF'
    box=mon('human-001','field-flute-box')
    scenario(game,[{'op':'set','path':f'pokemon.{p["pokemon_id"]}','value':p} for p in (party,box)]+[
        {'op':'set','path':'humans.human-001.party','value':[party['pokemon_id']]},
        {'op':'set','path':'humans.human-001.box','value':[box['pokemon_id']]},
        {'op':'set','path':'humans.human-001.inventory.poke_flute','value':{'quantity':1}}])
    after=act(game,'human-001','use_field_item',{'item':'poke_flute'})
    assert after.pokemon[party['pokemon_id']]['status']=='' and after.pokemon[box['pokemon_id']]['status']=='slp'
    assert game[1].replay('gameplay-test').state_hash==after.state_hash
