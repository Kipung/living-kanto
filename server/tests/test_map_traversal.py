import pytest
from living_kanto.simulation.maps import GameMap,resolve_transfer,MapLoadError
from living_kanto.simulation.pathfinding import shortest_path,PathNotFound

def gm(mid,rows,events=None):return GameMap(mid,len(rows[0]),len(rows),rows,{},events=events)
def test_warp_uses_destination_index_not_nearest_open_cell():
 a=gm('a',['111','111','111'],{'warp_events':[{'x':1,'y':1,'dest_map':'b','dest_warp_id':'1'}]})
 b=gm('b',['1111','1111','1111'],{'warp_events':[{'x':0,'y':0},{'x':3,'y':2}]})
 assert resolve_transfer({'a':a,'b':b},'a',1,1,'b')==('b',3,2)
 with pytest.raises(MapLoadError):resolve_transfer({'a':a,'b':b},'a',0,1,'b')
def test_edge_offset_and_exact_blocked_landing():
 a=gm('a',['111111']*3,{'connections':[{'direction':'up','map':'b','offset':2}]})
 b=gm('b',['111','111','101'])
 assert resolve_transfer({'a':a,'b':b},'a',2,0,'b')==('b',0,2)
 with pytest.raises(MapLoadError):resolve_transfer({'a':a,'b':b},'a',3,0,'b')
 with pytest.raises(MapLoadError):resolve_transfer({'a':a,'b':b},'a',0,0,'b')
def test_bfs_routes_around_wall_no_teleport():
 m=gm('a',['11111','10001','11111']);path=shortest_path(m,(0,1),(4,1))
 assert path[-1]==(4,1) and len(path)==6
 previous=(0,1)
 for point in path:
  assert m.is_walkable(*point) and abs(previous[0]-point[0])+abs(previous[1]-point[1])==1
  previous=point
 with pytest.raises(PathNotFound):shortest_path(gm('b',['101']), (0,0),(2,0))

def test_production_source_travel_and_exact_warp_replay(tmp_path):
 from pathlib import Path
 from living_kanto.simulation.world import WorldEngine
 from living_kanto.store.run_store import RunStore
 root=Path(__file__).resolve().parents[2]
 engine=WorldEngine(root/'content');store=RunStore(tmp_path/'source.db')
 engine.initialize(store,'source',mode='survival');store.set_status('source','running')
 _,state,_=store.load_run('source');hid=next(iter(state.humans));h=state.humans[hid]
 choices=[a for a in engine.legal_actions(state,hid) if a.action=='travel_to']
 assert choices
 action=choices[0]
 event,new=engine.build_action_event(store,'source',hid,action=action.action,arguments=action.arguments,observation_version=state.state_version,expected_state_version=state.state_version,decision_explanation='User selected a source-backed walking route',decision_provenance={'kind':'user'})
 route=event.deterministic_inputs['route'];previous=(h['x'],h['y'])
 for step in route['steps']:
  assert engine.maps[h['map_id']].is_walkable(*step)
  assert abs(previous[0]-step[0])+abs(previous[1]-step[1])==1
  previous=step
 assert new.simulated_time-state.simulated_time==len(route['steps'])
 engine.commit(store,event)
 assert store.replay('source').state_hash==new.state_hash
 gm=engine.maps['PalletTown'];target=gm.exit_target(6,7)
 assert resolve_transfer(engine.maps,'PalletTown',6,7,target)==('PalletTown_PlayersHouse_1F',4,8)
 store.close()

def test_source_terrain_water_elevation_direction_and_ledge():
 m=gm('terrain',['11111']*3)
 m.cells={(x,y):{'behavior':0,'elevation':3} for y in range(3) for x in range(5)}
 m.cells[(2,1)]['behavior']=0x10
 assert m.step_destination((1,1),'east') is None
 assert m.step_destination((1,1),'east',surfing=True)==(2,1)
 m.cells[(2,1)]={'behavior':0x38,'elevation':3}
 assert m.step_destination((1,1),'east')==(3,1)
 assert m.step_destination((3,1),'west') is None
 assert shortest_path(m,(1,1),(3,1))==[(3,1)]
 m.cells[(2,1)]={'behavior':0,'elevation':4}
 assert m.step_destination((1,1),'east') is None
 m.cells[(2,1)]['elevation']=15
 assert m.step_destination((1,1),'east')==(2,1)
 m.cells[(2,1)]['behavior']=0x31
 assert m.step_destination((1,1),'east') is None

