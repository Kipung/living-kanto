"""Extract display geography, never invent map coordinates or connections."""
import hashlib,json,re
from pathlib import Path
BASE=Path(__file__).resolve().parents[1];REF=BASE/'reference/pokefirered'
sections_path=REF/'src/data/region_map/region_map_sections.json';layout_path=REF/'src/data/region_map/region_map_layout_kanto.h'
source=json.loads(sections_path.read_text());sections={s['id']:s for s in source['map_sections'] if 'x' in s}
layout=layout_path.read_text();layers={}
for name,body in re.findall(r'\[(LAYER_\w+)\]\s*=\s*\{(.*?)\n    \}',layout,re.S):
 rows=[re.findall(r'MAPSEC_\w+',r) for r in re.findall(r'\{([^{}]+)\}',body)]
 assert len(rows)==15 and all(len(r)==22 for r in rows)
 layers[name]=rows
inventory=json.loads((BASE/'content/region.json').read_text())['maps'];locations=[];used=set()
for m in inventory:
 p=REF/'data/maps'/m['id']/'map.json';raw=json.loads(p.read_text());sec=raw['region_map_section'];used.add(sec)
 locations.append({'map_id':m['id'],'section_id':sec,'type':raw['map_type'],'floor':raw.get('floor_number',0)})
out={'schema_version':1,'width':22,'height':15,'layers':layers,'sections':[sections[k] for k in sorted(used) if k in sections],'maps':locations,'source':[{'path':str(p.relative_to(REF)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in [sections_path,layout_path]],'display_note':'Schematic cells and positions extracted from the original Kanto region map; viewing a map does not move a person.'}
(BASE/'content/region_overview.json').write_text(json.dumps(out,indent=2)+'\n')
print(len(locations),'maps',len(out['sections']),'source sections',list(layers))
