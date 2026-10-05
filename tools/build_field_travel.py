"""Extract Fly destinations, field headers and darkness radii from pinned source."""
import json,re,hashlib
from pathlib import Path
B=Path(__file__).resolve().parents[1];R=B/'reference/pokefirered'
index={json.loads(p.read_text())['id']:p.parent.name for p in (R/'data/maps').glob('*/map.json')}
text=(R/'src/region_map.c').read_text();heal={r['id']:r for r in json.loads((R/'src/data/heal_locations.json').read_text())['heal_locations']};dest=[]
for macro,location in re.findall(r'\{MAP\((MAP_\w+)\),\s+(HEAL_LOCATION_\w+)\}',text):
 if location=='HEAL_LOCATION_NONE' or location not in heal or macro not in index:continue
 mid=index[macro]
 if not (B/'content/maps'/f'{mid}.json').exists():continue
 row=heal[location];dest.append({'map_id':mid,'x':row['x'],'y':row['y'],'heal_location':location})
source=['src/region_map.c','src/data/heal_locations.json','src/field_screen_effect.c','src/overworld.c','src/fldeff_flash.c','src/item_use.c']
radii=[int(x.strip()) for x in re.search(r'sFlashLevelToRadius\[\]\s*=\s*\{([^}]+)',(R/'src/field_screen_effect.c').read_text())[1].split(',')]
(B/'content/field_travel.json').write_text(json.dumps({'schema_version':1,'fly_destinations':dest,'flash_radii_pixels':radii,'source':[{'path':s,'sha256':hashlib.sha256((R/s).read_bytes()).hexdigest()} for s in source],'adaptations':['Fly unlocks by this trainer physically visiting a destination, rather than one shared protagonist flag.','Field action duration is one simulation second; visual animation timing does not change outcomes.','Bicycle uses source permissions and encounter-rate reduction; integer simulation tile timing remains one second.']},indent=2)+'\n')
for path in (B/'content/maps').glob('*.json'):
 raw_path=R/'data/maps'/path.stem/'map.json'
 if not raw_path.exists():continue
 raw=json.loads(raw_path.read_text());d=json.loads(path.read_text())
 for key in ['requires_flash','allow_cycling','allow_running','allow_escaping']:d['events'][key]=raw[key]
 path.write_text(json.dumps(d,indent=2,sort_keys=True)+'\n')
print(len(dest),'source Fly destinations',radii)