def test_field_permission_requires_badge_owned_known_move_even_if_fainted():
 from types import SimpleNamespace
 from living_kanto.simulation.field import permission,actions,actor_map
 h={'human_id':'a','party':['p'],'badges':['soul'],'x':0,'y':0,'facing':'east','status':{}}
 mon={'owner_id':'a','hp':10,'moves':[{'move':'SURF'}]};s=SimpleNamespace(pokemon={'p':mon})
 m=gm('water',['11']);m.cells={(0,0):{'behavior':0,'elevation':3},(1,0):{'behavior':0x15,'elevation':1}}
 assert permission(s,h,'SURF') and actions(s,h,m)[0].action=='surf'
 for change in ({'owner_id':'b'},{'is_egg':True},{'moves':[]}):
  old=dict(mon);mon.update(change);assert not permission(s,h,'SURF');mon.clear();mon.update(old)
 mon['hp']=0;assert permission(s,h,'SURF') # Cartridge HM setup has no HP gate.
 h['badges']=[];assert not permission(s,h,'SURF') and not actions(s,h,m)

def test_cut_state_is_individual_and_source_object_blocking():
 from types import SimpleNamespace
 from living_kanto.simulation.field import actor_map,actions
 m=gm('route',['111'],{'object_events':[{'local_id':'TREE','graphics_id':'OBJ_EVENT_GFX_CUT_TREE','x':1,'y':0}]})
 h={'human_id':'a','party':['p'],'badges':['cascade'],'x':0,'y':0,'facing':'east'}
 s=SimpleNamespace(pokemon={'p':{'owner_id':'a','hp':5,'moves':[{'move':'CUT'}]}})
 assert not actor_map(m,h).is_walkable(1,0)
 assert actions(s,h,m)[0].arguments=={'object_id':'route:TREE'}
 h['field']={'cut':['route:TREE']}
 assert actor_map(m,h).is_walkable(1,0)
 assert not actor_map(m,{'human_id':'b'}).is_walkable(1,0)
 assert m.is_walkable(1,0)

def test_field_cut_engine_event_is_atomic_and_replayable(tmp_path):
 from living_kanto.simulation import SimulationEngine
 from living_kanto.store.run_store import RunStore
 m=gm('pallet-town',['11111']*5,{'object_events':[{'local_id':'TREE','graphics_id':'OBJ_EVENT_GFX_CUT_TREE','x':3,'y':2}]})
 engine=SimulationEngine({'pallet-town':m});store=RunStore(tmp_path/'cut.db')
 engine.create_run(store,run_id='cut',humans=[('a','A')]);_,state,_=store.load_run('cut')
 # Modify declared genesis fixture only; no production Creative grant.
 h=state.humans['a'];h.update(x=2,y=2,facing='east',badges=['cascade'],party=['p'])
 state.pokemon['p']={'owner_id':'a','hp':5,'moves':[{'move':'CUT'}]}
 state.state_hash=state.compute_state_hash()
 # Test a state-backed minimal fixture store at the same validation boundary.
 class FixtureStore:
  def load_run(self,run):return None,state,'0'*64
 event,new=engine.build_action_event(FixtureStore(),'cut','a',action='cut',arguments={'object_id':'pallet-town:TREE'},observation_version=0,expected_state_version=0,decision_explanation='Cut this source tree',decision_provenance={'kind':'user'})
 assert event.event_kind=='human.field_move' and new.humans['a']['field']['cut']==['pallet-town:TREE']
 assert m.is_walkable(3,2)
 from living_kanto.contracts.state import StateUpdate
 assert StateUpdate.from_dict(event.transaction).apply_to(state).state_hash==new.state_hash
 store.close()

def test_source_elevator_floors_and_lift_key_gate():
 from pathlib import Path
 from living_kanto.simulation.world import WorldEngine
 from living_kanto.simulation.field import elevator_options
 engine=WorldEngine(Path(__file__).resolve().parents[2]/'content')
 h={'map_id':'CeladonCity_DepartmentStore_Elevator','inventory':{}}
 floors=elevator_options(engine.maps,h)
 assert len(floors)==5 and {f['map_id'] for f in floors}=={f'CeladonCity_DepartmentStore_{i}F' for i in range(1,6)}
 assert all((f['x'],f['y'])==(6,1) for f in floors)
 h['map_id']='RocketHideout_Elevator'
 assert not elevator_options(engine.maps,h)
 h['inventory']={'lift_key':{'quantity':1}}
 assert len(elevator_options(engine.maps,h))==3

