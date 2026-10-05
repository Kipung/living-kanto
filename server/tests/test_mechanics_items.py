import copy
import random
import pytest
from living_kanto.mechanics import create_pokemon
from living_kanto.mechanics.item_rules import *


def owner(species='BULBASAUR',level=15,item='potion',quantity=1,actor='a'):
    p=create_pokemon(species,level,actor,random.Random(1))
    t={'human_id':actor,'party':[p['pokemon_id']],'box':[],'inventory':{item:{'quantity':quantity}},'pokedex':[]}
    return t,p

def test_reference_machine_and_tutor_coverage():
    assert len(machine_learnsets())==len(tutor_learnsets())==151
    machines=[k for k in item_catalog() if k.startswith(('TM','HM')) and 'move' in item_catalog()[k]]
    assert len(machines)==58
    for species,items in machine_learnsets().items():
        assert all(item in machines and item_catalog()[item]['move'] in data()['moves'] for item in items)
    assert 'TM03' in machine_learnsets()['SQUIRTLE']
    assert 'HM03' not in machine_learnsets()['BULBASAUR']
    assert 'SUBSTITUTE' in tutor_learnsets()['BULBASAUR']

def test_healing_exact_source_amount_no_mutation_no_effect():
    t,p=owner();p['hp']=1
    before=copy.deepcopy((t,p))
    newt,newp,event=apply_item(t,p,'POTION')
    assert newp['hp']==min(p['stats']['hp'],21) and newt['inventory']['potion']['quantity']==0
    assert (t,p)==before
    with pytest.raises(ItemError):apply_item(t,{**p,'hp':p['stats']['hp']},'POTION')
    assert (t,p)==before
    t,p=owner(item='hyper_potion',level=100);p['hp']=1
    assert apply_item(t,p,'HYPER_POTION')[1]['hp']==201

def test_status_revive_and_herb_friendship():
    t,p=owner(item='antidote');p['status']='tox'
    assert apply_item(t,p,'ANTIDOTE')[1]['status']==''
    t,p=owner(item='revive');p['hp']=0
    assert apply_item(t,p,'REVIVE')[1]['hp']==p['stats']['hp']//2
    with pytest.raises(ItemError):apply_item(t,{**p,'hp':1},'REVIVE')
    t,p=owner(item='energy_root');p['hp']=1;p['friendship']=210
    assert apply_item(t,p,'ENERGY_ROOT')[1]['friendship']==195

def test_pp_restoration_boost_caps_and_slot_validation():
    t,p=owner(item='ether');p['moves'][0]['pp']=0
    healed=apply_item(t,p,'ETHER',move_slot=1)[1]
    assert healed['moves'][0]['pp']==10
    t['inventory']={'pp_up':{'quantity':4}}
    for _ in range(3):t,p,_=apply_item(t,p,'PP_UP',move_slot=1)
    assert p['moves'][0]['max_pp']==data()['moves'][p['moves'][0]['move']]['pp']*8//5
    with pytest.raises(ItemError):apply_item(t,p,'PP_UP',move_slot=1)
    assert t['inventory']['pp_up']['quantity']==1
    with pytest.raises(ItemError):apply_item(t,p,'PP_UP',move_slot=0)

def test_vitamins_and_rare_candy_source_caps_and_revive():
    t,p=owner(item='protein',quantity=11)
    for _ in range(10):t,p,_=apply_item(t,p,'PROTEIN')
    assert p['evs']['atk']==100
    with pytest.raises(ItemError):apply_item(t,p,'PROTEIN')
    t,p=owner(item='rare_candy');p['hp']=0;before=p['stats']['hp']
    t,p,_=apply_item(t,p,'RARE_CANDY')
    assert p['level']==16 and p['hp']==p['stats']['hp']-before
    assert evolution_options(p)==['IVYSAUR']

def test_stone_consumes_only_valid_evolution_same_pid():
    t,p=owner('EEVEE',item='water_stone');pid=p['pokemon_id'];personality=p['personality']
    nt,np,_=apply_item(t,p,'WATER_STONE')
    assert np['species']=='VAPOREON' and np['pokemon_id']==pid and np['personality']==personality
    assert nt['inventory']['water_stone']['quantity']==0
    t,p=owner(item='water_stone')
    with pytest.raises(ItemError):apply_item(t,p,'WATER_STONE')
    assert t['inventory']['water_stone']['quantity']==1

def test_tm_consumable_hm_reusable_compatible_species_and_hm_protection():
    t,p=owner('SQUIRTLE',level=5,item='tm03')
    nt,np,_=teach_machine(t,p,'TM03')
    assert nt['inventory']['tm03']['quantity']==0 and np['moves'][-1]['move']=='WATER_PULSE'
    t,p=owner('BULBASAUR',level=5,item='hm01')
    nt,np,_=teach_machine(t,p,'HM01')
    assert nt['inventory']['hm01']['quantity']==1 and np['moves'][-1]['move']=='CUT'
    t=nt;p=np;t['inventory']['tm06']={'quantity':1}
    with pytest.raises(ItemError):teach_machine(t,p,'TM06',replace_slot=len(p['moves']))
    t,p=owner('BULBASAUR',level=5,item='hm03')
    with pytest.raises(ItemError):teach_machine(t,p,'HM03')
    t,p=owner('BULBASAUR',level=5,item='hm01',quantity=0)
    with pytest.raises(ItemError):teach_machine(t,p,'HM01')

