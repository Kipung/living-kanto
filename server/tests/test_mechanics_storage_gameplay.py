import random
import pytest
from test_gameplay import game,act,locate,scenario,state
from living_kanto.mechanics import create_pokemon
from living_kanto.mechanics.storage import release_pokemon

def pc(game):
    engine,store=game;mid='ViridianCity_PokemonCenter_1F'
    cell=next((x,y) for (x,y),c in engine.maps[mid].cells.items() if c['behavior']==0x83)
    for facing,(dx,dy) in {'north':(0,-1),'south':(0,1),'east':(1,0),'west':(-1,0)}.items():
        point=(cell[0]-dx,cell[1]-dy)
        if engine.maps[mid].is_walkable(*point):return mid,point,facing
    raise AssertionError('Source PC has no physical interaction cell')

def test_physical_pc_storage_and_release_retains_identity_replay(game):
    hid='human-001';engine,store=game;mons=[create_pokemon('RATTATA',5,hid,random.Random(i),identifier=f'pokemon-pc-{i}') for i in range(2)]
    scenario(game,[{'op':'set','path':f'pokemon.{p["pokemon_id"]}','value':p} for p in mons]+[{'op':'set','path':f'humans.{hid}.party','value':[p['pokemon_id'] for p in mons]}])
    locate(game,hid,'ViridianCity_PokemonCenter_1F',(5,5))
    assert not any(a.action=='store_deposit' for a in engine.gameplay_actions(state(game),hid))
    mid,position,facing=pc(game);locate(game,hid,mid,position);scenario(game,[{'op':'set','path':f'humans.{hid}.facing','value':facing}])
    pid=mons[0]['pokemon_id'];scenario(game,[{'op':'set','path':'world_facts.static_encounters.zapdos','value':{'pokemon_id':pid,'status':'caught','owner_id':hid,'battle_id':None}}]);s=act(game,hid,'store_deposit',{'pokemon_id':pid})
    assert pid in s.humans[hid]['box'] and pid not in s.humans[hid]['party']
    s=act(game,hid,'store_withdraw',{'pokemon_id':pid});assert pid in s.humans[hid]['party']
    s=act(game,hid,'release_pokemon',{'pokemon_id':pid})
    assert s.pokemon[pid]['owner_id'] is None and s.pokemon[pid]['personality']==mons[0]['personality']
    assert s.pokemon[pid]['ownership_history']==mons[0]['ownership_history']
    assert s.pokemon[pid]['release_history'][-1]['trainer_id']==hid
    assert s.pokemon[pid]['original_trainer_id']==hid
    claim=s.world_facts['static_encounters']['zapdos'];assert claim['status']=='released' and claim['released_by']==hid and claim['pokemon_id']==pid and claim['owner_id'] is None
    assert pid not in s.humans[hid]['party']+s.humans[hid]['box']
    assert not any(a.action=='release_pokemon' for a in engine.gameplay_actions(s,hid)) # last usable mon.
    assert store.replay('gameplay-test').state_hash==s.state_hash

def test_source_release_only_sole_surf_dive_restriction_not_all_hms():
    a=create_pokemon('SQUIRTLE',20,'a',random.Random(1),identifier='p-a');b=create_pokemon('RATTATA',5,'a',random.Random(2),identifier='p-b')
    h={'human_id':'a','map_id':'Route1','party':['p-a','p-b'],'box':[]}
    a['moves']=[{'move':'SURF','pp':15,'max_pp':15}]
    with pytest.raises(ValueError,match='Surf'):release_pokemon(h,a,[a,b])
    a['moves']=[{'move':'CUT','pp':30,'max_pp':30}]
    result,p=release_pokemon(h,a,[a,b]);assert p['owner_id'] is None
