from pathlib import Path
import json
import pytest
from living_kanto.simulation.scenarios import scenario_actions,scenario_effects,ScenarioError,definitions
ROOT=Path(__file__).resolve().parents[2]
def trainer(mid,x,y):return {'human_id':'a','map_id':mid,'x':x,'y':y,'inventory':{},'pokedex':[]}
def test_scenario_reward_sources_and_station_coordinates():
 for row in definitions():
  assert (ROOT/'reference/pokefirered'/row['source']).is_file()
  m=json.loads((ROOT/'reference/pokefirered/data/maps'/row['map_id']/'map.json').read_text())
  assert any((e['x'],e['y'])==(row['x'],row['y']) for e in m.get('object_events',[])+m.get('bg_events',[]))
def test_bill_console_before_ticket_and_once_per_individual():
 h=trainer('Route25_SeaCottage',4,4)
 assert [a.arguments['scenario_id'] for a in scenario_actions(None,h,{})]==['bill_cell_separator']
 h.update(x=7,y=4)
 assert not scenario_actions(None,h,{})
 h['scenarios']={'completed':['bill_cell_separator']}
 result=scenario_effects(None,h,{}, {'scenario_id':'bill_ticket'})
 assert result['changes'][0]['value']['ss_ticket']['quantity']==1
 h['scenarios']['completed'].append('bill_ticket')
 with pytest.raises(ScenarioError):scenario_effects(None,h,{}, {'scenario_id':'bill_ticket'})
 assert scenario_actions(None, {**h,'human_id':'b','scenarios':{'completed':['bill_cell_separator']}},{})
def test_gold_teeth_exchange_consumes_and_flash_counts_caught_species():
 h=trainer('FuchsiaCity_WardensHouse',3,4)
 with pytest.raises(ScenarioError):scenario_effects(None,h,{}, {'scenario_id':'warden_strength'})
 h['inventory']={'GOLD_TEETH':{'quantity':1}}
 result=scenario_effects(None,h,{}, {'scenario_id':'warden_strength'})
 inv=result['changes'][0]['value'];assert inv['GOLD_TEETH']['quantity']==0 and inv['HM04']['quantity']==1
 h=trainer('Route2_EastBuilding',4,5);h['pokedex']=['BULBASAUR']*10
 assert not scenario_actions(None,h,{})
 h['pokedex']=[str(i) for i in range(10)]
 assert scenario_actions(None,h,{})[0].arguments['scenario_id']=='aide_flash'
def test_no_remote_station_or_unearned_captain_cut():
 h=trainer('SSAnne_CaptainsOffice',5,3)
 assert not scenario_actions(None,h,{})
 h['inventory']={'ss_ticket':{'quantity':1}}
 assert scenario_actions(None,h,{})
 h.update(x=0,y=0)
 assert not scenario_actions(None,h,{})

def test_flute_requires_real_ghost_fact_and_actual_summit_station():
 h=trainer('LavenderTown_VolunteerPokemonHouse',3,4)
 assert not scenario_actions(None,h,{})
 h['scenarios']={'completed':['tower_fuji_release']}
 assert not scenario_actions(None,h,{})
 h['access']={'tower_marowak_defeated':True}
 assert scenario_actions(None,h,{})[0].arguments['scenario_id']=='fuji_flute'
 h=trainer('PokemonTower_7F',11,5)
 assert not scenario_actions(None,h,{})
 h['access']={'tower_marowak_defeated':True}
 assert scenario_actions(None,h,{})[0].arguments['scenario_id']=='tower_fuji_release'

def test_flash_case_variants_cannot_duplicate_species():
 h=trainer('Route2_EastBuilding',4,5)
 h['pokedex']=['Bulbasaur','BULBASAUR']+[str(i) for i in range(8)]
 assert not scenario_actions(None,h,{})
