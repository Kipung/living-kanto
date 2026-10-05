import random
from test_gameplay import game,act,locate,scenario,state
from living_kanto.mechanics import create_pokemon

def test_paid_safari_actual_encounter_without_owned_pokemon_and_replay(game):
    engine,store=game;hid='human-001'
    locate(game,hid,'FuchsiaCity_SafariZone_Entrance',(4,3))
    scenario(game,[{'op':'set','path':f'humans.{hid}.money','value':500}])
    s=act(game,hid,'safari_enter')
    assert s.humans[hid]['money']==0 and s.humans[hid]['safari']['balls']==30
    grass=next(c for c in __import__('json').loads((engine.content_root/'maps/SafariZone_Center.json').read_text())['cells'] if c.get('encounter_type')==1)
    locate(game,hid,'SafariZone_Center',(grass['x'],grass['y']))
    s=act(game,hid,'train');assert s.humans[hid]['safari']['encounter'] and not s.humans[hid].get('battle_id')
    legal=engine.battle_actions(s,hid);assert {a.action for a in legal}=={'safari_action'}
    s=act(game,hid,'safari_action',{'choice':'run'})
    assert s.humans[hid]['safari']['encounter'] is None and s.humans[hid]['safari']['active']
    assert store.replay('gameplay-test').state_hash==s.state_hash

def test_source_ghost_individual_traits_and_uncatchability(game):
    engine,store=game;hid='human-001'
    p=create_pokemon('BLASTOISE',60,hid,random.Random(1),identifier='pokemon-ghost-test');p['moves']=[{'move':'SURF','pp':15,'max_pp':15}]
    scenario(game,[{'op':'set','path':f'pokemon.{p["pokemon_id"]}','value':p},{'op':'set','path':f'humans.{hid}.party','value':[p['pokemon_id']]},{'op':'set','path':f'humans.{hid}.inventory.silph_scope','value':{'item_id':'silph_scope','quantity':1}}])
    locate(game,hid,'PokemonTower_6F',(11,15))
    s=act(game,hid,'start_ghost_battle');record=engine.active_battle(s,hid)
    ghost=s.pokemon[record['session']['teams'][1]['party'][0]['pokemon_id']]
    assert ghost['species']=='MAROWAK' and ghost['level']==30 and ghost['gender']=='F' and ghost['nature']=='Serious'
    assert ghost['personality']%25==12 and ghost['personality']&255<127
    assert set(ghost['ivs'].values())=={31}
    assert not any(a.action=='catch' for a in engine.battle_actions(s,hid))
    assert not s.humans[hid].get('access',{}).get('tower_marowak_defeated')
    for _ in range(20):
        options=engine.battle_actions(s,hid)
        if not s.humans[hid].get('battle_id'):break
        attack=next(a for a in options if a.action=='battle_move' and a.arguments['slot']==1)
        s=act(game,hid,attack.action,attack.arguments)
    assert s.humans[hid]['access']['tower_marowak_defeated']
    assert store.replay('gameplay-test').state_hash==s.state_hash

def test_source_tutor_one_use_and_second_trainer_independence(game):
    from living_kanto.mechanics.tutors import tutor_stations
    assert len(tutor_stations())==15
    station=next(t for t in tutor_stations() if t['move']=='MEGA_PUNCH')
    for hid in ('human-001','human-002'):
        p=create_pokemon('CHARMANDER',5,hid,random.Random(1),identifier=f'pokemon-tutor-{hid}')
        scenario(game,[{'op':'set','path':f'pokemon.{p["pokemon_id"]}','value':p},{'op':'set','path':f'humans.{hid}.party','value':[p['pokemon_id']]}])
        locate(game,hid,station['map_id'],(station['x']-1,station['y']))
        s=act(game,hid,'learn_from_tutor',{'pokemon_id':p['pokemon_id'],'tutor_id':station['tutor_id']})
        assert s.pokemon[p['pokemon_id']]['moves'][-1]['move']=='MEGA_PUNCH'
        assert not any(a.action=='learn_from_tutor' and a.arguments['tutor_id']==station['tutor_id'] for a in game[0].gameplay_actions(s,hid))
    assert game[1].replay('gameplay-test').state_hash==s.state_hash

