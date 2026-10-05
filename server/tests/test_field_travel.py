from pathlib import Path
import random
from types import SimpleNamespace
import pytest
from living_kanto.simulation.world import WorldEngine
from living_kanto.simulation.field_travel import actions,changes_for
from living_kanto.simulation.field import actor_map
from living_kanto.simulation.scenarios import scenario_effects
from living_kanto.mechanics import create_pokemon

def fixture():
 e=WorldEngine(Path(__file__).resolve().parents[2]/'content');h={'human_id':'h','map_id':'PalletTown','x':6,'y':8,'inventory':{},'badges':['thunder','boulder'],'party':['p'],'field':{'visited_maps':['PalletTown','ViridianCity']},'status':{}}
 p=create_pokemon('PIDGEY',10,'h',random.Random(2),identifier='p');p['moves']=[{'move':'FLY','pp':15},{'move':'FLASH','pp':20}]
 return e,h,SimpleNamespace(pokemon={'p':p})
def test_fly_source_landing_requires_own_badge_move_and_personal_visit_even_creative():
 e,h,state=fixture();choices=actions(state,h,e.maps);fly=next(a for a in choices if a.action=='fly_to')
 assert fly.arguments=={'map_id':'ViridianCity'} and fly.known_consequences['source_landing']==[26,27]
 changes,receipt=changes_for(state,h,e.maps,'fly_to',fly.arguments)
 assert receipt['heal_location']=='HEAL_LOCATION_VIRIDIAN_CITY'
 for args in [{'map_id':'CeruleanCity'},{'map_id':'ViridianCity','x':1}]:
  with pytest.raises(ValueError):changes_for(state,h,e.maps,'fly_to',args)
 state.pokemon['p']['hp']=0;assert any(a.action=='fly_to' for a in actions(state,h,e.maps))
 h['badges']=[];state.mode='creative'
 assert not any(a.action=='fly_to' for a in actions(state,h,e.maps))
 h['badges']=['thunder'];state.pokemon['p']['owner_id']='other'
 assert not any(a.action=='fly_to' for a in actions(state,h,e.maps))
def test_flash_only_dark_cave_requires_badge_and_stays_per_trainer():
 e,h,state=fixture();assert not any(a.action=='flash' for a in actions(state,h,e.maps))
 h['map_id']='RockTunnel_1F';assert any(a.action=='flash' for a in actions(state,h,e.maps))
 changes,_=changes_for(state,h,e.maps,'flash',{});assert changes==[{'op':'set','path':'humans.h.field.flash_active','value':True}]
 assert not h['field'].get('flash_active');h['field']['flash_active']=True
 assert not any(a.action=='flash' for a in actions(state,h,e.maps))
def test_bicycle_trigger_cannot_be_walked_without_legitimate_exchange():
 e,h,state=fixture();m=e.maps['Route16_NorthEntrance_1F'];trigger=next(t for t in m.events['coord_events'] if 'NeedBikeTrigger' in t['script'])
 assert not actor_map(m,h).is_walkable(trigger['x'],trigger['y'])
 h.update(map_id='CeruleanCity_BikeShop',x=9,y=4)
 with pytest.raises(ValueError):scenario_effects(state,h,e.maps,{'scenario_id':'bike_exchange'})
 h['inventory']['bike_voucher']={'item_id':'bike_voucher','quantity':1}
 reward=scenario_effects(state,h,e.maps,{'scenario_id':'bike_exchange'})['changes'][0]['value'];assert reward['bike_voucher']['quantity']==0 and reward['bicycle']['quantity']==1
 h['inventory']=reward;assert actor_map(m,h).is_walkable(trigger['x'],trigger['y'])
 h['map_id']='Route1';assert any(a.action=='ride_bicycle' for a in actions(state,h,e.maps))
 h['map_id']='PalletTown_ProfessorOaksLab';assert not any(a.action=='ride_bicycle' for a in actions(state,h,e.maps))

def test_source_cycling_road_permission_is_individual_and_forces_mount():
 from living_kanto.simulation.access import transfer_gate,AccessDenied
 e,h,state=fixture();h['map_id']='Route16'
 with pytest.raises(AccessDenied):transfer_gate(h,'Route17')
 h['inventory']['bicycle']={'item_id':'bicycle','quantity':1}
 changes=transfer_gate(h,'Route17');assert {'op':'set','path':'humans.h.status.bicycle','value':True} in changes
 h['status'].update(bicycle=True,cycling_road=True)
 assert not any(a.action=='dismount_bicycle' for a in actions(state,h,e.maps))

def test_production_flash_is_replayable_and_dark_actor_visibility_is_private(tmp_path):
 from living_kanto.store.run_store import RunStore
 from living_kanto.contracts.state import StateUpdate
 e=WorldEngine(Path(__file__).resolve().parents[2]/'content');store=RunStore(tmp_path/'flash.db');e.initialize(store,'flash',mode='survival');_,state,head=store.load_run('flash')
 h=state.humans['human-001'];point=e.maps['RockTunnel_1F'].first_open_cell();h.update(map_id='RockTunnel_1F',x=point[0],y=point[1],party=['p'],badges=['boulder'],field={})
 p=create_pokemon('BULBASAUR',5,h['human_id'],random.Random(2),identifier='p');p['moves']=[{'move':'FLASH','pp':20}];p['hp']=0;state.pokemon['p']=p;state.state_hash=state.compute_state_hash()
 class Fixture:
  def load_run(self,run):return None,state,head
 event,new=e.build_action_event(Fixture(),'flash',h['human_id'],action='flash',arguments={},observation_version=0,expected_state_version=0,decision_explanation='Illuminate the cave',decision_provenance={'kind':'user'})
 assert new.humans[h['human_id']]['field']['flash_active']
 assert not state.humans[h['human_id']]['field'].get('flash_active')
 assert StateUpdate.from_dict(event.transaction).apply_to(state).state_hash==new.state_hash
 store.close()
