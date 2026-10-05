"""Per-trainer Seafoam transition mechanics from the cartridge scripts.

Movement entries are extracted verbatim into cardinal tile routes; camera,
animation and pauses are omitted, explicitly timed as one second per step.
"""
import copy,re
from pathlib import Path
from .field import WATER
REF=Path(__file__).resolve().parents[3]/'reference/pokefirered'
DIRECTIONS={'up':(0,-1),'down':(0,1),'left':(-1,0),'right':(1,0)}

def _movement(mid,label,start):
 text=(REF/'data/maps'/mid/'scripts.inc').read_text();body=text.split(label+'::',1)[1].split('step_end',1)[0]
 x,y=start;out=[]
 for d in re.findall(r'\bwalk_(?:fast_)?(up|down|left|right)\b',body):
  dx,dy=DIRECTIONS[d];x+=dx;y+=dy;out.append([x,y])
 return out

def transition_effects(maps,h,origin,source_position,destination,landing):
 """Return actor copy + source-script evidence after an exact source warp."""
 actor=copy.deepcopy(h);actor.update(map_id=destination,x=landing[0],y=landing[1]);evidence=[]
 from ..mechanics.escape import remember_escape_entry
 checkpoint=remember_escape_entry(origin.map_id,destination,source_position[0],source_position[1],h.get('facing','south')) if (REF/'data/maps'/origin.map_id/'map.json').exists() and (REF/'data/maps'/destination/'map.json').exists() else None
 if checkpoint:actor.setdefault('field',{})['escape_warp']=checkpoint
 field=actor.setdefault('field',{});revealed=set(field.get('revealed_boulders',[]));stopped=set(field.get('stopped_currents',[]))
 for floor in ['B3F','B4F']:
  if {f'FLAG_HIDE_SEAFOAM_{floor}_BOULDER_1',f'FLAG_HIDE_SEAFOAM_{floor}_BOULDER_2'}<=revealed:stopped.add(floor)
 field['stopped_currents']=sorted(stopped)
 if destination in ('Route16_NorthEntrance_1F','Route18_EastEntrance_1F'):actor.setdefault('status',{})['cycling_road']=False
 if (origin.map_id=='Route16_NorthEntrance_1F' and tuple(source_position)==(1,12)) or (origin.map_id=='Route18_EastEntrance_1F' and tuple(source_position)==(1,6)):
  actor.setdefault('status',{}).update(bicycle=True,cycling_road=True)
  evidence.append({'source':f'data/maps/{destination}/scripts.inc','forced_bicycle':True})
 if maps[destination].events.get('map_type') in {'MAP_TYPE_ROUTE','MAP_TYPE_TOWN','MAP_TYPE_OCEAN_ROUTE','MAP_TYPE_CITY'}:field['flash_active']=False
 if not maps[destination].events.get('allow_cycling',False):actor.setdefault('status',{})['bicycle']=False

 if destination=='Route20':
  reset_floors=[]
  if 'B3F' not in stopped:reset_floors+=['1F','B1F','B2F'];revealed={f for f in revealed if not any(f.startswith('FLAG_HIDE_SEAFOAM_'+floor+'_') for floor in ['B1F','B2F']) and f not in {'FLAG_HIDE_SEAFOAM_B3F_BOULDER_1','FLAG_HIDE_SEAFOAM_B3F_BOULDER_2'}}
  if 'B4F' not in stopped:reset_floors+=['B3F'];revealed={f for f in revealed if not f.startswith('FLAG_HIDE_SEAFOAM_B4F_')}
  reset_maps={'SeafoamIslands_'+f for f in reset_floors}
  field['boulders']={k:v for k,v in field.get('boulders',{}).items() if k.split(':')[0] not in reset_maps}
  field['fallen_boulders']=[k for k in field.get('fallen_boulders',[]) if k.split(':')[0] not in reset_maps or (k.startswith('SeafoamIslands_B3F:') and 'B3F' not in reset_floors)]
  field['revealed_boulders']=sorted(revealed)
  if reset_floors:evidence.append({'source':'data/maps/Route20/scripts.inc','reset_floors':reset_floors})
 falling=int(origin.cells.get(tuple(source_position),{}).get('behavior',0))==0x66
 if falling and destination in ('SeafoamIslands_B3F','SeafoamIslands_B4F') and int(maps[destination].cells.get(tuple(landing),{}).get('behavior',0)) in WATER:
  actor.setdefault('status',{})['surfing']=True;actor['status']['source_forced_surfing']=True
  floor=destination.rsplit('_',1)[1]
  if floor not in stopped:
   cutoff=24 if floor=='B3F' else 9;distance='Far' if landing[0]<cutoff else 'Close';label=f'{destination}_Movement_RideCurrent{distance}'
   steps=_movement(destination,label,landing);evidence.append({'map_id':destination,'steps':steps,'source':f'data/maps/{destination}/scripts.inc','label':label})
   if floor=='B3F':
    actor.update(map_id='SeafoamIslands_B4F',x=27,y=21);steps=_movement('SeafoamIslands_B4F','SeafoamIslands_B4F_Movement_EnterOnCurrent',(27,21));evidence.append({'map_id':'SeafoamIslands_B4F','script_warp':[27,21],'steps':steps,'source':'data/maps/SeafoamIslands_B3F/scripts.inc'});actor.update(x=steps[-1][0],y=steps[-1][1],facing='north')
   else:
    x,y=steps[-1];steps.append([x,y-1]);actor.update(x=x,y=y-1,facing='north');actor['status']['surfing']=False;actor['status']['source_forced_surfing']=False
    evidence[-1]['dismount_source']='src/field_player_avatar.c:SeafoamIslandsB4F_CurrentDumpsPlayerOnLand'
 return actor,evidence

def safe_travel_slice(game_map,steps,limit):
 """A scheduler boundary cannot unlock input midway through forced momentum."""
 count=min(len(steps),limit);spin=False;current=False
 for point in steps[:count]:
  behavior=int(game_map.cells.get(tuple(point),{}).get('behavior',0))
  if 0x54<=behavior<=0x57:spin=True
  elif behavior==0x58:spin=False
  current=0x50<=behavior<=0x53
 while count<len(steps) and (spin or current):
  behavior=int(game_map.cells.get(tuple(steps[count]),{}).get('behavior',0));count+=1
  if behavior==0x58:spin=False
  current=0x50<=behavior<=0x53
 return count