def test_source_surf_encounter_requires_owned_move_and_soul_badge(game):
    engine,store=game;hid='human-001'
    p=create_pokemon('SQUIRTLE',20,hid,random.Random(1),identifier='pokemon-surf-test');p['moves']=[{'move':'SURF','pp':15,'max_pp':15}]
    scenario(game,[{'op':'set','path':f'pokemon.{p["pokemon_id"]}','value':p},{'op':'set','path':f'humans.{hid}.party','value':[p['pokemon_id']]}])
    cell=next(c for c in __import__('json').loads((engine.content_root/'maps/Route21_North.json').read_text())['cells'] if c.get('encounter_type')==2)
    locate(game,hid,'Route21_North',(cell['x'],cell['y']))
    assert engine.encounter_method(state(game),hid) is None
    scenario(game,[{'op':'set','path':f'humans.{hid}.badges','value':['soul']}])
    assert engine.encounter_method(state(game),hid)=='surf'
    after=act(game,hid,'train');record=engine.active_battle(after,hid)
    assert record['encounter_method']=='surf'
    assert after.pokemon[record['session']['teams'][1]['party'][0]['pokemon_id']]['species']=='TENTACOOL'
    assert store.replay('gameplay-test').state_hash==after.state_hash

def test_source_zapdos_world_unique_reservation_and_actual_defeat(game):
    from living_kanto.mechanics.statics import static_templates
    t=static_templates()['zapdos'];engine,store=game
    for hid in ('human-001','human-002'):
        p=create_pokemon('GOLEM',100,hid,random.Random(1),identifier=f'pokemon-static-test-{hid}')
        p['moves']=[{'move':'ROCK_SLIDE','pp':10,'max_pp':10}]
        scenario(game,[{'op':'set','path':f'pokemon.{p["pokemon_id"]}','value':p},{'op':'set','path':f'humans.{hid}.party','value':[p['pokemon_id']]}])
        locate(game,hid,t['map_id'],(t['x']+1,t['y']))
    s=act(game,'human-001','start_static_battle',{'static_id':'zapdos'})
    assert s.world_facts['static_encounters']['zapdos']['pokemon_id']=='pokemon-static-zapdos'
    assert s.pokemon['pokemon-static-zapdos']['level']==50
    assert not any(a.action=='start_static_battle' for a in engine.gameplay_actions(s,'human-002'))
    for _ in range(10):
        if not s.humans['human-001'].get('battle_id'):break
        s=act(game,'human-001','battle_move',{'slot':1})
    assert s.world_facts['static_encounters']['zapdos']['status']=='defeated'
    assert not any(a.action=='start_static_battle' for a in engine.gameplay_actions(s,'human-002'))
    assert store.replay('gameplay-test').state_hash==s.state_hash

def test_source_master_ball_consumed_unique_zapdos_catch_same_individual(game):
    from living_kanto.mechanics.statics import static_templates
    t=static_templates()['zapdos'];engine,store=game;hid='human-001'
    p=create_pokemon('SQUIRTLE',5,hid,random.Random(1),identifier='pokemon-master-test')
    scenario(game,[{'op':'set','path':f'pokemon.{p["pokemon_id"]}','value':p},{'op':'set','path':f'humans.{hid}.party','value':[p['pokemon_id']]},{'op':'set','path':f'humans.{hid}.inventory.master_ball','value':{'item_id':'master_ball','quantity':1}}])
    locate(game,hid,t['map_id'],(t['x']+1,t['y']))
    s=act(game,hid,'start_static_battle',{'static_id':'zapdos'});pid='pokemon-static-zapdos';personality=s.pokemon[pid]['personality']
    s=act(game,hid,'catch',{'ball':'master_ball'})
    assert s.world_facts['static_encounters']['zapdos']['status']=='caught'
    assert s.pokemon[pid]['personality']==personality and s.pokemon[pid]['owner_id']==hid
    assert s.pokemon[pid]['pokeball']=='MASTER_BALL' and pid in s.humans[hid]['party']
    assert s.humans[hid]['inventory']['master_ball']['quantity']==0
    assert store.replay('gameplay-test').state_hash==s.state_hash

