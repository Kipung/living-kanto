"""Engine-owned geographic journeys over directed tiles and exact source exits.

Uses public map geography only. Never supplies goals, private people, items,
field-move permissions or badges. Locked checkpoints and unsupported dynamic
warps are unavailable edges. Search is bounded and reports an unresolved route.
"""
import copy,heapq
from itertools import count
from .field_scripts import transition_effects
from .maps import resolve_transfer,MapLoadError
from .field import actor_map,permission,WATER
from .pathfinding import ReachabilityTree,PathNotFound
from ..contracts.base import content_hash
from .access import transfer_gate,AccessDenied
class JourneyUnavailable(ValueError):pass

# Route simulation never consults identity, social history, or past decisions.
# Exclude only known irrelevant fields; retain unknown future mechanical fields.
_ROUTING_IRRELEVANT=frozenset({
 'ambitions','appearance','biography','decision_history','goal','goals',
 'interests','last_decision','memories','memory_summary','model_provenance',
 'name','personality','preferences','relationships','responsibilities',
 'role','setup_role','setup_status',
})

def _routing_actor(h):
 return {key:value for key,value in h.items() if key not in _ROUTING_IRRELEVANT}


def _apply(h,changes):
 for c in changes:
  parts=c['path'].split('.')[2:];obj=h
  for part in parts[:-1]:obj=obj.setdefault(part,{})
  obj[parts[-1]]=copy.deepcopy(c['value'])

def plan_journey(maps,h,destination_map,*,state=None,max_nodes=256,max_tiles=10000,path_cache=None):
 if path_cache is None:path_cache={}
 if destination_map not in maps:raise JourneyUnavailable('destination is not a known available map')
 if h['map_id']==destination_map:raise JourneyUnavailable('already in destination map')
 sequence=count();start=(h['map_id'],int(h['x']),int(h['y']),bool(h.get('status',{}).get('surfing')),bool(h.get('access',{}).get('saffron_tea')));queue=[(0,next(sequence),start,copy.deepcopy(_routing_actor(h)),[])];best={start:0};expanded=0
 while queue and expanded<max_nodes:
  distance,_,node,actor,route=heapq.heappop(queue)
  if best.get(node)!=distance:continue
  mid,x,y,*_=node
  if mid==destination_map:return route
  expanded+=1;game_map=actor_map(maps[mid],actor);surfing=bool(actor.get('status',{}).get('surfing')) and state is not None and (permission(state,actor,'SURF') or actor.get('status',{}).get('source_forced_surfing',False))
  # Try the closest few real edge/door tiles for each destination, rather than
  # every boundary tile. Disconnected entrances remain separate search nodes.
  grouped={}
  for point,target in game_map.exits.items():
   if target in maps:grouped.setdefault(target,[]).append(point)
  # The actor is unchanged while examining this node's outgoing edges.
  # Hash it once, rather than repeatedly serializing its private history.
  cache_key=(mid,x,y,surfing,content_hash(actor))
  for target,points in sorted(grouped.items()):
   for point in sorted(points,key=lambda p:(abs(p[0]-x)+abs(p[1]-y),p))[:4]:
    try:
     tree=path_cache.get(cache_key)
     if tree is None:
      tree=ReachabilityTree(game_map,(x,y),surfing=surfing);path_cache[cache_key]=tree
     path=tree.path_to(point)
     after=copy.deepcopy(actor)
     # An intention loses surfing when its tile path reaches land.
     remained=surfing and all(int(game_map.cells.get(p,{}).get('behavior',0)) in WATER for p in path)
     if surfing and not remained:after.setdefault('status',{})['surfing']=False
     dst,nx,ny=resolve_transfer(maps,game_map,*point,target,surfing=remained or int(game_map.cells.get(point,{}).get("behavior",0))==0x66)
     checkpoint=transfer_gate(after,dst,state);_apply(after,checkpoint)
     after,script_steps=transition_effects(maps,after,game_map,point,dst,(nx,ny))
     dst,nx,ny=after["map_id"],after["x"],after["y"]
     if int(maps[dst].cells.get((nx,ny),{}).get("behavior",0)) not in WATER:after.setdefault("status",{})["surfing"]=False
     if not actor_map(maps[dst],after).is_walkable(nx,ny):continue
    except (PathNotFound,MapLoadError,AccessDenied):continue
    cost=distance+len(path)+1+sum(len(s.get("steps",[])) for s in script_steps);next_node=(dst,nx,ny,bool(after.get("status",{}).get("surfing")),bool(after.get("access",{}).get("saffron_tea")))
    if cost>max_tiles or cost>=best.get(next_node,float('inf')):continue
    best[next_node]=cost
    segment={'map_id':mid,'start':[x,y],'steps':[list(p) for p in path],'source_exit':list(point),'destination_map':dst,'destination':[nx,ny],'checkpoint_changes':checkpoint,'script_steps':script_steps,'field_after':after.get('field',{}),'status_after':after.get('status',{}),'surfing_after':bool(after.get('status',{}).get('surfing'))}
    heapq.heappush(queue,(cost,next(sequence),next_node,after,route+[segment]))
 raise JourneyUnavailable('no legal source-backed journey found within bounded search; locked, unsupported or disconnected terrain may block it')

def public_destinations(maps,current):
 """Nearby cities/services/gyms from static topology; no private state."""
 graph={mid:{t for t in m.exits.values() if t in maps} for mid,m in maps.items()};todo=[current];seen={current};out=[]
 while todo and len(out)<5:
  mid=todo.pop(0)
  if mid!=current and (mid.endswith(('_PokemonCenter_1F','_Gym','_ProfessorOaksLab')) or '_' not in mid and ('City' in mid or 'Town' in mid)):out.append(mid)
  for target in sorted(graph.get(mid,())):
   if target not in seen:seen.add(target);todo.append(target)
 return out
