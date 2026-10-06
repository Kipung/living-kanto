import copy
import random
from types import SimpleNamespace
import pytest
from living_kanto.mechanics import create_pokemon
from living_kanto.mechanics.field_steps import field_steps
from living_kanto.mechanics.item_rules import ItemError
from living_kanto.mechanics.utility_items import use_vs_seeker, vs_charge, invitation_live, use_fame_checker
from living_kanto.mechanics.acquisition import source_catalog, acquisition_actions, acquisition_effects, AcquisitionError
from living_kanto.simulation.hidden_items import response, use_itemfinder, front_candidates, collect
from living_kanto.simulation import pickups
from living_kanto.simulation.engine import EngineError
from test_gameplay import game, act, scenario, state, locate


def map_fixture(map_id='TestFinder',rows=None,connections=None):
    return SimpleNamespace(map_id=map_id,width=20,height=20,reference_id='MAP_'+map_id,
                           cells={},events={'bg_events':rows or [],'connections':connections or []})


def hidden(x,y,item='ITEM_POTION',flag='FLAG_TEST_ITEM',quantity=1,underfoot=False):
    return {'type':'hidden_item','x':x,'y':y,'elevation':0,'item':item,'flag':flag,'quantity':quantity,'underfoot':underfoot}


def finder_actor(**extra):
    return {'human_id':'a','map_id':'TestFinder','x':10,'y':10,'facing':'north','party':[],
            'inventory':{'itemfinder':{'quantity':1}}, **extra}


def test_hidden_requires_facing_not_underfoot_and_coins_atomic_full_cap():
    h=finder_actor();m=map_fixture(rows=[hidden(10,9),hidden(10,10,underfoot=True,flag='FLAG_UNDERFOOT')])
    assert front_candidates(h,m)==[m.events['bg_events'][0]]
    assert front_candidates({**h,'facing':'east'},m)==[]
    before=copy.deepcopy(h);updated=collect(h,hidden(10,9,quantity=3))
    assert updated['inventory']['potion']['quantity']==3 and h==before
    assert not front_candidates(updated,m)
    coin=hidden(10,9,item='ITEM_NONE',quantity=20)
    with pytest.raises(ItemError,match='Coin Case'):collect(h,coin)
    h['inventory']['coin_case']={'quantity':1};h['acquisition']={'coins':9980}
    before=copy.deepcopy(h)
    with pytest.raises(ItemError,match='full'):collect(h,coin)
    assert h==before and not h.get('collected_hidden_items')
    h['acquisition']['coins']=9979;updated=collect(h,coin)
    assert updated['acquisition']['coins']==9999 and 'none' not in updated['inventory']


def test_itemfinder_source_range_strength_ties_and_no_response_reusable():
    h=finder_actor();empty=map_fixture()
    updated,receipt=use_itemfinder(h,empty,{empty.map_id:empty})
    assert receipt['response']=='none' and updated['inventory']==h['inventory']
    assert (updated['x'],updated['y'])==(10,10)
    m=map_fixture(rows=[hidden(17,15)])
    assert response(h,m,{m.map_id:m})[0]=={'response':'nearby','direction':'east','strength_beeps':2}
    m.events['bg_events']=[hidden(18,10),hidden(10,16)]
    assert response(h,m,{m.map_id:m})[0]['response']=='none'
    m.events['bg_events']=[hidden(8,9),hidden(12,11,flag='OTHER')]
    assert response(h,m,{m.map_id:m})[0]=={'response':'nearby','direction':'east','strength_beeps':4}
    # Source first prefers smaller absolute Y, then positive Y, then event order.
    m.events['bg_events']=[hidden(11,12),hidden(7,10,flag='OTHER')]
    assert response(h,m,{m.map_id:m})[0]['direction']=='west'
    h['collected_hidden_items']=['OTHER']
    assert response(h,m,{m.map_id:m})[0]['direction']=='south'


