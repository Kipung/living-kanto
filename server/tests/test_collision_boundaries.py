"""Movement boundaries verified against pinned object/player collision code."""
import json
from types import SimpleNamespace
import pytest
from living_kanto.simulation.maps import GameMap,resolve_transfer,MapLoadError
from living_kanto.simulation.field import actor_map
from living_kanto.simulation.pathfinding import shortest_path,PathNotFound
from living_kanto.simulation.collision import compatible_elevations

def terrain(rows,levels=None):
 m=GameMap('m',len(rows[0]),len(rows),rows,{})
 m.cells={(x,y):{'behavior':0,'collision':0 if v=='1' else 1,'elevation':(levels or {}).get((x,y),3)} for y,row in enumerate(rows) for x,v in enumerate(row)}
 return m

def test_source_blocked_warp_marker_does_not_open_wall(tmp_path):
 data={'width':3,'height':1,'cells':[{'x':x,'y':0,'collision':int(x==1),'behavior':0,'elevation':3} for x in range(3)],'events':{'warp_events':[{'x':1,'y':0,'dest_map':'elsewhere','dest_warp_id':'0'}]}}
 p=tmp_path/'map.json';p.write_text(json.dumps(data));m=GameMap.from_content('m',p)
 assert not m.is_walkable(1,0) and m.can_stand(1,0)
 assert m.step_destination((0,0),'east') is None
 with pytest.raises(PathNotFound):shortest_path(m,(0,0),(2,0))
 # A landing marker may be occupied immediately after its exact warp, then left.
 assert m.step_destination((1,0),'east')==(2,0)

def test_source_animated_door_only_enters_from_south():
 m=terrain(['111']*3);m.cells[(1,1)].update(behavior=0x69,collision=1);m.exits[(1,1)]='destination'
 assert m.step_destination((1,2),'north')==(1,1)
 for p,d in [((0,1),'east'),((2,1),'west'),((1,0),'south')]:assert m.step_destination(p,d) is None
 assert m.step_destination((1,1),'south')==(1,2)
 assert m.step_destination((1,1),'west') is None

def test_surf_never_disables_elevation_walls_and_dismount_requires_bank_three():
 m=terrain(['111'],{(0,0):1,(1,0):4,(2,0):3});m.cells[(0,0)]['behavior']=0x15
 assert m.step_destination((0,0),'east',surfing=True) is None
 m.cells[(1,0)]['elevation']=3
 assert m.step_destination((0,0),'east',surfing=True)==(1,0)
 assert shortest_path(m,(0,0),(2,0),surfing=True)==[(1,0),(2,0)]

def test_carried_elevation_cannot_change_lanes_on_bridge_fifteen():
 m=terrain(['111'],{(0,0):3,(1,0):15,(2,0):4});h={'human_id':'a','map_id':'m','x':1,'y':0,'status':{'collision_elevation':3}}
 assert actor_map(m,h)._step_basic((1,0),'east') is None
 with pytest.raises(PathNotFound):shortest_path(actor_map(m,h),(1,0),(2,0))
 m.cells[(2,0)]['elevation']=3;assert shortest_path(actor_map(m,h),(1,0),(2,0))==[(2,0)]

def test_humans_are_solid_but_different_bridge_elevations_are_compatible():
 m=terrain(['111']);a={'human_id':'a','map_id':'m','x':0,'y':0};b={'human_id':'b','map_id':'m','x':1,'y':0};s=SimpleNamespace(humans={'a':a,'b':b})
 assert actor_map(m,a,s).step_destination((0,0),'east') is None
 assert m.step_destination((0,0),'east')==(1,0)
 assert compatible_elevations(0,4) and not compatible_elevations(3,4)
 m.cells[(1,0)]['elevation']=15;b['status']={'collision_elevation':4}
 assert actor_map(m,a,s).step_destination((0,0),'east')==(1,0)

def test_source_object_and_new_target_reservations_are_solid():
 m=terrain(['11111']);a={'human_id':'a','map_id':'m','x':0,'y':0}
 m.events={'object_events':[{'local_id':'tree','graphics_id':'OBJ_EVENT_GFX_CUT_TREE','x':2,'y':0}]}
 assert actor_map(m,a).step_destination((1,0),'east') is None
 assert actor_map(m,a,reservations=[('b','m',1,0,3)]).step_destination((0,0),'east') is None
 a['field']={'cut':['m:tree']};assert actor_map(m,a).step_destination((1,0),'east')==(2,0)

def test_exact_transfer_cannot_land_inside_another_person():
 a=terrain(['111']);a.events={'warp_events':[{'x':1,'y':0,'dest_map':'b','dest_warp_id':'0'}]}
 b=GameMap('b',3,1,['111'],{},events={'warp_events':[{'x':1,'y':0}]});b.cells={(x,0):{'elevation':3} for x in range(3)}
 traveler={'human_id':'a','map_id':'m','x':1,'y':0};other={'human_id':'b','map_id':'b','x':1,'y':0};s=SimpleNamespace(humans={'a':traveler,'b':other})
 with pytest.raises(MapLoadError):resolve_transfer({'m':a,'b':b},a,1,0,'b',actor=traveler,state=s)
 assert resolve_transfer({'m':a,'b':b},a,1,0,'b')==('b',1,0)

def test_existing_overlap_can_step_out_but_never_onto_an_occupied_neighbor():
 m=terrain(['111']);a={'human_id':'a','map_id':'m','x':1,'y':0};b={**a,'human_id':'b'};c={**a,'human_id':'c','x':2};s=SimpleNamespace(humans={'a':a,'b':b,'c':c})
 overlay=actor_map(m,a,s);assert overlay.can_stand(1,0)
 assert overlay.step_destination((1,0),'west')==(0,0);assert overlay.step_destination((1,0),'east') is None

def test_surf_dismount_cannot_overlap_bank_character():
 m=terrain(['11'],{(0,0):1,(1,0):3});m.cells[(0,0)]['behavior']=0x15
 a={'human_id':'a','map_id':'m','x':0,'y':0,'status':{'surfing':True}};b={'human_id':'b','map_id':'m','x':1,'y':0}
 assert actor_map(m,a,SimpleNamespace(humans={'a':a,'b':b})).step_destination((0,0),'east',surfing=True) is None

def test_collision_marked_ledge_can_jump_only_to_safe_landing():
 m=terrain(['101']);m.cells[(1,0)]['behavior']=0x38
 assert m.step_destination((0,0),'east')==(2,0)
 m._walk[0][2]=False;m.cells[(2,0)]['collision']=1
 assert m.step_destination((0,0),'east') is None

def test_visible_item_blocks_until_collected_for_that_trainer():
 m=terrain(['111']);m.events={'object_events':[{'local_id':2,'graphics_id':'OBJ_EVENT_GFX_ITEM_BALL','x':1,'y':0,'script':'ItemScript'}]};a={'human_id':'a','map_id':'m','x':0,'y':0}
 assert actor_map(m,a).step_destination((0,0),'east') is None
 a['collected_source_items']=['m:2:ItemScript'];assert actor_map(m,a).step_destination((0,0),'east')==(1,0)
