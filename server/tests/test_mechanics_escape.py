import random,pytest
from living_kanto.mechanics.escape import remember_escape_entry,escape_destination,use_escape
from living_kanto.mechanics.item_rules import ItemError
from living_kanto.mechanics import create_pokemon
from test_gameplay import game,act,locate,scenario,state

def test_source_escape_checkpoint_orientation_and_map_flags():
    warp=remember_escape_entry('Route4','MtMoon_1F',14,8,'north');assert (warp['x'],warp['y'])==(14,9)
    assert remember_escape_entry('MtMoon_1F','MtMoon_B1F',5,5,'north') is None
    assert remember_escape_entry('ViridianForest','Route2_ViridianForest_SouthGate',5,5,'north') is None
    h={'map_id':'MtMoon_1F','field':{'escape_warp':warp},'inventory':{'escape_rope':{'quantity':1}}}
    updated,r=use_escape(h,'ESCAPE_ROPE');assert updated['map_id']=='Route4' and updated['inventory']['escape_rope']['quantity']==0
    assert h['inventory']['escape_rope']['quantity']==1
    h['map_id']='PalletTown_ProfessorOaksLab';assert escape_destination(h,'ESCAPE_ROPE') is None
    h['map_id']='MtMoon_1F';h['field']={}
    with pytest.raises(ItemError):use_escape(h,'ESCAPE_ROPE')

def test_source_teleport_requires_real_checkpoint_and_outdoors():
    h={'map_id':'Route1'};assert escape_destination(h,'TELEPORT') is None
    h['last_heal_station']={'map_id':'ViridianCity_PokemonCenter_1F'}
    assert escape_destination(h,'TELEPORT')=={'map_id':'ViridianCity','x':26,'y':27,'source':'src/data/heal_locations.json'}
    h['map_id']='MtMoon_1F';assert escape_destination(h,'TELEPORT') is None

def test_actual_dungeon_entry_checkpoint_rope_and_owned_dig_replay(game):
    engine,store=game;hid='human-001'
    # Exact source entrance transfer produces the checkpoint; no hand-written exit.
    source='Route4';target='MtMoon_1F';warp=next(w for w in engine.maps[source].events['warp_events'] if w.get('dest_map')==target or w.get('dest_map')==engine.maps[target].reference_id)
    locate(game,hid,source,(warp['x'],warp['y']+1));scenario(game,[{'op':'set','path':f'humans.{hid}.inventory.escape_rope','value':{'quantity':1}},{'op':'set','path':f'humans.{hid}.facing','value':'north'}])
    act(game,hid,'walk_to',{'direction':'north'})
    s=act(game,hid,'enter_map',{'map_id':target})
    assert s.humans[hid]['map_id']==target and s.humans[hid]['field']['escape_warp']['map_id']==source
    s=act(game,hid,'use_field_item',{'item':'escape_rope'});assert s.humans[hid]['map_id']==source and s.humans[hid]['inventory']['escape_rope']['quantity']==0
    p=create_pokemon('DIGLETT',20,hid,random.Random(1),identifier='pokemon-source-dig');assert any(m['move']=='DIG' for m in p['moves'])
    scenario(game,[{'op':'set','path':f'pokemon.{p["pokemon_id"]}','value':p},{'op':'set','path':f'humans.{hid}.party','value':[p['pokemon_id']]}]);locate(game,hid,target)
    before=state(game);s=act(game,hid,'use_field_move',{'pokemon_id':p['pokemon_id'],'move':'DIG'})
    assert s.humans[hid]['map_id']==source and s.pokemon[p['pokemon_id']]['moves']==p['moves']
    assert store.replay('gameplay-test').state_hash==s.state_hash

def test_owned_teleport_uses_actual_healing_checkpoint_without_pp_loss(game):
    engine,store=game;hid='human-001';p=create_pokemon('ABRA',5,hid,random.Random(2),identifier='pokemon-teleport-source')
    scenario(game,[{'op':'set','path':f'pokemon.{p["pokemon_id"]}','value':p},{'op':'set','path':f'humans.{hid}.party','value':[p['pokemon_id']]}])
    mid='ViridianCity_PokemonCenter_1F';locate(game,hid,mid);act(game,hid,'heal_party')
    staff=next(h['human_id'] for h in state(game).humans.values() if h.get('service_assignment',{}).get('kind')=='healing' and h['map_id']==mid)
    choice=engine.service_actions(state(game),staff)[0];act(game,staff,choice.action,choice.arguments)
    locate(game,hid,'Route1');s=act(game,hid,'use_field_move',{'pokemon_id':p['pokemon_id'],'move':'TELEPORT'})
    assert (s.humans[hid]['map_id'],s.humans[hid]['x'],s.humans[hid]['y'])==('ViridianCity',26,27)
    assert s.pokemon[p['pokemon_id']]['moves']==p['moves']
    assert store.replay('gameplay-test').state_hash==s.state_hash