def test_itemfinder_connected_map_offsets_and_underfoot_ignored():
    h=finder_actor(x=19,y=5)
    m=map_fixture(connections=[{'map':'OtherFinder','direction':'right','offset':2}])
    other=map_fixture('OtherFinder',[hidden(0,3,flag='FLAG_CONNECTED'),hidden(0,3,flag='FLAG_UNDER',underfoot=True)])
    receipt,row=response(h,m,{m.map_id:m,other.map_id:other})
    assert receipt['direction']=='east' and row is None
    h['collected_hidden_items']=['FLAG_CONNECTED']
    assert response(h,m,{m.map_id:m,other.map_id:other})[0]['response']=='none'


def test_underfoot_itemfinder_source_quantity_one_no_teleport_bag_full_no_claim():
    h=finder_actor();m=map_fixture(rows=[hidden(10,10,item='ITEM_LEFTOVERS',quantity=5,underfoot=True)])
    before=copy.deepcopy(h);updated,receipt=use_itemfinder(h,m,{m.map_id:m})
    assert receipt['response']=='underfoot' and receipt['strength_beeps']==3
    assert updated['inventory']['leftovers']['quantity']==1 and updated['collected_hidden_items']==['FLAG_TEST_ITEM']
    assert (updated['x'],updated['y'])==(h['x'],h['y']) and h==before
    assert use_itemfinder(updated,m,{m.map_id:m})[1]['response']=='none'
    h['inventory']['leftovers']={'quantity':999}
    updated,receipt=use_itemfinder(h,m,{m.map_id:m})
    assert 'collection_error' in receipt and updated['inventory']['leftovers']['quantity']==999 and 'collected_hidden_items' not in updated
    # Underfoot specials are undetectable from an adjacent tile.
    assert response(finder_actor(x=9),m,{m.map_id:m})[0]['response']=='none'


def test_hidden_pickup_source_front_engine_replay_and_per_trainer(game):
    engine,store=game;mid='Route10';h='human-001'
    locate(game,h,mid,(10,20));scenario(game,[{'op':'set','path':f'humans.{h}.facing','value':'north'}])
    before=state(game);choice=next(a for a in engine.legal_actions(before,h) if a.action=='pick_up_item' and a.arguments['object_id'].startswith('hidden:'))
    after=act(game,h,choice.action,choice.arguments)
    assert after.humans[h]['inventory']['super_potion']['quantity']>=1
    assert 'FLAG_HIDDEN_ITEM_ROUTE10_SUPER_POTION' in after.humans[h]['collected_hidden_items']
    assert not any(a.arguments==choice.arguments for a in engine.legal_actions(after,h))
    with pytest.raises(EngineError):act(game,h,choice.action,choice.arguments)
    locate(game,'human-002',mid,(10,20));scenario(game,[{'op':'set','path':'humans.human-002.facing','value':'north'}])
    after=act(game,'human-002',choice.action,choice.arguments)
    assert after.humans['human-002']['inventory']['super_potion']['quantity']>=1
    assert store.replay('gameplay-test').state_hash==after.state_hash


def test_underfoot_leftovers_actual_route_itemfinder_engine_replay(game):
    # Explicit Creative placement tests the source dig; ordinary movement still owns collision.
    locate(game,'human-001','Route12',(14,70))
    scenario(game,[{'op':'set','path':'humans.human-001.inventory.itemfinder','value':{'quantity':1}}])
    before=state(game);after=act(game,'human-001','use_field_item',{'item':'itemfinder'})
    assert after.humans['human-001']['inventory']['leftovers']['quantity']==1
    assert after.humans['human-001']['inventory']['itemfinder']['quantity']==1
    assert (after.humans['human-001']['x'],after.humans['human-001']['y'])==(14,70)
    assert 'FLAG_HIDDEN_ITEM_ROUTE12_LEFTOVERS' in after.humans['human-001']['collected_hidden_items']
    again=act(game,'human-001','use_field_item',{'item':'itemfinder'})
    assert again.humans['human-001']['inventory']['leftovers']['quantity']==1
    assert game[1].replay('gameplay-test').state_hash==again.state_hash


