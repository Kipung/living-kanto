"""Content completeness and source-backed integrity, independent of runtime minds."""
import json
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def test_population_role_counts_and_individuality():
 h=json.loads((ROOT/'content/population.json').read_text())['humans']
 assert len(h)==100 and len({x['human_id'] for x in h})==100
 assert Counter(x['role'] for x in h)=={'aspiring_trainer':30,'gym_leader':8,'elite_four':4,'initial_champion':1,'professor':1,'service_staff':20,'shop_staff':10,'worker':10,'resident':16}
 assert len({x['biography'] for x in h})==100
 assert all(x['map_id'] in {m['id'] for m in json.loads((ROOT/'content/region.json').read_text())['maps']} for x in h)
 assert all(not x['badges'] for x in h if x['role']=='aspiring_trainer')
 for x in h:assert x['goals'] and x['memories'] and x['personality'] and x['relationships']
def test_mainland_region_reference_and_coverage():
 d=json.loads((ROOT/'content/region.json').read_text());maps={m['id']:m for m in d['maps']}
 for n in range(1,26):assert any(k==f'Route{n}' or k.startswith(f'Route{n}_') for k in maps)
 assert len(d['progression'])==8
 for p in d['progression']:assert p['map_id'] in maps
 for m in maps.values():
  assert m['width']>0 and m['height']>0
  assert (ROOT/'reference/pokefirered'/m['source']).is_file()
  for c in m['connections']:assert c['map'] in maps
  for w in m['warps']:assert w['dest_map'] in maps
 assert all(e['map'] in maps for e in d['encounters'])
def test_maps_imported_or_explicitly_reported():
 d=json.loads((ROOT/'content/region.json').read_text());fail={m['map'] for m in json.loads((ROOT/'content/asset_import_failures.json').read_text())}
 for m in d['maps']:
  name=m['id'];png=ROOT/'content/maps'/f'{name}.png';meta=ROOT/'content/maps'/f'{name}.json'
  assert (png.is_file() and meta.is_file()) or name in fail

def test_school_unloaded_tile_zero_follows_vram_reset_source():
 import sys
 sys.path.insert(0,str(ROOT/'tools'))
 from import_original_assets import _cell_indices
 assert _cell_indices([7]*64,8,1,1)==[0]*64
 for mid in ['ViridianCity_School','CeladonCity_Condominiums_RoofRoom']:
  meta=json.loads((ROOT/'content/maps'/f'{mid}.json').read_text())
  assert meta['unloaded_tile_provenance']['source_sha256']['src/overworld.c']
  assert (ROOT/'content/maps'/f'{mid}.png').is_file()
 assert len(list((ROOT/'content/maps').glob('*.json')))==256

def test_overview_coordinates_and_map_sections_match_primary_source():
 import json
 from pathlib import Path
 base=Path(__file__).resolve().parents[2]
 data=json.loads((base/'content/region_overview.json').read_text())
 source=json.loads((base/'reference/pokefirered/src/data/region_map/region_map_sections.json').read_text())
 original={s['id']:s for s in source['map_sections']}
 assert len(data['maps'])==256
 assert data['width']==22 and data['height']==15
 assert data['layers']['LAYER_MAP'][11][4]=='MAPSEC_PALLET_TOWN'
 for section in data['sections']:assert section==original[section['id']]
 for m in data['maps']:
  raw=json.loads((base/'reference/pokefirered/data/maps'/m['map_id']/'map.json').read_text())
  assert m['section_id']==raw['region_map_section']
