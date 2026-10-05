"""Source Fly, Flash and Bicycle permissions; no Creative implicit bypass."""
import json
from functools import lru_cache
from pathlib import Path
from ..contracts.human import LegalAction
from .field import permission
from .scenarios import quantity
OUTDOORS={'MAP_TYPE_ROUTE','MAP_TYPE_TOWN','MAP_TYPE_OCEAN_ROUTE','MAP_TYPE_CITY'}
@lru_cache(maxsize=1)
def rules():return json.loads((Path(__file__).resolve().parents[3]/'content/field_travel.json').read_text())
def actions(state,h,maps):
 m=maps[h['map_id']];out=[];field=h.get('field',{});status=h.get('status',{})
 if m.events.get('requires_flash') and not field.get('flash_active') and permission(state,h,'FLASH'):out.append(LegalAction(action='flash',arguments={},known_consequences={'lights_current_cave':True,'source_radius_pixels':200}))
 if permission(state,h,'FLY') and m.events.get('map_type') in OUTDOORS:
  visited=set(field.get('visited_maps',[]))|{h['map_id']}
  for d in rules()['fly_destinations']:
   if d['map_id'] in visited and d['map_id']!=h['map_id'] and d['map_id'] in maps and maps[d['map_id']].is_walkable(d['x'],d['y']):out.append(LegalAction(action='fly_to',arguments={'map_id':d['map_id']},known_consequences={'source_landing':[d['x'],d['y']],'personally_visited':True}))
 if quantity(h,'bicycle') and not status.get('surfing'):
  if status.get('bicycle'):
   if not status.get('cycling_road') and h['map_id']!='Route17':out.append(LegalAction(action='dismount_bicycle',arguments={},known_consequences={'on_foot':True}))
  elif m.events.get('allow_cycling'):out.append(LegalAction(action='ride_bicycle',arguments={},known_consequences={'source_encounter_rate_percent':80,'integer_tile_seconds':1}))
 return out

def changes_for(state,h,maps,action,args):
 if not any(a.action==action and a.arguments==args for a in actions(state,h,maps)):raise ValueError('Field travel permission or source location unavailable')
 p='humans.'+h['human_id'];changes=[];evidence=None
 if action=='flash':changes=[{'op':'set','path':p+'.field.flash_active','value':True}]
 elif action in ('ride_bicycle','dismount_bicycle'):changes=[{'op':'set','path':p+'.status.bicycle','value':action=='ride_bicycle'}]
 else:
  d=next(d for d in rules()['fly_destinations'] if d['map_id']==args['map_id']);evidence={'source':'src/region_map.c:sMapFlyDestinations','heal_location':d['heal_location'],'destination_map':d['map_id'],'landing':[d['x'],d['y']]}
  for key,value in [('map_id',d['map_id']),('x',d['x']),('y',d['y']),('status.surfing',False),('status.bicycle',False),('status.cycling_road',False),('status.source_forced_surfing',False),('field.flash_active',False)]:changes.append({'op':'set','path':p+'.'+key,'value':value})
 return changes,evidence