def vs_fixture():
    a={'human_id':'a','map_id':'PalletTown','x':10,'y':10,'party':['pa'],'inventory':{'vs_seeker':{'quantity':1}},'field_steps':{'walked':100}}
    b={'human_id':'b','map_id':'PalletTown','x':11,'y':10,'party':['pb'],'inventory':{}}
    mons={pid:create_pokemon('RATTATA',10,actor,random.Random(i),identifier=pid) for i,(pid,actor) in enumerate((('pa','a'),('pb','b')))}
    records={'old':{'challenger':'a','opponent':'b','wild':False,'ended':True,'outcome':'a'}}
    return SimpleNamespace(humans={'a':a,'b':b},pokemon=mons,world_facts={'battles':records},state_version=4,simulated_time=20)


def test_vs_source_walking_charge_invitation_no_scripted_acceptance_or_rewards():
    s=vs_fixture();h=s.humans['a'];before=copy.deepcopy(s.world_facts)
    updated,offers,receipt=use_vs_seeker(s,h)
    assert receipt['response']=='invitations_sent' and vs_charge(updated)==0
    assert len(offers)==1 and next(iter(offers.values()))['status']=='pending' and not updated.get('battle_id')
    assert s.world_facts==before and updated['inventory']==h['inventory']
    for _ in range(99):updated,_,_=field_steps(updated,[s.pokemon['pa']],random.Random(1))
    assert vs_charge(updated)==99
    updated,_,_=field_steps(updated,[s.pokemon['pa']],random.Random(1))
    assert vs_charge(updated)==100
    offer=next(iter(offers.values()));s.humans['b']['map_visit']=1
    assert not invitation_live(s,offer) # leaving and returning cannot resurrect an invitation
    s.humans['b']['map_visit']=0
    s.humans['a']=updated
    assert not invitation_live(s,offer) # exactly100subsequent tiles expires the invitation
    with pytest.raises(ItemError,match='outdoor'):use_vs_seeker(s,{**updated,'map_id':'ViridianForest'})
    with pytest.raises(ItemError,match='outdoor'):use_vs_seeker(s,{**updated,'map_id':'PewterCity_Gym'})
    s=vs_fixture();s.world_facts['battles']={};s.humans['a']['memories']={'0':{'text':'I fought b'}}
    updated,offers,receipt=use_vs_seeker(s,s.humans['a'])
    assert not offers and vs_charge(updated)==100 and receipt['response']=='no_rematch_entities_in_range'
    s.humans['a']['field_steps']['walked']=99
    assert use_vs_seeker(s,s.humans['a'])[2]['steps_remaining']==1


def test_fame_checker_only_seen_public_canonical_residents_stale_snapshot():
    h={'human_id':'a','map_id':'PewterCity','x':10,'y':10,'inventory':{'fame_checker':{'quantity':1}}}
    brock={'human_id':'b','name':'Brock','role':'gym_leader','setup_role':'gym_leader','map_id':'PewterCity','x':11,'y':10,'badges':[],
           'biography':'secret biography','memories':{'private':'secret'},'party':['secret-pokemon'],'goal':{'text':'secret goal'}}
    misty={**brock,'human_id':'m','name':'Misty','map_id':'CeruleanCity'}
    s=SimpleNamespace(humans={'a':h,'b':brock,'m':misty},simulated_time=10)
    updated,receipt=use_fame_checker(s,h)
    assert [r['name'] for r in receipt['residents']]==['Brock'] and 'secret' not in str(receipt)
    assert receipt['residents'][0]['office_provenance']=='declared_initial_setup' and receipt['residents'][0]['public_badges']==[]
    brock.update(map_id='CeruleanCity',badges=['Cascade']);s.simulated_time=20
    updated2,receipt2=use_fame_checker(s,updated)
    assert receipt2['residents'][0]['last_observed_map']=='PewterCity' and receipt2['residents'][0]['public_badges']==[]
    assert updated2['inventory']['fame_checker']['quantity']==1 and h.get('utility_items') is None