def test_flute_wakes_actual_source_snorlax_and_clears_only_trainers_blocker(game):
    from living_kanto.simulation.field import objects
    engine,store=game
    source=next(obj for obj in objects(engine.maps['Route12'],state(game).humans['human-001']) if obj['kind']=='snorlax')
    for hid in ('human-001','human-002'):
        p=create_pokemon('SQUIRTLE',5,hid,random.Random(1),identifier=f'pokemon-snorlax-{hid}')
        scenario(game,[{'op':'set','path':f'pokemon.{p["pokemon_id"]}','value':p},{'op':'set','path':f'humans.{hid}.party','value':[p['pokemon_id']]},{'op':'set','path':f'humans.{hid}.inventory.poke_flute','value':{'item_id':'poke_flute','quantity':1}},{'op':'set','path':f'humans.{hid}.inventory.master_ball','value':{'item_id':'master_ball','quantity':1}}])
        locate(game,hid,'Route12',(source['x']-1,source['y']))
    s=act(game,'human-001','start_snorlax_battle',{'object_id':source['key']})
    assert source['key'] in s.humans['human-001']['field']['snorlax_cleared']
    assert any(obj['key']==source['key'] for obj in objects(engine.maps['Route12'],s.humans['human-002']))
    record=engine.active_battle(s,'human-001');pid=record['session']['teams'][1]['party'][0]['pokemon_id']
    assert s.pokemon[pid]['species']=='SNORLAX' and s.pokemon[pid]['level']==30
    s=act(game,'human-001','catch',{'ball':'master_ball'})
    assert s.pokemon[pid]['owner_id']=='human-001' and s.humans['human-001']['inventory']['poke_flute']['quantity']==1
    assert store.replay('gameplay-test').state_hash==s.state_hash

def test_mewtwo_requires_individual_hall_of_fame_mainland_adaptation(game):
    from living_kanto.mechanics.statics import static_templates
    engine,store=game;hid='human-001';t=static_templates()['mewtwo']
    p=create_pokemon('SQUIRTLE',5,hid,random.Random(1),identifier='pokemon-mewtwo-test')
    scenario(game,[{'op':'set','path':f'pokemon.{p["pokemon_id"]}','value':p},{'op':'set','path':f'humans.{hid}.party','value':[p['pokemon_id']]}])
    locate(game,hid,t['map_id'],(t['x']+1,t['y']))
    assert not any(a.action=='start_static_battle' for a in engine.gameplay_actions(state(game),hid))
    # Explicit Creative eligibility fixture, not autonomous championship evidence.
    scenario(game,[{'op':'set','path':'world_facts.championship.hall_of_fame','value':[{'champion_id':hid}]}])
    s=act(game,hid,'start_static_battle',{'static_id':'mewtwo'})
    assert s.pokemon['pokemon-static-mewtwo']['species']=='MEWTWO' and s.pokemon['pokemon-static-mewtwo']['level']==70
    assert store.replay('gameplay-test').state_hash==s.state_hash

def test_articuno_source_two_boulder_current_gate(game):
    from living_kanto.mechanics.statics import static_templates
    engine,store=game;hid='human-001';t=static_templates()['articuno']
    p=create_pokemon('SQUIRTLE',5,hid,random.Random(1),identifier='pokemon-articuno-test')
    scenario(game,[{'op':'set','path':f'pokemon.{p["pokemon_id"]}','value':p},{'op':'set','path':f'humans.{hid}.party','value':[p['pokemon_id']]}])
    locate(game,hid,t['map_id'],(t['x']+1,t['y']))
    assert not any(a.action=='start_static_battle' for a in engine.gameplay_actions(state(game),hid))
    # Explicit Creative current-state fixture. Separate traversal tests exercise
    # actual boulder routes; this proves the battle gate, not a solved AI puzzle.
    scenario(game,[{'op':'set','path':f'humans.{hid}.field.revealed_boulders','value':['FLAG_HIDE_SEAFOAM_B4F_BOULDER_1','FLAG_HIDE_SEAFOAM_B4F_BOULDER_2']}])
    s=act(game,hid,'start_static_battle',{'static_id':'articuno'})
    assert s.pokemon['pokemon-static-articuno']['species']=='ARTICUNO' and s.pokemon['pokemon-static-articuno']['level']==50
    assert store.replay('gameplay-test').state_hash==s.state_hash
