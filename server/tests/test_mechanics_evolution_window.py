import random
from test_gameplay import game,act,locate,scenario,state
from living_kanto.mechanics import create_pokemon,evolution_options,grant_experience
from living_kanto.mechanics.pokemon import experience_at_level

def test_fresh_high_level_requires_real_levelup_before_evolution():
    p=create_pokemon('BULBASAUR',20,'a',random.Random(1))
    assert evolution_options(p)==[]
    grant_experience(p,0);assert evolution_options(p)==[]
    grant_experience(p,experience_at_level('BULBASAUR',21)-p['experience'])
    assert evolution_options(p)==['IVYSAUR']

def test_actual_rare_candy_opportunity_same_identity_consumed_replay(game):
    engine,store=game;hid='human-001';p=create_pokemon('BULBASAUR',16,hid,random.Random(1),identifier='pokemon-evolution-window')
    p['origin_map_id']='PalletTown';locate(game,hid,'PalletTown_ProfessorOaksLab')
    scenario(game,[{'op':'set','path':f'pokemon.{p["pokemon_id"]}','value':p},{'op':'set','path':f'humans.{hid}.party','value':[p['pokemon_id']]},{'op':'set','path':f'humans.{hid}.inventory.rare_candy','value':{'quantity':1}}])
    assert not any(a.action=='evolve' for a in engine.gameplay_actions(state(game),hid))
    s=act(game,hid,'use_item',{'pokemon_id':p['pokemon_id'],'item':'rare_candy'})
    assert s.pokemon[p['pokemon_id']]['friendship']==p['friendship']+6
    assert evolution_options(s.pokemon[p['pokemon_id']])==['IVYSAUR']
    s=act(game,hid,'evolve',{'pokemon_id':p['pokemon_id'],'species':'IVYSAUR'})
    assert s.pokemon[p['pokemon_id']]['personality']==p['personality'] and s.pokemon[p['pokemon_id']]['evolution_opportunity'] is None
    assert not evolution_options(s.pokemon[p['pokemon_id']])
    assert store.replay('gameplay-test').state_hash==s.state_hash
