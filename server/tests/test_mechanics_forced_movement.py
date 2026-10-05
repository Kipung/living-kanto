"""Cartridge lastSpinTile persists across normal floor until STOP/collision."""
import copy,random
import pytest
from test_gameplay import game,state,scenario,locate
from test_shared_clock_engine import activate,choose
from living_kanto.mechanics import create_pokemon
from living_kanto.simulation.engine import EngineError

SPIN=range(0x54,0x58)
def spin_route(e):
 gm=e.maps['RocketHideout_B2F']
 for start,cell in gm.cells.items():
  if not gm.is_walkable(*start):continue
  for direction in ('north','south','east','west'):
   path=gm.step_path(start,direction)
   if not path or len(path)<4 or int(gm.cells[path[0]].get('behavior',0)) not in SPIN or int(gm.cells[path[-1]].get('behavior',0))!=0x58:continue
   values=[int(gm.cells[p].get('behavior',0)) for p in path]
   if any(values[i] not in SPIN and values[i]!=0x58 and values[i+1] not in SPIN and values[i+1]!=0x58 for i in range(len(values)-1)):return gm,start,direction,path
 raise AssertionError('Source spin route with consecutive normal momentum tiles missing')

def setup_spin(game):
 e,_=game;gm,start,direction,path=spin_route(e);locate(game,'human-001',gm.map_id,start)
 mon=create_pokemon('PIDGEY',5,'human-001',random.Random(1),identifier='spin-poison-mon');mon['hp']=10;mon['status']='psn'
 scenario(game,[{'op':'set','path':f'pokemon.{mon["pokemon_id"]}','value':mon},{'op':'set','path':'humans.human-001.party','value':[mon['pokemon_id']]},{'op':'set','path':'humans.human-001.field_steps','value':{'happiness':0,'poison':4}}]);activate(game);choose(game,'human-001','walk_to',{'direction':direction})
 return gm,path,mon

def test_source_spin_retains_control_and_poison_guard_until_stop(game):
 e,store=game;gm,path,mon=setup_spin(game)
 for position in path:
  before=state(game);e.tick_shared_time(store,'gameplay-test',before.simulated_time+1);s=state(game);h=s.humans['human-001']
  assert (h['x'],h['y'])==position
  assert h['field_steps']['poison']==4 and s.pokemon[mon['pokemon_id']]['hp']==10
  if int(gm.cells[position].get('behavior',0))!=0x58:
   assert h['movement_intent']['forced_mode']=='spin' and h['movement_intent']['forced_movement']
   assert not e.legal_actions(s,'human-001')
   with pytest.raises(EngineError):choose(game,'human-001','cancel_movement',{})
  else:assert h['movement_intent'] is None
 assert store.replay('gameplay-test').state_hash==state(game).state_hash

def test_legacy_mid_spin_false_boolean_recovers_from_accepted_path(game):
 e,store=game;gm,path,mon=setup_spin(game)
 normal_index=next(i for i in range(1,len(path)-1) if int(gm.cells[path[i]].get('behavior',0)) not in SPIN and int(gm.cells[path[i+1]].get('behavior',0)) not in SPIN and int(gm.cells[path[i+1]].get('behavior',0))!=0x58)
 for _ in range(normal_index+1):e.tick_shared_time(store,'gameplay-test',state(game).simulated_time+1)
 intent=copy.deepcopy(state(game).humans['human-001']['movement_intent']);intent.pop('forced_mode');intent.pop('forced_direction');intent['forced_movement']=False
 scenario(game,[{'op':'set','path':'humans.human-001.movement_intent','value':intent}]);e.tick_shared_time(store,'gameplay-test',state(game).simulated_time+1);s=state(game)
 assert s.humans['human-001']['movement_intent']['forced_mode']=='spin'
 assert s.humans['human-001']['movement_intent']['forced_direction'] in ('north','south','east','west')
 assert s.humans['human-001']['field_steps']['poison']==4 and s.pokemon[mon['pokemon_id']]['hp']==10
 assert store.replay('gameplay-test').state_hash==s.state_hash

def test_spin_wall_collision_clears_mode_before_ordinary_direction(game):
 e,_=game;gm,start,direction,path=spin_route(e);point=path[1];spin_direction={0x54:'east',0x55:'west',0x56:'north',0x57:'south'}[int(gm.cells[path[0]].get('behavior',0))];delta={'east':(1,0),'west':(-1,0),'north':(0,-1),'south':(0,1)}[spin_direction]
 blocked=copy.deepcopy(gm);next_point=(point[0]+delta[0],point[1]+delta[1]);blocked._walk[next_point[1]][next_point[0]]=False
 before,mode,d=e._forced_context({'status':{}},{'forced_mode':'spin','forced_direction':spin_direction},blocked,point)
 assert before is True and mode is None and d is None

def test_water_current_ends_on_noncurrent_landing(game):
 e,_=game;gm=next(m for m in e.maps.values() if any(int(c.get('behavior',0)) in range(0x50,0x54) for c in m.cells.values()));point=next(p for p,c in gm.cells.items() if int(c.get('behavior',0)) in (0x10,0x11,0x12,0x13,0x15,0x1a,0x1b))
 before,mode,d=e._forced_context({'status':{'surfing':True}},{'forced_mode':'current','forced_direction':'east'},gm,point)
 assert before is True and mode is None and d is None