def offers(t1,p1,t2,p2,version=7):
    return [{'actor_id':t['human_id'],'trade_id':'trade-one','accepted':True,'state_version':version,'offered_pokemon':p['pokemon_id'],'requested_pokemon':other['pokemon_id']} for t,p,other in ((t1,p1,p2),(t2,p2,p1))]

def test_trade_two_accepted_offers_swaps_same_individual_evolves_and_atomic():
    t1,p1=owner('KADABRA',actor='a');t2,p2=owner('MACHOKE',actor='b')
    # Same RNG creates same ID; realistic instances have distinct identities.
    p2['pokemon_id']='pokemon-second';t2['party']=['pokemon-second']
    initial=copy.deepcopy((t1,p1,t2,p2));accepted=offers(t1,p1,t2,p2)
    a,received_a,b,received_b,event=trade_exchange(t1,p1,t2,p2,offers=accepted,expected_state_version=7)
    assert received_a['species']=='MACHAMP' and received_b['species']=='ALAKAZAM'
    assert a['party']==[p2['pokemon_id']] and b['party']==[p1['pokemon_id']]
    assert received_b['personality']==p1['personality'] and received_a['friendship']==70
    assert (t1,p1,t2,p2)==initial
    accepted[1]['accepted']=False
    with pytest.raises(ItemError):trade_exchange(t1,p1,t2,p2,offers=accepted,expected_state_version=7)
    assert (t1,p1,t2,p2)==initial

def test_trade_everstone_blocks_evolution_and_no_level_evolution_on_trade():
    t1,p1=owner('BULBASAUR',level=30,actor='a');t2,p2=owner('KADABRA',actor='b');p2['pokemon_id']='pokemon-second';t2['party']=['pokemon-second'];p2['held_item']='EVERSTONE'
    result=trade_exchange(t1,p1,t2,p2,offers=offers(t1,p1,t2,p2),expected_state_version=7)
    assert result[1]['species']=='KADABRA' and result[3]['species']=='BULBASAUR'

def test_full_heal_confusion_and_gen3_x_item_stage_limits():
    t,p=owner(item='full_heal')
    nt,np,event=apply_item(t,p,'FULL_HEAL',battle=True,battle_conditions={'active':True,'confusion':True})
    assert event['battle_effects']=={'cure_confusion':True} and nt['inventory']['full_heal']['quantity']==0
    t,p=owner(item='x_attack')
    nt,np,event=apply_item(t,p,'X_ATTACK',battle=True,battle_conditions={'active':True,'boosts':{'atk':0}})
    assert event['battle_effects']=={'boost':{'atk':1}}
    assert np['friendship']==p['friendship']+1
    with pytest.raises(ItemError):apply_item(t,p,'X_ATTACK',battle=True,battle_conditions={'active':True,'boosts':{'atk':6}})
    with pytest.raises(ItemError):apply_item(t,p,'X_ATTACK',battle=True,battle_conditions={'active':False})

def test_source_pp_max_maximizes_five_pp_move():
    t,p=owner('CHARMANDER',item='pp_max')
    p['moves']=[{'move':'FIRE_BLAST','pp':5,'max_pp':5}]
    nt,np,event=apply_item(t,p,'PP_MAX',move_slot=1)
    assert np['moves'][0]['max_pp']==8 and np['moves'][0]['pp']==8
    assert nt['inventory']['pp_max']['quantity']==0

def test_battle_bag_item_pending_private_and_restored_x_accuracy():
    from living_kanto.mechanics import BattleSession
    t,p=owner(level=30,item='x_accuracy')
    p['moves']=[{'move':'GROWL','pp':40,'max_pp':40}]
    foe=create_pokemon('CHARMANDER',30,'b',random.Random(2));foe['moves']=[{'move':'GROWL','pp':40,'max_pp':40}]
    s=BattleSession.start([{'actor_id':'a','party':[p]},{'actor_id':'b','party':[foe]}],[1,2,3,4])
    before=s.observation('b')
    nt,np,event=apply_item(t,p,'X_ACCURACY',battle=True,battle_conditions=s.item_context('a',p['pokemon_id']))
    result=s.submit_item('a',np,event['item'],event['battle_effects'],expected_version=0)
    assert not result['resolved'] and s.observation('b')==before
    s=BattleSession(s.to_dict());result=s.submit('b',{'type':'move','slot':1},expected_version=0)
    own=next(p for p in result['pokemon'] if p['owner_id']=='a')
    assert own['moves'][0]['pp']==40
    assert s.item_context('a',p['pokemon_id'])['boosts']['accuracy']==1
    assert nt['inventory']['x_accuracy']['quantity']==0

def test_source_item_friendship_origin_region_soothe_luxury_order():
    t,p=owner(item='rare_candy');t['map_id']='PalletTown_ProfessorOaksLab'
    p['origin_map_id']='PalletTown';p['held_item']='SOOTHE_BELL';p['pokeball']='LUXURY_BALL'
    before=p['friendship'];nt,np,event=apply_item(t,p,'RARE_CANDY')
    assert np['friendship']==before+9 # floor(5*1.5)+Luxury1+same region1, once.
    assert p['friendship']==before
    t,p=owner(item='protein');t['map_id']='PalletTown_ProfessorOaksLab'
    p['origin_map_id']='PalletTown';p['held_item']='SOOTHE_BELL';p['pokeball']='LUXURY_BALL'
    _,np,_=apply_item(t,p,'PROTEIN');assert np['friendship']==p['friendship']+9