@pytest.mark.parametrize('gift',['vs_seeker','fame_checker','itemfinder'])
def test_utility_gifts_source_stations_claim_once_species_gate(gift):
    station=source_catalog()['stations'][gift]
    h={'human_id':'a','map_id':station['map_id'],'x':station['x'],'y':station['y']+1,'inventory':{},'field_steps':{'walked':500},'pokedex':[]}
    if gift=='itemfinder':
        assert not any(a.arguments=={'gift_id':gift} for a in acquisition_actions(h))
        from living_kanto.mechanics.reference import data
        h['pokedex']=list(data()['species'])[:30]
    updated,p,_=acquisition_effects(h,'acquire_key_gift',{'gift_id':gift},random.Random(1))
    assert p is None and updated['inventory'][gift.upper()]['quantity']==1
    if gift=='vs_seeker':assert vs_charge(updated)==0
    with pytest.raises(AcquisitionError):acquisition_effects(updated,'acquire_key_gift',{'gift_id':gift},random.Random(1))


def test_vs_engine_invites_actual_entity_acceptance_no_automatic_battle(game):
    engine,store=game;actors=('human-001','human-002')
    mons=[create_pokemon('RATTATA',15,actor,random.Random(i),identifier=f'vs-mon-{i}') for i,actor in enumerate(actors)]
    changes=[]
    for i,(actor,p) in enumerate(zip(actors,mons)):
        changes.extend([{'op':'set','path':f'pokemon.{p["pokemon_id"]}','value':p},
                        {'op':'set','path':f'humans.{actor}.party','value':[p['pokemon_id']]},
                        {'op':'set','path':f'humans.{actor}.map_id','value':'PalletTown'},
                        {'op':'set','path':f'humans.{actor}.x','value':10+i},
                        {'op':'set','path':f'humans.{actor}.y','value':10}])
    changes.extend([{'op':'set','path':'humans.human-001.inventory.vs_seeker','value':{'quantity':1}},
                    {'op':'set','path':'humans.human-001.field_steps.walked','value':100},
                    {'op':'set','path':'world_facts.battles.old-vs-fixture','value':{'ended':True,'challenger':actors[0],'opponent':actors[1],'wild':False,'outcome':actors[0]}}])
    scenario(game,changes)
    before=state(game);money=[before.humans[a]['money'] for a in actors];xp=[before.pokemon[p['pokemon_id']]['experience'] for p in mons]
    pending=act(game,actors[0],'use_field_item',{'item':'vs_seeker'})
    assert pending.humans[actors[0]].get('battle_id') is None and pending.humans[actors[1]].get('battle_id') is None
    cid=pending.humans[actors[0]]['last_vs_seeker']['invitations'][0]
    assert any(a.action=='accept_challenge' and a.arguments=={'challenge_id':cid} for a in engine.legal_actions(pending,actors[1]))
    after=act(game,actors[1],'accept_challenge',{'challenge_id':cid})
    assert after.humans[actors[0]]['battle_id']==after.humans[actors[1]]['battle_id']
    assert [after.humans[a]['money'] for a in actors]==money
    assert [after.pokemon[p['pokemon_id']]['experience'] for p in mons]==xp
    record=engine.active_battle(after,actors[0]);assert record['personal_duel'] and record['session']['challenge']['kind']=='personal'
    assert store.replay('gameplay-test').state_hash==after.state_hash


def test_fame_checker_engine_read_public_notes_no_private_mutations_replay(game):
    engine,store=game;hid='human-001'
    brock=next(actor for actor,person in state(game).humans.items() if person['name']=='Brock')
    locate(game,hid,'PewterCity',(10,10));locate(game,brock,'PewterCity',(11,10))
    scenario(game,[{'op':'set','path':f'humans.{hid}.inventory.fame_checker','value':{'quantity':1}}])
    before=state(game);after=act(game,hid,'use_field_item',{'item':'fame_checker'})
    notes=after.humans[hid]['last_fame_checker']['residents']
    assert any(note['human_id']==brock for note in notes)
    assert all(after.humans[brock].get(key)==before.humans[brock].get(key) for key in ('biography','memories','party','box','relationships','badges','goal'))
    assert after.pokemon==before.pokemon
    assert after.humans[hid]['inventory']==before.humans[hid]['inventory']
    assert all('biography' not in note and 'party' not in note and 'memories' not in note for note in notes)
    assert store.replay('gameplay-test').state_hash==after.state_hash
