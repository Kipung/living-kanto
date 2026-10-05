import pytest
from types import SimpleNamespace
from pathlib import Path
from living_kanto.simulation.maps import GameMap
from living_kanto.simulation.routeplanner import plan_journey,JourneyUnavailable

def synthetic(mid,target=None):
 m=GameMap(mid,5,3,['11111']*3,{(4,1):target} if target else {},events={'connections':[{'direction':'right','map':target,'offset':0}]} if target else {})
 return m

def test_journey_traces_exact_steps_and_each_source_transfer():
 maps={'a':synthetic('a','b'),'b':synthetic('b','c'),'c':synthetic('c')}
 h={'human_id':'h','map_id':'a','x':1,'y':1,'inventory':{},'badges':[],'status':{}}
 route=plan_journey(maps,h,'c')
 assert [r['map_id'] for r in route]==['a','b']
 assert route[0]['steps']==[[2,1],[3,1],[4,1]]
 assert route[0]['destination']==[0,1]
 assert route[1]['destination_map']=='c'
 assert h['map_id']=='a'

def test_planner_cannot_cross_badge_gate_or_blocked_tiles():
 maps={'a':synthetic('a','Route23'),'Route23':synthetic('Route23')}
 h={'human_id':'h','map_id':'a','x':1,'y':1,'inventory':{},'badges':[],'status':{}}
 with pytest.raises(JourneyUnavailable):plan_journey(maps,h,'Route23')
 h['badges']=['boulder','cascade','thunder','rainbow','soul','marsh','volcano','earth']
 assert plan_journey(maps,h,'Route23')
 maps['a']._walk[0][2]=maps['a']._walk[1][2]=maps['a']._walk[2][2]=False
 with pytest.raises(JourneyUnavailable):plan_journey(maps,h,'Route23')

def test_actual_source_local_to_next_city_route_without_teleport():
 from living_kanto.simulation.world import WorldEngine
 engine=WorldEngine(Path(__file__).resolve().parents[2]/'content')
 h={'human_id':'h','map_id':'PalletTown','x':10,'y':8,'inventory':{},'badges':[],'party':[],'status':{}}
 route=plan_journey(engine.maps,h,'ViridianCity',state=SimpleNamespace(pokemon={}))
 assert [s['destination_map'] for s in route]==['Route1','ViridianCity']
 for segment in route:
  previous=segment['start'];m=engine.maps[segment['map_id']]
  for point in segment['steps']:
   assert m.is_walkable(*point) and abs(point[0]-previous[0])+abs(point[1]-previous[1]) in (1,2)
   previous=point

def test_source_journey_engine_records_route_and_replays_same_hash(tmp_path):
 from living_kanto.simulation.world import WorldEngine
 from living_kanto.store.run_store import RunStore
 from living_kanto.contracts.state import StateUpdate
 engine=WorldEngine(Path(__file__).resolve().parents[2]/'content');store=RunStore(tmp_path/'journey.db');engine.initialize(store,'journey',mode='survival')
 _,state,head=store.load_run('journey');h=state.humans['human-001'];h.update(map_id='PalletTown',x=10,y=8,inventory={},badges=[],party=[],status={});state.state_hash=state.compute_state_hash()
 class FixtureStore:
  def load_run(self,run):return None,state,head
 event,new=engine.build_action_event(FixtureStore(),'journey','human-001',action='journey_to',arguments={'map_id':'ViridianCity'},observation_version=0,expected_state_version=0,decision_explanation='Travel to the next city along public roads',decision_provenance={'kind':'user'})
 route=event.deterministic_inputs['route'];assert route['journey'] and route['duration_seconds']==new.simulated_time-state.simulated_time
 assert new.humans['human-001']['map_id']=='ViridianCity'
 assert StateUpdate.from_dict(event.transaction).apply_to(state).state_hash==new.state_hash
 store.close()
