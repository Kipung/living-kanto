"""Repeatable per-trainer environmental stations, explicitly adapted from gifts.

Stations replace cartridge NPC gift scripts rather than impersonating AI humans.
They require physical source-location proximity and recorded prerequisites.
No station produces a battle victory, badge, or championship outcome.
"""
import copy,json
from functools import lru_cache
from pathlib import Path
from ..contracts.human import LegalAction
class ScenarioError(ValueError):pass
@lru_cache(maxsize=1)
def definitions():return json.loads((Path(__file__).resolve().parents[3]/'content/scenarios.json').read_text())['scenarios']
def quantity(h,item):
 inventory=h.get('inventory',{});key=next((k for k in inventory if k.upper()==item.upper()),item);e=inventory.get(key,{});return e.get('quantity',0) if isinstance(e,dict) else int(e or 0)
def eligible(h,row):
 if h['map_id']!=row['map_id']:return False
 if row['id']=='safari_surf' and not h.get('safari',{}).get('active'):return False
 if abs(h['x']-row['x'])+abs(h['y']-row['y'])>1:return False
 if row['id'] in h.get('scenarios',{}).get('completed',[]):return False
 for item in row.get('required_items',[]):
  if quantity(h,item)<=0:return False
 for access in row.get('required_access',[]):
  if not h.get('access',{}).get(access):return False
 for achievement in row.get('required_scenarios',[]):
  if achievement not in h.get('scenarios',{}).get('completed',[]):return False
 if len({str(s).upper().replace(' ','_').replace('-','_') for s in h.get('pokedex',[])})<row.get('caught_species',0):return False
 return True

def scenario_actions(state,h,maps):
 return [LegalAction(action='use_scenario',arguments={'scenario_id':row['id']},known_consequences={'reward':row.get('reward'),'consumes':row.get('consumes',[]),'duration_seconds':row['duration_seconds'],'adaptation':row['adaptation']}) for row in definitions() if eligible(h,row)]

def scenario_effects(state,h,maps,args):
 if set(args)!={'scenario_id'}:raise ScenarioError('use_scenario requires scenario_id')
 row=next((r for r in definitions() if r['id']==args['scenario_id']),None)
 if row is None or not eligible(h,row):raise ScenarioError('scenario unavailable: source location, prerequisites, or prior completion')
 inventory=copy.deepcopy(h.get('inventory',{}))
 for item in row.get('consumes',[]):
  key=next(k for k in inventory if k.upper()==item.upper());entry=inventory[key]
  if isinstance(entry,dict):entry['quantity']-=1
  else:inventory[key]=entry-1
 if row.get('reward'):
  item=row['reward'];entry=inventory.get(item,{'item_id':item,'quantity':0})
  if isinstance(entry,dict):entry['quantity']+=1
  else:entry={'item_id':item,'quantity':entry+1}
  inventory[item]=entry
 completed=list(h.get('scenarios',{}).get('completed',[]))+[row['id']];prefix='humans.'+h['human_id']
 return {'changes':[{'op':'set','path':prefix+'.inventory','value':inventory},{'op':'set','path':prefix+'.scenarios.completed','value':completed}], 'duration':row['duration_seconds'],'source':row['source'],'adaptation':row['adaptation'],'scenario_id':row['id']}
