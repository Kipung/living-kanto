"""Source dungeon escape warps and outdoor Teleport checkpoints."""
import copy,json
from functools import lru_cache
from .reference import REFERENCE
from .item_rules import _consume,ItemError
OUTDOORS={'MAP_TYPE_ROUTE','MAP_TYPE_TOWN','MAP_TYPE_CITY','MAP_TYPE_OCEAN_ROUTE','MAP_TYPE_UNDERWATER'}
@lru_cache(maxsize=512)
def header(map_id):
    return json.loads((REFERENCE/'data/maps'/map_id/'map.json').read_text())

def remember_escape_entry(source_map,dest_map,x,y,facing):
    """UpdateEscapeWarp receives the actual source warp tile, without grid+7."""
    if source_map=='ViridianForest' or header(source_map)['map_type'] not in OUTDOORS or header(dest_map)['map_type'] in OUTDOORS:return None
    return {'map_id':source_map,'x':x,'y':y+(facing!='south'),'source':'src/overworld.c UpdateEscapeWarp'}

@lru_cache(maxsize=1)
def teleport_points():
    rows=json.loads((REFERENCE/'src/data/heal_locations.json').read_text())['heal_locations']
    source_names={json.loads(path.read_text())['id']:path.parent.name for path in (REFERENCE/'data/maps').glob('*/map.json')}
    return {source_names[row['respawn_map']]:{'map_id':source_names[row['map']],'x':row['x'],'y':row['y'],'source':'src/data/heal_locations.json'} for row in rows}

def escape_destination(trainer,kind):
    if trainer.get('battle_id') or trainer.get('safari',{}).get('active'):return None
    if kind in ('ESCAPE_ROPE','DIG'):
        if not header(trainer['map_id']).get('allow_escaping'):return None
        checkpoint=trainer.get('field',{}).get('escape_warp')
        return copy.deepcopy(checkpoint) if checkpoint else None
    if kind=='TELEPORT':
        if header(trainer['map_id'])['map_type'] not in OUTDOORS-{'MAP_TYPE_UNDERWATER'}:return None
        station=trainer.get('last_heal_station')
        return copy.deepcopy(teleport_points().get(station['map_id'])) if station else None
    return None

def use_escape(trainer,kind):
    destination=escape_destination(trainer,kind)
    if not destination:raise ItemError('No legal source escape/checkpoint destination')
    h=copy.deepcopy(trainer)
    if kind=='ESCAPE_ROPE':_consume(h,'ESCAPE_ROPE')
    for key in ('map_id','x','y'):h[key]=destination[key]
    h['active_plan']=None
    for key in ('surfing','source_forced_surfing','bicycle','cycling_road'):h.setdefault('status',{})[key]=False
    h.setdefault('field',{})['flash_active']=False
    h['field']['strength_active']=False
    return h,{'method':kind,'origin_map_id':trainer['map_id'],'destination':destination,'source':'src/item_use.c CanUseEscapeRopeOnCurrMap;src/fldeff_dig.c;src/fldeff_teleport.c'}
