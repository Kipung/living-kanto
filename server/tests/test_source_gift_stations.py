import re
from pathlib import Path
import pytest
from living_kanto.simulation.scenarios import definitions, eligible, scenario_effects, ScenarioError

ROOT = Path(__file__).resolve().parents[2]

def test_source_aide_thresholds_and_individual_completion():
    for row in definitions():
        if row['id'] not in {'aide_itemfinder','aide_exp_share','aide_amulet_coin','aide_everstone'}:
            continue
        source = (ROOT/'reference/pokefirered'/row['source']).read_text()
        threshold = int(re.search(r'\.equ REQUIRED_(?:CAUGHT|OWNED)_MONS, (\d+)', source)[1])
        assert row['caught_species'] == threshold
        assert 'ITEM_'+row['reward'].upper() in source
        h={'human_id':'a','map_id':row['map_id'],'x':row['x']-1,'y':row['y'],'inventory':{},'pokedex':[str(i) for i in range(threshold-1)]}
        assert not eligible(h,row)
        h['pokedex'].append(str(threshold-1))
        assert eligible(h,row)
        result=scenario_effects(None,h,{}, {'scenario_id':row['id']})
        assert result['changes'][0]['value'][row['reward']]['quantity']==1
        h['scenarios']={'completed':[row['id']]}
        with pytest.raises(ScenarioError): scenario_effects(None,h,{}, {'scenario_id':row['id']})
        assert eligible({**h,'human_id':'b','scenarios':{}},row)

def test_source_rods_are_local_distinct_and_once_per_trainer():
    rods = [r for r in definitions() if r['id'].startswith('fishing_')]
    assert {r['reward'] for r in rods}=={'old_rod','good_rod','super_rod'}
    for row in rods:
        assert 'ITEM_'+row['reward'].upper() in (ROOT/'reference/pokefirered'/row['source']).read_text()
        h={'human_id':'a','map_id':row['map_id'],'x':row['x'],'y':row['y']+1,'inventory':{},'pokedex':[]}
        assert eligible(h,row)
        assert not eligible({**h,'map_id':'PalletTown'},row)
        assert not eligible({**h,'x':0,'y':0},row)
        assert not eligible({**h,'scenarios':{'completed':[row['id']]}},row)
