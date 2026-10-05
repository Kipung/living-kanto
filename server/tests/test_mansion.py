import copy
import pytest
from test_gameplay import game,act,locate,scenario,state
from living_kanto.simulation.field import actor_map
from living_kanto.simulation.access import transfer_gate,AccessDenied

def test_source_mansion_all_floors_exact_per_trainer_overlays_and_toggle(game):
    engine,store=game;hid='human-001'
    for mid in ['PokemonMansion_1F','PokemonMansion_2F','PokemonMansion_3F','PokemonMansion_B1F']:
        source=engine.maps[mid];switch=source.events['mansion_switch'];assert switch['off'] and switch['on'] and switch['source_sha256']
        other=copy.deepcopy(state(game).humans[hid]);other['field']={'mansion_switch':True}
        opened=actor_map(source,other);closed=actor_map(source,{'field':{}})
        for enabled,view in [(False,closed),(True,opened)]:
            for tile in switch['on' if enabled else 'off']:
                assert view.cells[(tile['x'],tile['y'])]['metatile_id']==tile['metatile_id']
                assert view.is_walkable(tile['x'],tile['y'])==(not bool(tile['collision']))
                assert tile['image_sha256']
    statue=engine.maps['PokemonMansion_1F'].events['mansion_switch']['statues'][0]
    locate(game,hid,'PokemonMansion_1F',(statue['x'],statue['y']+1))
    scenario(game,[{'op':'set','path':f'humans.{hid}.facing','value':'north'}])
    s=act(game,hid,'toggle_mansion_switch',{})
    assert s.humans[hid]['field']['mansion_switch'] and not s.humans['human-002'].get('field',{}).get('mansion_switch')
    assert s.humans[hid]['badges']==[]
    s=act(game,hid,'toggle_mansion_switch',{});assert not s.humans[hid]['field']['mansion_switch']
    assert store.replay('gameplay-test').state_hash==s.state_hash

def test_cerulean_cave_needs_actual_own_hall_of_fame(game):
    engine,store=game;s=state(game);h=dict(s.humans['human-001'],map_id='CeruleanCity')
    with pytest.raises(AccessDenied):transfer_gate(h,'CeruleanCave_1F',s)
    scenario(game,[{'op':'set','path':'world_facts.championship.hall_of_fame','value':[{'champion_id':'human-002'}]}])
    with pytest.raises(AccessDenied):transfer_gate(h,'CeruleanCave_1F',state(game))
    scenario(game,[{'op':'set','path':'world_facts.championship.hall_of_fame','value':[{'champion_id':'human-001'}]}])
    assert transfer_gate(h,'CeruleanCave_1F',state(game))==[]

def test_secret_key_source_route_requires_real_statue_toggles(game):
    from collections import deque
    from living_kanto.simulation.maps import resolve_transfer,MapLoadError
    engine,store=game
    start=('PokemonMansion_1F',8,32,False);todo=deque([start]);previous={start:None};goal=None
    views={(mid,on):actor_map(engine.maps[mid],{'field':{'mansion_switch':on}}) for mid in ['PokemonMansion_1F','PokemonMansion_2F','PokemonMansion_3F','PokemonMansion_B1F'] for on in [False,True]}
    while todo:
        node=todo.popleft();mid,x,y,on=node;view=views[(mid,on)]
        if mid=='PokemonMansion_B1F' and abs(x-5)+abs(y-7)<=1:goal=node;break
        successors=[]
        for direction in ['north','south','east','west']:
            point=view.step_destination((x,y),direction)
            if point:successors.append((mid,*point,on))
        target=view.exit_target(x,y)
        if target and target.startswith('PokemonMansion_'):
            try:
                dst,nx,ny=resolve_transfer(engine.maps,view,x,y,target)
                if views[(dst,on)].is_walkable(nx,ny):successors.append((dst,nx,ny,on))
            except MapLoadError:pass
        if any((x,y-1)==(bg['x'],bg['y']) for bg in view.events['mansion_switch']['statues']):successors.append((mid,x,y,not on))
        for following in successors:
            if following not in previous:previous[following]=node;todo.append(following)
    assert goal is not None,'Original dungeon route must reach Secret Key without teleport/story waiver'
    route=[]
    while goal:route.append(goal);goal=previous[goal]
    route.reverse()
    assert any(a[3]!=b[3] for a,b in zip(route,route[1:]))
    assert len(route)>100
