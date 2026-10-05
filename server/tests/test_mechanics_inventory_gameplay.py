"""Explicit Creative setup, actual engine decisions/commits/replay for inventory and trades."""
import copy
import random
import pytest
from test_gameplay import game,act,locate,scenario,state,starter_and_encounter
from living_kanto.mechanics import create_pokemon, BattleSession
from living_kanto.simulation.engine import EngineError


def test_overworld_potion_and_tm_use_are_atomic_and_replayable(game):
    p=create_pokemon('SQUIRTLE',5,'human-001',random.Random(1),identifier='pokemon-inventory-test');p['hp']=1
    scenario(game,[{'op':'set','path':'pokemon.pokemon-inventory-test','value':p},
        {'op':'set','path':'humans.human-001.party','value':[p['pokemon_id']]},
        {'op':'set','path':'humans.human-001.inventory','value':{'potion':{'item_id':'potion','quantity':1},'tm03':{'item_id':'tm03','quantity':1}}}])
    after=act(game,'human-001','use_item',{'pokemon_id':p['pokemon_id'],'item':'potion'})
    assert after.pokemon[p['pokemon_id']]['hp']==min(p['stats']['hp'],21)
    assert after.humans['human-001']['inventory']['potion']['quantity']==0
    after=act(game,'human-001','teach_machine',{'pokemon_id':p['pokemon_id'],'item':'tm03'})
    assert after.pokemon[p['pokemon_id']]['moves'][-1]['move']=='WATER_PULSE'
    assert after.humans['human-001']['inventory']['tm03']['quantity']==0
    assert game[1].replay('gameplay-test').state_hash==after.state_hash


def test_battle_potion_consumes_trainer_turn_and_preserves_attack_pp(game):
    before=starter_and_encounter(game);engine,store=game;hid='human-001';pid=before.humans[hid]['party'][0]
    # Damage the persistent individual and restart the actual encounter fixture so
    # simulator state reflects the explicit injury; no outcome is fabricated.
    record=engine.active_battle(before,hid);session=BattleSession(record['session'])
    mon=copy.deepcopy(before.pokemon[pid]);mon['hp']=1
    session.synchronize_individuals([mon]);record=copy.deepcopy(record);record['session']=session.to_dict()
    scenario(game,[{'op':'set','path':f'pokemon.{pid}.hp','value':1}, {'op':'set','path':f'world_facts.battles.{record["battle_id"]}','value':record}])
    initial=state(game);pp=initial.pokemon[pid]['moves'][0]['pp'];balls=initial.humans[hid]['inventory']['potion']['quantity']
    after=act(game,hid,'use_item',{'pokemon_id':pid,'item':'potion'})
    assert after.pokemon[pid]['hp']>1
    assert after.pokemon[pid]['moves'][0]['pp']==pp
    assert after.humans[hid]['inventory']['potion']['quantity']==balls-1
    assert after.world_facts['battles'][record['battle_id']]['turn']==1
    assert store.replay('gameplay-test').state_hash==after.state_hash


def trade_fixture(game):
    p1=create_pokemon('KADABRA',20,'human-001',random.Random(1),identifier='pokemon-trade-one')
    p2=create_pokemon('MACHOKE',20,'human-002',random.Random(2),identifier='pokemon-trade-two')
    locate(game,'human-001','PalletTown',(10,10));locate(game,'human-002','PalletTown',(11,10))
    scenario(game,[{'op':'set','path':f'pokemon.{p["pokemon_id"]}','value':p} for p in (p1,p2)]+
        [{'op':'set','path':f'humans.{p["owner_id"]}.party','value':[p['pokemon_id']]} for p in (p1,p2)])
    after=act(game,'human-001','trade_offer',{'human_id':'human-002','pokemon_id':p1['pokemon_id'],'wanted_species':'MACHOKE'})
    tid=next(iter(after.world_facts['trade_offers']))
    return p1,p2,tid


def test_explicit_offer_counterpart_final_accept_transfers_same_individual_atomically(game):
    p1,p2,tid=trade_fixture(game)
    counter=act(game,'human-002','trade_accept',{'trade_id':tid,'pokemon_id':p2['pokemon_id']})
    assert counter.pokemon[p1['pokemon_id']]['owner_id']=='human-001'
    assert counter.pokemon[p2['pokemon_id']]['owner_id']=='human-002'
    after=act(game,'human-001','trade_accept',{'trade_id':tid})
    assert after.humans['human-001']['party']==[p2['pokemon_id']]
    assert after.humans['human-002']['party']==[p1['pokemon_id']]
    assert after.pokemon[p1['pokemon_id']]['owner_id']=='human-002' and after.pokemon[p1['pokemon_id']]['species']=='ALAKAZAM'
    assert after.pokemon[p2['pokemon_id']]['owner_id']=='human-001' and after.pokemon[p2['pokemon_id']]['species']=='MACHAMP'
    assert after.pokemon[p1['pokemon_id']]['personality']==p1['personality']
    assert game[1].replay('gameplay-test').state_hash==after.state_hash
    with pytest.raises(EngineError):act(game,'human-001','trade_accept',{'trade_id':tid})
    assert state(game).state_hash==after.state_hash


def test_trade_rejects_changed_individual_and_decline_never_transfers(game):
    p1,p2,tid=trade_fixture(game)
    act(game,'human-002','trade_accept',{'trade_id':tid,'pokemon_id':p2['pokemon_id']})
    scenario(game,[{'op':'set','path':f'pokemon.{p2["pokemon_id"]}.hp','value':1}])
    before=state(game)
    with pytest.raises(EngineError,match='changed'):act(game,'human-001','trade_accept',{'trade_id':tid})
    assert state(game).state_hash==before.state_hash
    after=act(game,'human-002','trade_decline',{'trade_id':tid})
    assert after.pokemon[p1['pokemon_id']]['owner_id']=='human-001' and after.pokemon[p2['pokemon_id']]['owner_id']=='human-002'

def test_source_stone_shop_paid_human_queue_and_replay(game):
    locate(game,'human-001','CeladonCity_DepartmentStore_4F',(5,5));locate(game,'human-002','CeladonCity_DepartmentStore_4F',(6,5))
    scenario(game,[{'op':'set','path':'humans.human-001.money','value':3000},{'op':'set','path':'humans.human-002.role','value':'shop_staff'}])
    queued=act(game,'human-001','shop_buy',{'item':'water_stone','quantity':1})
    assert queued.humans['human-001']['money']==900
    assert queued.humans['human-001'].get('service_request')
    service=game[0].service_actions(queued,'human-002')[0]
    after=act(game,'human-002',service.action,service.arguments)
    assert after.humans['human-001']['inventory']['water_stone']['quantity']==1
    assert game[1].replay('gameplay-test').state_hash==after.state_hash

def test_all_mainland_source_services_staffed_without_role_changes(game):
    engine,store=game;s=state(game)
    required={('healing',mid) for mid in engine.maps if 'PokemonCenter_1F' in mid}|{('shop',mid) for mid in engine.maps if engine.shop_prices(mid)}
    assigned={(h['service_assignment']['kind'],h['service_assignment']['map_id']) for h in s.humans.values() if h.get('service_assignment')}
    assert required.issubset(assigned)
    assert sum(h['role']=='service_staff' for h in s.humans.values())==20
    assert sum(h['role']=='shop_staff' for h in s.humans.values())==10
