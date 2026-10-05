"""Per-trainer mechanical checkpoints, adapted from source guard/door scripts.

No checkpoint impersonates the persistent human guard or invents a victory.
A key is a possession prerequisite; badges remain factual battle records.
"""
from .scenarios import quantity
BADGES={'boulder','cascade','thunder','rainbow','soul','marsh','volcano','earth'}
class AccessDenied(ValueError):pass

def transfer_gate(h,target,state=None):
 current=h['map_id'];progress=h.get('access',{});changes=[];prefix='humans.'+h['human_id']
 if target=='SaffronCity' and current in {'Route5_SouthEntrance','Route6_NorthEntrance','Route7_EastEntrance','Route8_WestEntrance'} and not progress.get('saffron_tea'):
  if not quantity(h,'tea'):raise AccessDenied('Saffron checkpoint requires own Tea; delivery is recorded per trainer')
  inv={k:dict(v) if isinstance(v,dict) else v for k,v in h['inventory'].items()};key=next(k for k in inv if k.upper()=='TEA')
  if isinstance(inv[key],dict):inv[key]['quantity']-=1
  else:inv[key]-=1
  changes += [{'op':'set','path':prefix+'.inventory','value':inv},{'op':'set','path':prefix+'.access.saffron_tea','value':True}]
 if target=='Route17':
  if not quantity(h,'bicycle'):raise AccessDenied('Cycling Road requires this trainer’s Bicycle')
  changes += [{'op':'set','path':prefix+'.status.bicycle','value':True},{'op':'set','path':prefix+'.status.cycling_road','value':True}]
 if target.startswith('SafariZone_') and target!='SafariZone_Entrance' and not h.get('safari',{}).get('active'):
  raise AccessDenied('Safari Zone requires a paid active visit; use admission at its entrance')
 if target.startswith('SSAnne') and not current.startswith('SSAnne') and not quantity(h,'ss_ticket'):
  raise AccessDenied('S.S. Anne entry requires this trainer’s S.S. Ticket')
 if target=='CinnabarIsland_Gym' and not quantity(h,'secret_key'):
  raise AccessDenied('Cinnabar Gym requires this trainer’s Secret Key')
 if target=='PokemonTower_7F' and current=='PokemonTower_6F':
  if not quantity(h,'silph_scope'):raise AccessDenied('Tower ghost requires this trainer’s Silph Scope')
  if not h.get('access',{}).get('tower_marowak_defeated'):raise AccessDenied('Tower summit requires an actual completed victory over its uncatchable Marowak ghost; scenario incomplete')
 if target=='ViridianCity_Gym' and not BADGES.difference({'earth'}).issubset(set(h.get('badges',[]))):
  raise AccessDenied('Repeatable Giovanni challenge opens after this trainer earns the other seven badges')
 if target.startswith('CeruleanCave_') and not current.startswith('CeruleanCave_'):
  history=state.world_facts.get('championship',{}).get('hall_of_fame',[]) if state else []
  if not any(entry.get('champion_id')==h['human_id'] for entry in history):raise AccessDenied('Cerulean Cave requires this trainer’s real Hall of Fame victory; mainland adaptation replaces excluded Sevii Ruby/Sapphire network quest')
 if target=='Route22_NorthEntrance' and 'boulder' not in h.get('badges',[]):raise AccessDenied('League gate requires Boulder Badge')
 if target=='Route23' or target.startswith(('VictoryRoad','IndigoPlateau','PokemonLeague')):
  if not BADGES.issubset(set(h.get('badges',[]))):raise AccessDenied('League journey requires all eight badges for this trainer')
 return changes
