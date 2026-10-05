import random
import pytest
from test_gameplay import game,act,locate,scenario,state
from living_kanto.mechanics.source_gifts import receive_gift,gift_templates
from living_kanto.mechanics.progression import official_team,official_prize

def test_source_koichi_party_and_one_choice_gift_gate():
    team=official_team('Koichi','human-075',random.Random(1))
    assert [(p['species'],p['level']) for p in team]==[('HITMONLEE',37),('HITMONCHAN',37)]
    assert all(len(p['moves'])==4 for p in team) and official_prize('Koichi',37)==888
    h={'human_id':'h','map_id':'SaffronCity_Dojo','x':6,'y':3,'party':[],'box':[],'pokedex':[]}
    with pytest.raises(ValueError):receive_gift(h,'hitmonlee',random.Random(1))
    h['access']={'dojo_master_defeated':True};h,p=receive_gift(h,'hitmonlee',random.Random(1))
    assert p['level']==25 and p['original_trainer_id']=='h'
    with pytest.raises(ValueError):receive_gift(h,'hitmonchan',random.Random(1))

def test_source_eevee_physical_gift_independent_and_replay(game):
    engine,store=game;hid='human-001';locate(game,hid,'CeladonCity_Condominiums_RoofRoom',(7,4))
    s=act(game,hid,'receive_source_gift',{'gift_id':'eevee'});p=s.pokemon[s.humans[hid]['party'][-1]]
    assert (p['species'],p['level'],p['original_trainer_id'])==('EEVEE',25,hid)
    assert not any(a.action=='receive_source_gift' for a in engine.gameplay_actions(s,hid))
    second='human-002';locate(game,second,'CeladonCity_Condominiums_RoofRoom',(7,4));s=act(game,second,'receive_source_gift',{'gift_id':'eevee'})
    assert s.humans[second]['party'][-1]!=p['pokemon_id']
    assert store.replay('gameplay-test').state_hash==s.state_hash

def test_source_electrode_fake_item_is_real_battle_independent(game):
    from living_kanto.mechanics.statics import electrode_templates
    from living_kanto.mechanics import create_pokemon
    hid='human-001';engine,store=game;p=create_pokemon('CHARMANDER',20,hid,random.Random(1),identifier='pokemon-electrode-starter')
    scenario(game,[{'op':'set','path':f'pokemon.{p["pokemon_id"]}','value':p},{'op':'set','path':f'humans.{hid}.party','value':[p['pokemon_id']]}])
    template=electrode_templates()['electrode1'];assert template['level']==34
    locate(game,hid,'PowerPlant',(template['x']-1,template['y']))
    s=act(game,hid,'start_electrode_battle',{'electrode_id':'electrode1'});battle=s.world_facts['battles'][s.humans[hid]['battle_id']]
    foe=s.pokemon[battle['session']['teams'][1]['party'][0]['pokemon_id']]
    assert (foe['species'],foe['level'])==('ELECTRODE',34)
    assert 'electrode1' in s.humans[hid]['field']['electrode_cleared']
    assert 'electrode1' not in s.humans['human-002'].get('field',{}).get('electrode_cleared',[])
    assert store.replay('gameplay-test').state_hash==s.state_hash

def test_dojo_actual_completed_win_unlocks_one_source_reward(game):
    from living_kanto.mechanics import create_pokemon
    engine,store=game;hid='human-001';p=create_pokemon('CHARIZARD',100,hid,random.Random(1),identifier='pokemon-dojo-fixture')
    p['moves']=[{'move':'FLAMETHROWER','pp':15,'max_pp':15}]
    scenario(game,[{'op':'set','path':f'pokemon.{p["pokemon_id"]}','value':p},{'op':'set','path':f'humans.{hid}.party','value':[p['pokemon_id']]}]);locate(game,hid,'SaffronCity_Dojo',(6,6))
    s=act(game,hid,'start_battle',{'human_id':'human-075'});bid=s.humans[hid]['battle_id']
    assert not s.humans[hid].get('access',{}).get('dojo_master_defeated')
    for _ in range(10):
        current=state(game)
        for actor in (hid,'human-075'):
            choices=engine.battle_actions(current,actor)
            if choices:
                a=next((a for a in choices if a.action=='battle_move'),choices[0]);current=act(game,actor,a.action,a.arguments)
            if not current.humans[hid].get('battle_id'):break
        if not current.humans[hid].get('battle_id'):break
    assert current.humans[hid]['access']['dojo_master_defeated']
    assert current.world_facts['battles'][bid]['prize_money']==888 and current.humans[hid]['badges']==[]
    locate(game,hid,'SaffronCity_Dojo',(5,4));current=act(game,hid,'receive_source_gift',{'gift_id':'hitmonlee'})
    assert current.pokemon[current.humans[hid]['party'][-1]]['species']=='HITMONLEE'
    assert store.replay('gameplay-test').state_hash==current.state_hash
