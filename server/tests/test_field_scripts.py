from pathlib import Path
from living_kanto.simulation.world import WorldEngine
from living_kanto.simulation.field_scripts import transition_effects

def engine():return WorldEngine(Path(__file__).resolve().parents[2]/'content')
def test_source_b3_fall_has_exact_scripted_current_warp():
 e=engine();h={'human_id':'h','field':{},'status':{}}
 a,trace=transition_effects(e.maps,h,e.maps['SeafoamIslands_B2F'],(24,8),'SeafoamIslands_B3F',(23,9))
 assert (a['map_id'],a['x'],a['y'])==('SeafoamIslands_B4F',27,18)
 assert a['status']['source_forced_surfing'] and a['status']['surfing']
 assert trace[0]['steps'][-1]==[26,19] and trace[1]['script_warp']==[27,21]
 assert h['field']=={} and h['status']=={}
def test_source_b4_fall_dumps_north_on_land_without_granting_hm():
 e=engine();a,trace=transition_effects(e.maps,{'field':{},'status':{}},e.maps['SeafoamIslands_B3F'],(6,18),'SeafoamIslands_B4F',(8,17))
 assert (a['x'],a['y'])==(12,12)
 assert not a['status']['surfing']
 assert 'inventory' not in a and 'dismount_source' in trace[0]
def test_route20_resets_uncompleted_puzzle_only_for_this_trainer():
 e=engine();h={'field':{'boulders':{'SeafoamIslands_1F:1':[1,1]},'fallen_boulders':['SeafoamIslands_1F:1'],'revealed_boulders':['FLAG_HIDE_SEAFOAM_B1F_BOULDER_1']}}
 a,t=transition_effects(e.maps,h,e.maps['SeafoamIslands_1F'],(6,21),'Route20',(48,8))
 assert not a['field']['revealed_boulders'] and not a['field']['fallen_boulders'] and not a['field']['boulders']
 assert h['field']['revealed_boulders'] and t[0]['source']=='data/maps/Route20/scripts.inc'

def test_actual_walk_into_source_hole_falls_without_a_surf_permission(tmp_path):
 from living_kanto.store.run_store import RunStore
 from living_kanto.contracts.state import StateUpdate
 e=engine();store=RunStore(tmp_path/'fall.db');e.initialize(store,'fall',mode='survival');_,state,head=store.load_run('fall')
 h=state.humans['human-001'];m=e.maps['SeafoamIslands_B2F'];hole=(24,8)
 direction,start=next((d,(hole[0]-dx,hole[1]-dy)) for d,(dx,dy) in {'north':(0,-1),'south':(0,1),'east':(1,0),'west':(-1,0)}.items() if m.step_destination((hole[0]-dx,hole[1]-dy),d)==hole)
 h.update(map_id=m.map_id,x=start[0],y=start[1],field={},status={},party=[],badges=[],inventory={});state.state_hash=state.compute_state_hash()
 class Fixture:
  def load_run(self,run):return None,state,head
 event,new=e.build_action_event(Fixture(),'fall','human-001',action='walk_to',arguments={'direction':direction},observation_version=0,expected_state_version=0,decision_explanation='Walk into source hole',decision_provenance={'kind':'user'})
 actor=new.humans['human-001'];assert (actor['map_id'],actor['x'],actor['y'])==('SeafoamIslands_B4F',27,18)
 assert actor['status']['source_forced_surfing'] and not actor['badges'] and not actor['inventory']
 assert event.deterministic_inputs['route']['fall_warp']['source']==[24,8]
 assert StateUpdate.from_dict(event.transaction).apply_to(state).state_hash==new.state_hash
 store.close()

def test_activity_boundary_cannot_unlock_input_midway_through_source_spin():
 from living_kanto.simulation.maps import GameMap
 from living_kanto.simulation.field_scripts import safe_travel_slice
 m=GameMap('spin',6,1,['111111'],{});m.cells={(i,0):{'behavior':b} for i,b in enumerate([0,0x54,0,0,0x58,0])}
 route=[[i,0] for i in range(1,6)]
 assert safe_travel_slice(m,route,2)==4
 assert safe_travel_slice(m,route,4)==4
