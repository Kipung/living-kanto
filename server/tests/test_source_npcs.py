import json
from pathlib import Path
from types import SimpleNamespace
from living_kanto.simulation.source_npcs import initial_actors,visible_actors
ROOT=Path(__file__).resolve().parents[2]
def test_unconditional_mainland_source_people_and_real_assets():
    engine=SimpleNamespace(content_root=ROOT/'content')
    actors=initial_actors(engine,{})
    assert len(actors)>650
    assert len({a['map_id'] for a in actors.values()})>150
    for npc in actors.values():
        mid=npc['map_id']; source=npc['source']
        events=json.loads((ROOT/f'content/maps/{mid}.json').read_text())['events']['object_events']
        match=next(o for i,o in enumerate(events) if o.get('local_id',i)==source['source_local_id'])
        assert str(match.get('flag','0'))=='0'
        assert (npc['x'],npc['y'])==(match['x'],match['y'])
        assert (ROOT/'content/actors'/f"{npc['appearance']['sprite']}.json").exists()
        assert npc['moving'] is False
        assert not npc['linked_human']
    assert any(a['source']['source_script']=='PalletTown_EventScript_FatMan' and 'Technology' in a['dialogue']['text'] for a in actors.values())
def test_service_replacements_and_private_copy():
    engine=SimpleNamespace(content_root=ROOT/'content')
    humans={'staff':{'service_assignment':{'map_id':'ViridianCity_PokemonCenter_1F','kind':'healing'}}}
    actors=initial_actors(engine,humans)
    assert not any(a['source']['graphics_id']=='OBJ_EVENT_GFX_NURSE' and a['map_id']=='ViridianCity_PokemonCenter_1F' for a in actors.values())
    assert not any(a['source']['graphics_id']=='OBJ_EVENT_GFX_PROF_OAK' for a in actors.values())
    state=SimpleNamespace(npcs=actors)
    visible=visible_actors(state,'PalletTown');assert len(visible)==2
    visible[0]['x']=999
    assert all(a['x']!=999 for a in actors.values())

from test_gameplay import game,state,locate,act

def test_initialized_source_population_and_dialogue_replay(game):
    engine,store=game; initial=state(game)
    assert initial.npcs and len(initial.humans)==100
    assert store.replay(initial.run_id).state_hash==initial.state_hash
    npc=next(n for n in initial.npcs.values() if n['source']['source_script']=='PalletTown_EventScript_FatMan')
    assert npc['name']=='Fat Man'
    locate(game,'human-001','PalletTown',(npc['x']-1,npc['y']))
    assert any(a.action=='speak_to_source_resident' and a.arguments['npc_id']==npc['npc_id'] for a in engine.legal_actions(state(game),'human-001'))
    after=act(game,'human-001','speak_to_source_resident',{'npc_id':npc['npc_id']})
    assert after.humans['human-001']['last_source_dialogue']['text']==npc['dialogue']['text']
    assert store.replay(initial.run_id).state_hash==after.state_hash
    locate(game,'human-002','Route1')
    assert npc['npc_id'] not in str(engine.observation_for(state(game),'human-002').self_state['nearby_source_residents'])

def test_source_collision_respects_elevation_and_existing_origin(game):
    from living_kanto.simulation.collision import occupied_tiles
    engine,_=game; current=state(game)
    npc=next(n for n in current.npcs.values() if n['source']['source_script']=='PalletTown_EventScript_FatMan')
    h=dict(current.humans['human-001'],map_id=npc['map_id'],x=npc['x']-1,y=npc['y'])
    gm=engine.maps[npc['map_id']]
    assert occupied_tiles(gm,h,current)[(npc['x'],npc['y'])]==npc['npc_id']
    h.update(x=npc['x'],y=npc['y'])
    assert (npc['x'],npc['y']) not in occupied_tiles(gm,h,current)
    changed=__import__('copy').deepcopy(current);changed.npcs[npc['npc_id']]['source_placement']['elevation']=9
    h.update(x=npc['x']-1)
    assert (npc['x'],npc['y']) not in occupied_tiles(gm,h,changed)

def test_source_named_office_replacements():
    humans={'master':{'source_office':'dojo_master'},'researcher':{'source_office':'fossil_researcher'}}
    actors=initial_actors(SimpleNamespace(content_root=ROOT/'content'),humans)
    assert not any(a['source']['source_script'] in {'MtMoon_B2F_EventScript_Miguel','SaffronCity_Dojo_EventScript_MasterKoichi'} for a in actors.values())

