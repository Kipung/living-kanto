from pathlib import Path
from living_kanto.simulation.world import WorldEngine
from living_kanto.simulation.movement_encounters import intercept
from living_kanto.store.run_store import RunStore
from living_kanto.contracts.state import StateUpdate

def test_actual_source_travel_stops_and_starts_battle_in_same_update(tmp_path,monkeypatch):
 from living_kanto.mechanics import create_pokemon
 import random
 e=WorldEngine(Path(__file__).resolve().parents[2]/'content');s=RunStore(tmp_path/'walk.db');e.initialize(s,'walk',mode='survival')
 _,state,head=s.load_run('walk');hid='human-001';h=state.humans[hid]
 m=e.maps['Route1'];grass=next(p for p,c in m.cells.items() if c.get('encounter_type')==1 and m.is_walkable(*p))
 h.update(map_id='Route1',x=grass[0],y=grass[1],party=['owned'],status={},inventory={},badges=[],pokedex=[]);state.pokemon['owned']=create_pokemon('BULBASAUR',5,hid,random.Random(3),identifier='owned');state.state_hash=state.compute_state_hash()
 row=next(r for r in e.encounter_table('Route1') if r.get('land_mons') and 'LeafGreen' not in r.get('base_label',''))['land_mons']['mons'][0]
 encounter={**row,'max_level':row['min_level']}
 def force(actor,cell,tables,party,rng,**kw):
  actor=dict(actor);actor['field_encounter']={'steps':0,'map_id':'Route1'};return actor,encounter
 monkeypatch.setattr('living_kanto.simulation.movement_encounters.walking_encounter',force)
 route={'map_id':'Route1','start':[grass[0],grass[1]+1],'steps':[list(grass),[grass[0],grass[1]-1]],'duration_seconds':2}
 changes,duration,evidence,kind=intercept(e,state,hid,'travel_to',{}, {'kind':'identified_test'},'travel',route,[],2)
 new=state.with_advanced_version(changes)
 assert (new.humans[hid]['x'],new.humans[hid]['y'])==grass
 assert new.humans[hid]['battle_id'] in new.world_facts["battles"]
 assert evidence['steps']==[list(grass)] and evidence['interruption_reason']=='source wild encounter'
 assert len(new.pokemon)==len(state.pokemon)+1 and kind=='battle.started'
 # Verify the production command emits one replayable movement+battle receipt.
 direction,start=next((d,(grass[0]-dx,grass[1]-dy)) for d,(dx,dy) in {'north':(0,-1),'south':(0,1),'east':(1,0),'west':(-1,0)}.items() if m.step_destination((grass[0]-dx,grass[1]-dy),d)==grass)
 h.update(x=start[0],y=start[1]);state.state_hash=state.compute_state_hash()
 class Fixture:
  def load_run(self,run):return None,state,head
 event,after=e.build_action_event(Fixture(),'walk',hid,action='walk_to',arguments={'direction':direction},observation_version=0,expected_state_version=0,decision_explanation='Source movement interruption test',decision_provenance={'kind':'user','test_fixture':'forced encounter selection'})
 assert event.event_kind=='battle.started'
 assert event.deterministic_inputs['route']['steps']==[list(grass)]
 assert StateUpdate.from_dict(event.transaction).apply_to(state).state_hash==after.state_hash
 s.close()

def test_source_field_poison_stops_walk_and_recovers_same_individual_atomically(tmp_path,monkeypatch):
 from living_kanto.mechanics import create_pokemon
 import random
 e=WorldEngine(Path(__file__).resolve().parents[2]/'content');store=RunStore(tmp_path/'poison.db');e.initialize(store,'poison',mode='survival');_,state,head=store.load_run('poison')
 hid='human-001';h=state.humans[hid];m=e.maps['PalletTown'];start=m.first_open_cell((10,8))
 h.update(map_id='PalletTown',x=start[0],y=start[1])
 from living_kanto.simulation.field import actor_map
 traversable=actor_map(m,h,state)
 direction=next(d for d in ['north','south','east','west'] if traversable.step_destination(start,d))
 h.update(map_id='PalletTown',x=start[0],y=start[1],party=['owned'],money=3000,field_steps={'poison':4,'happiness':0},active_plan={'kind':'journey','destination_map':'ViridianCity'})
 mon=create_pokemon('BULBASAUR',5,hid,random.Random(2),identifier='owned');mon.update(hp=1,status='psn');state.pokemon['owned']=mon;state.state_hash=state.compute_state_hash()
 class Fixture:
  def load_run(self,run):return None,state,head
 event,new=e.build_action_event(Fixture(),'poison',hid,action='walk_to',arguments={'direction':direction},observation_version=0,expected_state_version=0,decision_explanation='One step while poisoned',decision_provenance={'kind':'user'})
 recovered=new.humans[hid]
 assert event.event_kind=='human.fainted' and event.deterministic_inputs['route']['interruption_reason']=='field poison whiteout'
 assert recovered['map_id']=='PalletTown_PlayersHouse_1F' and recovered['active_plan'] is None
 assert recovered['money']<3000 and recovered['last_whiteout']['reason']=='field_poison'
 assert new.pokemon['owned']['hp']==new.pokemon['owned']['stats']['hp'] and new.pokemon['owned']['owner_id']==hid and recovered['party']==['owned']
 assert StateUpdate.from_dict(event.transaction).apply_to(state).state_hash==new.state_hash
 store.close()