def test_source_victory_switch_individual_barrier_after_actual_boulder_push():
 from pathlib import Path
 from living_kanto.simulation.maps import GameMap
 from living_kanto.simulation.field import actor_map,pressed_switches
 root=Path(__file__).resolve().parents[2]
 m=GameMap.from_content('VictoryRoad_1F',root/'content/maps/VictoryRoad_1F.json')
 switch=m.events['strength_switches'][0]
 assert (switch['x'],switch['y'])==(20,16)
 assert {(b['x'],b['y']) for b in switch['barriers']}=={(12,14),(12,15)}
 assert not actor_map(m,{}).is_walkable(12,14)
 wrong=pressed_switches(m,'VictoryRoad_1F:wrong',(20,16),[]);assert not wrong
 done=pressed_switches(m,'VictoryRoad_1F:'+switch['object_id'],(20,16),[])
 assert actor_map(m,{'field':{'switches':done}}).is_walkable(12,14)
 assert not actor_map(m,{'field':{'switches':[]}}).is_walkable(12,14)

def test_forced_spin_records_all_tiles_and_rejects_loop():
 m=gm('spin',['11111']);m.cells={(x,0):{'behavior':0,'elevation':3} for x in range(5)}
 m.cells[(1,0)]['behavior']=0x54;m.cells[(4,0)]['behavior']=0x58
 assert m.step_path((0,0),'east')==[(1,0),(2,0),(3,0),(4,0)]
 assert shortest_path(m,(0,0),(4,0))==[(1,0),(2,0),(3,0),(4,0)]
 m.cells[(3,0)]['behavior']=0x55
 assert m.step_path((0,0),'east') is None

def test_source_card_key_door_closed_until_individual_unlock():
 from pathlib import Path
 from types import SimpleNamespace
 from living_kanto.simulation.field import actor_map,actions
 m=GameMap.from_content('SilphCo_2F',Path(__file__).resolve().parents[2]/'content/maps/SilphCo_2F.json')
 door=m.events['card_key_doors'][0];h={'human_id':'a','map_id':m.map_id,'x':door['x'],'y':door['y'],'inventory':{},'party':[],'badges':[],'facing':'south'}
 assert not actor_map(m,h).is_walkable(5,8)
 assert not any(a.action=='open_card_door' for a in actions(SimpleNamespace(pokemon={}),h,m))
 h['inventory']={'card_key':{'quantity':1}}
 assert any(a.action=='open_card_door' for a in actions(SimpleNamespace(pokemon={}),h,m))
 h['field']={'doors':[door['id']]}
 assert actor_map(m,h).is_walkable(5,8)
 assert not actor_map(m,{}).is_walkable(5,8)

def test_seafoam_source_fall_reveals_lower_boulder_and_stopped_layout():
 from pathlib import Path
 from living_kanto.simulation.field import actor_map,fallen_boulder,objects
 root=Path(__file__).resolve().parents[2];m=GameMap.from_content('SeafoamIslands_1F',root/'content/maps/SeafoamIslands_1F.json')
 h={'field':{}};obj=objects(m,h)[0];hole=next(p for p,c in m.cells.items() if c['behavior']==0x66)
 changes=fallen_boulder(m,h,obj['key'],hole)
 assert obj['reveal_flag'] in changes['revealed_boulders']
 assert obj['key'] not in {o['key'] for o in objects(m,{'field':changes})}
 lower=GameMap.from_content('SeafoamIslands_B3F',root/'content/maps/SeafoamIslands_B3F.json')
 assert len(objects(lower,{}))==4
 reveals=['FLAG_HIDE_SEAFOAM_B3F_BOULDER_1','FLAG_HIDE_SEAFOAM_B3F_BOULDER_2']
 stopped=actor_map(lower,{'field':{'revealed_boulders':reveals}})
 assert 'layouts' in stopped.source_path
 assert sum(c['behavior'] in (0x50,0x51,0x52,0x53) for c in stopped.cells.values())<sum(c['behavior'] in (0x50,0x51,0x52,0x53) for c in lower.cells.values())

def test_surf_current_forces_source_direction_until_normal_water():
 m=gm('water',['1111']);m.cells={(x,0):{'behavior':0x15,'elevation':1} for x in range(4)};m.cells[(1,0)]['behavior']=0x50;m.cells[(2,0)]['behavior']=0x50
 assert m.step_path((0,0),'east',surfing=True)==[(1,0),(2,0),(3,0)]
 assert m.step_path((0,0),'east',surfing=False) is None
