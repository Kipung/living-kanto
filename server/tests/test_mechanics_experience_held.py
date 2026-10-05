import copy,random,pytest
from living_kanto.mechanics import create_pokemon
from living_kanto.mechanics.experience import experience_distribution
from living_kanto.mechanics.held_items import change_held_item,assign_wild_held_item,holdable
from living_kanto.mechanics.item_rules import ItemError
from test_gameplay import game,act,locate,scenario,state

def mon(slot,level=5):return create_pokemon('RATTATA',level,'a',random.Random(slot),identifier=f'pokemon-exp-{slot}')

def test_source_xp_split_modifiers_order_and_max_level_counts():
    a,b,c=mon(1),mon(2),mon(3);a['held_item']='LUCKY_EGG';a['original_trainer_id']='other';b['held_item']='EXP_SHARE'
    foe={'species':'RATTATA','level':7}
    assert experience_distribution(foe,[a,b,c],[a['pokemon_id']],'a',trainer_battle=True)=={a['pokemon_id']:94,b['pokemon_id']:42}
    assert experience_distribution(foe,[b],[b['pokemon_id']],'a')=={b['pokemon_id']:56}
    c['level']=100;b['hp']=0
    assert experience_distribution(foe,[a,b,c],[a['pokemon_id'],c['pokemon_id']],'a')=={a['pokemon_id']:63}
    a['original_trainer_id']='a';a['ownership_history']=['a','other','a'];a['held_item']=''
    assert experience_distribution(foe,[a],[a['pokemon_id']],'a')=={a['pokemon_id']:57}

def test_source_held_give_swap_take_atomic_and_classification():
    p=mon(1);h={'human_id':'a','party':[p['pokemon_id']],'box':[],'inventory':{'exp_share':{'quantity':1},'lucky_egg':{'quantity':1}}}
    h,p=change_held_item(h,p,'exp_share');assert p['held_item']=='EXP_SHARE' and h['inventory']['exp_share']['quantity']==0
    h,p=change_held_item(h,p,'lucky_egg');assert h['inventory']['exp_share']['quantity']==1
    h,p=change_held_item(h,p);assert not p['held_item'] and h['inventory']['lucky_egg']['quantity']==1
    before=copy.deepcopy(h)
    with pytest.raises(ItemError):change_held_item(h,p,'hm03')
    assert h==before and holdable('POTION') and holdable('TM01') and not holdable('HM03') and not holdable('BICYCLE')

def test_source_wild_held_common_rare_boundaries():
    class Draw:
        def __init__(self,value):self.value=value
        def randrange(self,n):assert n==100;return self.value
    p=create_pokemon('CHANSEY',20,None,random.Random(1))
    assert assign_wild_held_item(p,Draw(94))==''
    assert assign_wild_held_item(p,Draw(95))=='LUCKY_EGG'
    p=create_pokemon('PIKACHU',20,None,random.Random(1))
    assert assign_wild_held_item(p,Draw(44))==''
    assert assign_wild_held_item(p,Draw(45))==''
    assert assign_wild_held_item(p,Draw(95))==''
    p['species']='RATICATE'
    assert assign_wild_held_item(p,Draw(45))=='ORAN_BERRY'
    assert assign_wild_held_item(p,Draw(95))=='SITRUS_BERRY'

def test_production_held_give_take_identity_inventory_and_replay(game):
    engine,store=game;hid='human-001';p=create_pokemon('RATTATA',5,hid,random.Random(1),identifier='pokemon-held-production')
    scenario(game,[{'op':'set','path':f'pokemon.{p["pokemon_id"]}','value':p},{'op':'set','path':f'humans.{hid}.party','value':[p['pokemon_id']]},{'op':'set','path':f'humans.{hid}.inventory.exp_share','value':{'quantity':1}},{'op':'set','path':f'humans.{hid}.inventory.lucky_egg','value':{'quantity':1}}])
    s=act(game,hid,'give_held_item',{'pokemon_id':p['pokemon_id'],'item':'lucky_egg'})
    assert s.pokemon[p['pokemon_id']]['held_item']=='LUCKY_EGG' and s.humans[hid]['inventory']['lucky_egg']['quantity']==0
    assert engine.observation_for(s,hid).party[0]['held_item']=='LUCKY_EGG'
    s=act(game,hid,'give_held_item',{'pokemon_id':p['pokemon_id'],'item':'exp_share'})
    assert s.humans[hid]['inventory']['lucky_egg']['quantity']==1
    s=act(game,hid,'take_held_item',{'pokemon_id':p['pokemon_id']})
    assert s.humans[hid]['inventory']['exp_share']['quantity']==1 and s.pokemon[p['pokemon_id']]['personality']==p['personality']
    assert store.replay('gameplay-test').state_hash==s.state_hash


def test_source_same_wild_item_is_certain():
    class Draw:
        def randrange(self,n):return 0
    p=create_pokemon('GEODUDE',20,None,random.Random(1))
    from living_kanto.mechanics.reference import data
    candidates=[species for species,row in data()['species'].items() if row['itemCommon']==row['itemRare']!='NONE']
    assert 'SNORLAX' in candidates
    for species in candidates:
        p['species']=species;assert assign_wild_held_item(p,Draw())==data()['species'][species]['itemCommon']

def test_actual_wild_ko_awards_bench_share_and_traded_lucky_egg(game):
    engine,store=game;hid='human-001';a=create_pokemon('CHARIZARD',50,hid,random.Random(1),identifier='pokemon-xp-active');b=create_pokemon('RATTATA',5,hid,random.Random(2),identifier='pokemon-xp-share');c=create_pokemon('RATTATA',5,hid,random.Random(3),identifier='pokemon-xp-benched')
    a['held_item']='LUCKY_EGG';a['original_trainer_id']='someone-else';a['moves']=[{'move':'FLAMETHROWER','pp':15,'max_pp':15}];b['held_item']='EXP_SHARE'
    # Earth badge makes the deliberately traded fixture obey for this XP case.
    changes=[{'op':'set','path':f'pokemon.{p["pokemon_id"]}','value':p} for p in (a,b,c)]+[{'op':'set','path':f'humans.{hid}.party','value':[p['pokemon_id'] for p in (a,b,c)]},{'op':'set','path':f'humans.{hid}.badges','value':['earth']}]
    scenario(game,changes);grass=next(point for point,cell in engine.maps['Route1'].cells.items() if cell.get('encounter_type')==1);locate(game,hid,'Route1',grass)
    before=act(game,hid,'train');bid=before.humans[hid]['battle_id'];record=before.world_facts['battles'][bid];foe=record['session']['teams'][1]['party'][0]
    expected=experience_distribution(foe,[a,b,c],[a['pokemon_id']],hid)
    after=act(game,hid,'battle_move',{'slot':1})
    assert after.humans[hid]['battle_id'] is None
    assert after.world_facts['battles'][bid]['experience_awards'][foe['pokemon_id']]==expected
    assert after.pokemon[b['pokemon_id']]['experience']==b['experience']+expected[b['pokemon_id']]
    assert after.pokemon[c['pokemon_id']]['experience']==c['experience']
    assert after.pokemon[b['pokemon_id']]['evs']!=b['evs']
    assert store.replay('gameplay-test').state_hash==after.state_hash