def test_perry_courtesy_allows_crossing_without_removing_collision(game):
    from living_kanto.simulation.source_npcs import courtesy_plan,courtesy_changes
    from living_kanto.simulation.collision import occupied_tiles
    from test_gameplay import scenario
    engine,store=game;current=state(game)
    npc=next(n for n in current.npcs.values() if n['source']['source_script']=='Route13_EventScript_Perry')
    locate(game,'human-001','Route13',(15,5));current=state(game)
    h=current.humans['human-001'];gm=engine.maps['Route13']
    assert occupied_tiles(gm,h,current)[(16,5)]==npc['npc_id']
    plan=courtesy_plan(engine,current,'human-001',npc['npc_id'])
    assert plan and plan['kind']=='step_aside'
    changes,receipt=courtesy_changes(engine,current,'human-001',{'npc_id':npc['npc_id']})
    after=scenario(game,changes)
    assert (after.humans['human-001']['x'],after.humans['human-001']['y'])==(15,5)
    assert (after.npcs[npc['npc_id']]['x'],after.npcs[npc['npc_id']]['y'])==(16,6)
    assert gm.step_path((15,5),'east')==[(16,5)]
    assert (16,5) not in occupied_tiles(gm,after.humans['human-001'],after)
    assert gm.step_path((16,5),'east')==[(17,5)]
    assert (16,6) in occupied_tiles(gm,after.humans['human-001'],after)
    assert store.replay(after.run_id).state_hash==after.state_hash

def test_courtesy_does_not_displace_people_or_service_posts(game):
    from living_kanto.simulation.source_npcs import courtesy_plan
    engine,_=game;current=state(game)
    npc=next(n for n in current.npcs.values() if n['source']['source_script']=='Route13_EventScript_Perry')
    locate(game,'human-001','Route13',(15,5));locate(game,'human-002','Route13',(16,5));current=state(game)
    # An existing person on the NPC tile prevents an exchange.
    assert courtesy_plan(engine,current,'human-001',npc['npc_id']) is None
    nurse=next(n for n in current.npcs.values() if n['source']['graphics_id']=='OBJ_EVENT_GFX_CABLE_CLUB_RECEPTIONIST')
    locate(game,'human-001',nurse['map_id'],(nurse['x'],nurse['y']+1))
    assert courtesy_plan(engine,state(game),'human-001',nurse['npc_id']) is None

def test_courtesy_exchange_in_one_tile_corridor():
    from living_kanto.simulation.maps import GameMap
    from living_kanto.simulation.source_npcs import courtesy_plan,courtesy_changes
    gm=GameMap('lane',5,3,['00000','11111','00000'],{})
    gm.cells={(x,y):{'x':x,'y':y,'collision':0 if y==1 else 1,'elevation':3,'behavior':0} for y in range(3) for x in range(5)}
    h={'human_id':'human-001','map_id':'lane','x':1,'y':1}
    npc={'npc_id':'source-npc-test','kind':'source_resident','map_id':'lane','x':2,'y':1,'source_placement':{'elevation':3},'appearance':{'sprite':'man'},'source':{}}
    state=SimpleNamespace(humans={'human-001':h},npcs={'source-npc-test':npc},simulated_time=5,world_facts={})
    engine=SimpleNamespace(maps={'lane':gm})
    plan=courtesy_plan(engine,state,'human-001','source-npc-test')
    assert plan['kind']=='exchange_tiles' and plan['human_to']==[2,1] and plan['npc_to']==[1,1]
    changes,_=courtesy_changes(engine,state,'human-001',{'npc_id':'source-npc-test'})
    assert any(c['path']=='humans.human-001.x' and c['value']==2 for c in changes)
    # Another human on the exchange tile must never be displaced.
    state.humans['human-002']={'human_id':'human-002','map_id':'lane','x':2,'y':1}
    assert courtesy_plan(engine,state,'human-001','source-npc-test') is None


def test_courtesy_cannot_drift_away_from_original_source_location(game):
    from living_kanto.simulation.source_npcs import courtesy_plan
    engine,_=game;current=state(game)
    npc=next(n for n in current.npcs.values() if n['source']['source_script']=='Route13_EventScript_Perry')
    locate(game,'human-001','Route13',(15,5));act(game,'human-001','ask_resident_to_make_way',{'npc_id':npc['npc_id']})
    locate(game,'human-001','Route13',(15,6))
    plan=courtesy_plan(engine,state(game),'human-001',npc['npc_id'])
    if plan:
        assert abs(plan['npc_to'][0]-16)+abs(plan['npc_to'][1]-5)<=1


def test_repeated_corridor_exchange_cannot_move_resident_beyond_home_radius():
    from living_kanto.simulation.maps import GameMap
    from living_kanto.simulation.source_npcs import courtesy_plan
    gm=GameMap('lane',6,3,['000000','111111','000000'],{})
    gm.cells={(x,y):{'x':x,'y':y,'collision':0 if y==1 else 1,'elevation':3,'behavior':0} for y in range(3) for x in range(6)}
    human={'human_id':'human-001','map_id':'lane','x':4,'y':1}
    npc={'npc_id':'source-npc-test','kind':'source_resident','map_id':'lane','x':3,'y':1,'source_placement':{'x':2,'y':1,'elevation':3},'appearance':{'sprite':'man'},'source':{}}
    current=SimpleNamespace(humans={'human-001':human},npcs={'source-npc-test':npc},simulated_time=5,world_facts={})
    assert courtesy_plan(SimpleNamespace(maps={'lane':gm}),current,'human-001','source-npc-test') is None
