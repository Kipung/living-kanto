"""Per-trainer field move permissions and source object state.

Badge ordering: party_menu.c CursorCB_FieldMove, FLAG_BADGE01_GET+fieldMove.
Trees/boulders use source local IDs, never global plot flags.
"""
import copy
from pathlib import Path
from ..contracts.human import LegalAction
FIELD_BADGES={'FLASH':'boulder','CUT':'cascade','FLY':'thunder','STRENGTH':'rainbow','SURF':'soul','ROCK_SMASH':'marsh','WATERFALL':'volcano'}
WATER={0x10,0x11,0x12,0x13,0x15,0x1A,0x1B,0x50,0x51,0x52,0x53}
DIRECTIONS={'north':(0,-1),'south':(0,1),'east':(1,0),'west':(-1,0)}
def permission(state,human,move):
 if FIELD_BADGES.get(move) not in human.get('badges',[]):return False
 for pid in human.get('party',[]):
  p=state.pokemon.get(pid,{})
  if p.get('owner_id')==human['human_id'] and not p.get('is_egg',False) and any(m.get('move')==move for m in p.get('moves',[])):return True
 return False

def objects(game_map,h):
 saved=h.get('field',{});removed=set(saved.get('cut',[]));positions=saved.get('boulders',{});out=[]
 for i,obj in enumerate(game_map.events.get('object_events',[])):
  gfx=obj.get('graphics_id');kind='tree' if gfx=='OBJ_EVENT_GFX_CUT_TREE' else 'boulder' if gfx=='OBJ_EVENT_GFX_PUSHABLE_BOULDER' else 'snorlax' if gfx=='OBJ_EVENT_GFX_SNORLAX' else None
  if not kind:continue
  key=f'{game_map.map_id}:{obj.get("local_id",i)}'
  if kind=='tree' and key in removed:continue
  if kind=='boulder':
   if key in saved.get('fallen_boulders',[]):continue
   flag=str(obj.get('flag',''))
   initially_hidden=flag.startswith(('FLAG_HIDE_SEAFOAM_B1F','FLAG_HIDE_SEAFOAM_B2F','FLAG_HIDE_SEAFOAM_B4F')) or flag in {'FLAG_HIDE_SEAFOAM_B3F_BOULDER_1','FLAG_HIDE_SEAFOAM_B3F_BOULDER_2'}
   if initially_hidden and flag not in saved.get('revealed_boulders',[]):continue
  if kind=='snorlax' and key in saved.get('snorlax_cleared',[]):continue
  x,y=positions.get(key,[obj['x'],obj['y']]);out.append({'key':key,'kind':kind,'x':x,'y':y,'reveal_flag':obj.get('trainer_type')})
 return out

def actor_map(game_map,h,state=None,*,reservations=(),ignore_origin=True):
 """Private traversal overlay; does not modify source maps or another trainer."""
 saved=h.get('field',{});revealed=set(saved.get('revealed_boulders',[]))
 if game_map.map_id in ('SeafoamIslands_B3F','SeafoamIslands_B4F'):
  floor=game_map.map_id.split('_')[-1];needed={f'FLAG_HIDE_SEAFOAM_{floor}_BOULDER_1',f'FLAG_HIDE_SEAFOAM_{floor}_BOULDER_2'}
  path=Path(game_map.source_path).parent.parent/'layouts'/f'{game_map.map_id}.json'
  if needed.issubset(revealed) and path.exists():
   from .maps import GameMap
   game_map=GameMap.from_content(game_map.map_id,path)
 result=copy.copy(game_map);result._walk=[row[:] for row in game_map._walk];result.cells=dict(game_map.cells);result._blocked_tiles=set(game_map._blocked_tiles)
 from .collision import actor_elevation,occupied_tiles,environmental_tiles
 result._collision_elevation=actor_elevation(game_map,h)
 from .scenarios import quantity
 if not quantity(h,'bicycle'):
  for trigger in game_map.events.get('coord_events',[]):
   if 'NeedBikeTrigger' in trigger.get('script','') and result.in_bounds(trigger['x'],trigger['y']):result._walk[trigger['y']][trigger['x']]=False
 completed=set(h.get('field',{}).get('switches',[]))
 for door in game_map.events.get('card_key_doors',[]):
  opened=door['id'] in saved.get('doors',[])
  for tile in door['opened'] if opened else door['closed']:
   x,y=tile['x'],tile['y']
   if result.in_bounds(x,y):
    result._walk[y][x]=not tile['collision'];result.cells[(x,y)]={**result.cells.get((x,y),{}),**tile}
 for switch in game_map.events.get('strength_switches',[]):
  for barrier in switch['barriers']:
   x,y=barrier['x'],barrier['y'];opened=switch['id'] in completed
   if result.in_bounds(x,y):
    result._walk[y][x]=opened
    if opened:result.cells[(x,y)]={**result.cells.get((x,y),{}),'behavior':barrier.get('behavior',0),'collision':0,'metatile_id':barrier.get('metatile_id')}
 mansion=game_map.events.get('mansion_switch')
 if mansion:
  for tile in mansion['on' if saved.get('mansion_switch') else 'off']:
   x,y=tile['x'],tile['y']
   if result.in_bounds(x,y):result._walk[y][x]=not tile['collision'];result.cells[(x,y)]={**result.cells.get((x,y),{}),**tile}
 for obj in objects(game_map,h):
  if result.in_bounds(obj['x'],obj['y']):result._walk[obj['y']][obj['x']]=False;result._blocked_tiles.add((obj['x'],obj['y']))
 for x,y in environmental_tiles(game_map,h,state):
  if result.in_bounds(x,y):result._walk[y][x]=False;result._blocked_tiles.add((x,y))
 result._dynamic_blocked=occupied_tiles(game_map,h,state,reservations,ignore_origin=ignore_origin)
 for (x,y) in result._dynamic_blocked:
  if result.in_bounds(x,y):result._walk[y][x]=False;result._blocked_tiles.add((x,y))
 return result

