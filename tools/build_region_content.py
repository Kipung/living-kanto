#!/usr/bin/env python3
"""Build mainland inventory from pinned pret data; preserve source encounter variants."""
import json,re,hashlib,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; REF=ROOT/'reference/pokefirered'
def build():
 layouts={x['id']:x for x in json.loads((REF/'data/layouts/layouts.json').read_text())['layouts'] if 'id' in x}
 prefixes=('PalletTown','ViridianCity','PewterCity','CeruleanCity','VermilionCity','LavenderTown','CeladonCity','FuchsiaCity','SaffronCity','CinnabarIsland','IndigoPlateau','ViridianForest','MtMoon','DiglettsCave','RockTunnel','PokemonTower','SafariZone','SeafoamIslands','PokemonMansion','PowerPlant','VictoryRoad','CeruleanCave','UndergroundPath','SSAnne','PokemonLeague','SilphCo','RocketHideout')
 selected=[]
 for p in sorted((REF/'data/maps').glob('*/map.json')):
  m=json.loads(p.read_text()); name=m['name']
  if name.startswith(prefixes) or re.match(r'^Route(?:[1-9]|1[0-9]|2[0-5])(?:_|$)',name): selected.append((m,p))
 ids={m['id']:m['name'] for m,p in selected}; maps=[]
 for m,p in selected:
  l=layouts[m['layout']]; maps.append({'id':m['name'],'reference_id':m['id'],'filename':m['name']+'.json','width':l['width'],'height':l['height'],'type':m['map_type'],'requires_flash':m['requires_flash'],'connections':[{**c,'map':ids.get(c['map'],c['map'])} for c in m.get('connections') or []], 'warps':[{**w,'dest_map':ids.get(w['dest_map'],w['dest_map'])} for w in m.get('warp_events',[]) if w['dest_map'] in ids], 'source':str(p.relative_to(REF)), 'source_sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
 wild=json.loads((REF/'src/data/wild_encounters.json').read_text()); encounters=[]
 for group in wild['wild_encounter_groups']:
  for e in group.get('encounters',[]):
   if e.get('map') in ids: encounters.append({**e,'map':ids[e['map']]})
 result={'schema_version':1,'content_version':'kanto-mainland-1','reference_revision':'037335f4c725d7c9aecdac87066f2002b4bd7e14','maps':maps,'encounter_fields':wild['wild_encounter_groups'][0]['fields'],'encounters':encounters,'adaptations':['FireRed and LeafGreen encounter variants coexist; choose a source variant deterministically per encounter.','Story progression is per trainer; static warp records alone do not grant traversal permission.'],'progression':[{'badge':badge,'leader':leader,'map_id':mapid,'source':'src/data/trainers.h'} for badge,leader,mapid in zip(['boulder','cascade','thunder','rainbow','soul','marsh','volcano','earth'],['Brock','Misty','Lt. Surge','Erika','Koga','Sabrina','Blaine','Giovanni'],['PewterCity_Gym','CeruleanCity_Gym','VermilionCity_Gym','CeladonCity_Gym','FuchsiaCity_Gym','SaffronCity_Gym','CinnabarIsland_Gym','ViridianCity_Gym'])]}
 (ROOT/'content/region.json').write_text(json.dumps(result,indent=2)+'\n'); print(len(maps),'maps',len(encounters),'encounter variants')
if __name__=='__main__':build()