def actions(state,h,game_map):
 out=[]
 for statue in game_map.events.get('mansion_switch',{}).get('statues',[]):
  if (h['x'],h['y']-1)==(statue['x'],statue['y']) and h.get('facing','south')=='north':out.append(LegalAction(action='toggle_mansion_switch',arguments={},known_consequences={'switch_on':not h.get('field',{}).get('mansion_switch',False),'per_trainer':True,'source':game_map.events['mansion_switch']['source']}))
 surfing=bool(h.get('status',{}).get('surfing')) and permission(state,h,'SURF')
 direction=h.get('facing','south');dx,dy=DIRECTIONS.get(direction,(0,1));front=(h['x']+dx,h['y']+dy)
 if not surfing and permission(state,h,'SURF') and actor_map(game_map,h,state).is_walkable(*front) and int(game_map.cells.get(front,{}).get('behavior',0)) in WATER:
  out.append(LegalAction(action='surf',arguments={},known_consequences={'arrives_at':list(front),'requires':'Soul Badge and owned non-Egg Pokémon that knows Surf'}))
 if surfing and int(game_map.cells.get((h['x'],h['y']),{}).get('behavior',0)) not in WATER:
  out.append(LegalAction(action='stop_surf',arguments={},known_consequences={'on_foot':True}))
 for obj in objects(game_map,h):
  if (obj['x'],obj['y'])!=front:continue
  if obj['kind']=='tree' and permission(state,h,'CUT'):
   out.append(LegalAction(action='cut',arguments={'object_id':obj['key']},known_consequences={'per_trainer':True}))
  if obj['kind']=='boulder' and permission(state,h,'STRENGTH'):
   landing=(obj['x']+dx,obj['y']+dy)
   if actor_map(game_map,h,state).is_walkable(*landing) or int(game_map.cells.get(landing,{}).get('behavior',0))==0x66:out.append(LegalAction(action='push_boulder',arguments={'object_id':obj['key'],'direction':direction},known_consequences={'arrives_at':list(landing),'per_trainer':True,'switch_story_effects':'source Seafoam falls and Victory Road pressure barriers recorded per trainer'}))
 for door in game_map.events.get('card_key_doors',[]):
  if door['id'] not in h.get('field',{}).get('doors',[]) and abs(h['x']-door['x'])+abs(h['y']-door['y'])<=1:
   from .scenarios import quantity
   if quantity(h,'card_key'):out.append(LegalAction(action='open_card_door',arguments={'door_id':door['id']},known_consequences={'per_trainer':True,'source':door['source']}))
 return out

def elevator_options(maps,h):
 """Destinations parsed from setdynamicwarp in the pinned elevator scripts."""
 current=maps.get(h['map_id'])
 if current is None or not current.display_name.endswith('_Elevator'):return []
 if current.display_name=='RocketHideout_Elevator':
  item=h.get('inventory',{}).get('lift_key',{})
  count=item.get('quantity',0) if isinstance(item,dict) else item
  if not count:return []
 out=[]
 for dest in current.events.get('elevator_destinations',[]):
  target=next((m for m in maps.values() if m.reference_id==dest['map_id']),None)
  if target and target.is_walkable(dest['x'],dest['y']):out.append({'map_id':target.map_id,'x':dest['x'],'y':dest['y'],'source':dest['source']})
 return out


def pressed_switches(game_map,object_id,landing,previous):
 completed=list(previous)
 for switch in game_map.events.get('strength_switches',[]):
  keys={f"{game_map.map_id}:{sid}" for sid in switch.get("object_ids",[switch["object_id"]])}
  if object_id in keys and tuple(landing)==(switch['x'],switch['y']) and switch['id'] not in completed:completed.append(switch['id'])
 return completed


def fallen_boulder(game_map,h,object_id,landing):
 if int(game_map.cells.get(tuple(landing),{}).get('behavior',0))!=0x66:return None
 obj=next((o for o in objects(game_map,h) if o['key']==object_id),None)
 if not obj:return None
 flag=obj.get('reveal_flag');saved=h.get('field',{})
 if not isinstance(flag,str) or not flag.startswith('FLAG_'):return None
 return {'fallen_boulders':list(saved.get('fallen_boulders',[]))+[object_id],'revealed_boulders':list(dict.fromkeys(list(saved.get('revealed_boulders',[]))+[flag]))}
