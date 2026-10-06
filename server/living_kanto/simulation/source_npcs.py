"""Pinned mainland source residents, separate from autonomous human population.

Unconditional source objects only. Wandering starts stationary at source origin;
there are no fabricated model decisions or decorative positions.
"""
import copy,json,re,hashlib
OFFICES={'OBJ_EVENT_GFX_BROCK','OBJ_EVENT_GFX_MISTY','OBJ_EVENT_GFX_LT_SURGE','OBJ_EVENT_GFX_ERIKA','OBJ_EVENT_GFX_KOGA','OBJ_EVENT_GFX_SABRINA','OBJ_EVENT_GFX_BLAINE','OBJ_EVENT_GFX_GIOVANNI','OBJ_EVENT_GFX_LORELEI','OBJ_EVENT_GFX_BRUNO','OBJ_EVENT_GFX_AGATHA','OBJ_EVENT_GFX_LANCE','OBJ_EVENT_GFX_BLUE','OBJ_EVENT_GFX_PROF_OAK'}
def initial_actors(engine,humans):
    manifest=json.loads((engine.content_root/'source_npcs.json').read_text())
    service={(h.get('service_assignment',{}).get('map_id'),h.get('service_assignment',{}).get('kind')) for h in humans.values() if h.get('service_assignment')}
    result={}
    for actor in manifest['actors']:
        mid=actor['map_id']; gfx=actor['graphics_id']; script=actor.get('source_script','') or ''
        if gfx in OFFICES:continue
        if gfx=='OBJ_EVENT_GFX_NURSE' and (mid,'healing') in service:continue
        if gfx=='OBJ_EVENT_GFX_CLERK' and ((mid,'shop') in service or any(h.get('workplace',{}).get('map_id')==mid and h.get('workplace',{}).get('kind')=='shop' for h in humans.values())):continue
        if mid=='MtMoon_B2F' and script.endswith('_Miguel') and any(h.get('source_office')=='fossil_researcher' for h in humans.values()):continue
        if mid=='SaffronCity_Dojo' and 'Koichi' in script and any(h.get('source_office')=='dojo_master' for h in humans.values()):continue
        key=actor['key']; npc_id='source-npc-'+hashlib.sha256(key.encode()).hexdigest()[:24]
        label=script.split('_EventScript_')[-1] if '_EventScript_' in script else actor['sprite']
        name=re.sub(r'(?<=[a-z])(?=[A-Z])',' ',label).replace('_',' ').strip() or 'Local resident'
        result[npc_id]={'npc_id':npc_id,'name':name,'key':key,'map_id':mid,'x':actor['x'],'y':actor['y'],'facing':actor['facing'],'appearance':{'sprite':actor['sprite']},'kind':'source_resident','linked_human':None,'source_placement':{'x':actor['x'],'y':actor['y'],'elevation':actor.get('elevation',0)},'source':copy.deepcopy(actor),'source_kind':'source_npc','moving':False,'dialogue':copy.deepcopy(actor.get('dialogue'))}
    return result

def visible_actors(state,map_id):
    return [copy.deepcopy(npc) for npc in state.npcs.values() if npc.get('kind')=='source_resident' and npc.get('map_id')==map_id and not npc.get('linked_human')]


def courtesy_plan(engine,state,human_id,npc_id):
    """A source resident yields on lawful floor, or swaps with an adjacent walker.

    Explicit shared-world courtesy, never an autonomous person's decision. Source
    people do not enter doors, water, other people, or environmental objects.
    """
    from .collision import occupied_tiles,environmental_tiles,compatible_elevations,actor_elevation
    h=state.humans[human_id];npc=state.npcs.get(npc_id)
    if not npc or npc.get('kind')!='source_resident' or npc.get('linked_human') or npc['map_id']!=h['map_id']:return None
    if npc.get('source',{}).get('graphics_id') in {'OBJ_EVENT_GFX_NURSE','OBJ_EVENT_GFX_CLERK','OBJ_EVENT_GFX_CABLE_CLUB_RECEPTIONIST'}:return None
    origin=(h['x'],h['y']);start=(npc['x'],npc['y'])
    if abs(origin[0]-start[0])+abs(origin[1]-start[1])!=1:return None
    if any(other_id!=human_id and other.get('map_id')==h['map_id'] and (other.get('x'),other.get('y'))==start for other_id,other in state.humans.items()):return None
    gm=engine.maps[h['map_id']]
    walker={'human_id':human_id,'map_id':h['map_id'],'x':npc['x'],'y':npc['y']}
    level=int(npc.get('source_placement',{}).get('elevation',0))
    if not compatible_elevations(actor_elevation(gm,h),level):return None
    blocked=occupied_tiles(gm,walker,state,ignore_origin=True)
    # Own human is excluded by human_id; reserve its current tile for exchange.
    blocked.update({p:'environment' for p in environmental_tiles(gm,walker,state)})
    from .field import objects as field_objects
    # Shared residents conservatively avoid original prop positions, including
    # props cleared only in one trainer's private field state.
    for person in [{},h]:
        blocked.update({(obj['x'],obj['y']):'field_object' for obj in field_objects(gm,person)})
    directions={'north':(0,-1),'south':(0,1),'east':(1,0),'west':(-1,0)}
    home=npc.get('source_placement',{})
    home_position=(home.get('x',start[0]),home.get('y',start[1]))
    def legal_floor(p,direction):
        # Courtesy is a small local yield, never progressive drift from the source location.
        if abs(p[0]-home_position[0])+abs(p[1]-home_position[1])>1:return False
        path=gm.step_path(start,direction,elevation=level)
        return path==[p] and p not in gm.exits and p not in blocked and int(gm.cells.get(p,{}).get('behavior',0)) not in {0x10,0x11,0x12,0x13,0x15,0x1A,0x1B,0x50,0x51,0x52,0x53}
    for direction,(dx,dy) in directions.items():
        # Yield perpendicular to the approach; moving along the lane merely
        # moves a permanent blockage further down the same corridor.
        if (origin[0]!=start[0] and dx!=0) or (origin[1]!=start[1] and dy!=0):continue
        dest=(start[0]+dx,start[1]+dy)
        if dest!=origin and legal_floor(dest,direction):
            return {'npc_id':npc_id,'npc_from':list(start),'npc_to':list(dest),'npc_facing':direction,'human_from':list(origin),'human_to':list(origin),'kind':'step_aside'}
    # In a one-tile corridor, exchanging adjacent tiles allows passage without
    # passing through or overlapping either actor at a committed boundary.
    to_human=next((d for d,(dx,dy) in directions.items() if (start[0]+dx,start[1]+dy)==origin),None)
    to_npc=next((d for d,(dx,dy) in directions.items() if (origin[0]+dx,origin[1]+dy)==start),None)
    if start in gm.exits or origin in gm.exits or not legal_floor(origin,to_human):return None
    if gm.step_path(origin,to_npc,surfing=bool(h.get('status',{}).get('surfing')))!=[start]:return None
    other=occupied_tiles(gm,h,state,ignore_origin=True)
    if other.get(start)!=npc_id:return None
    if start in environmental_tiles(gm,h,state):return None
    return {'npc_id':npc_id,'npc_from':list(start),'npc_to':list(origin),'npc_facing':to_human,'human_from':list(origin),'human_to':list(start),'human_facing':to_npc,'kind':'exchange_tiles'}


def courtesy_actions(engine,state,human_id):
    from ..contracts.human import LegalAction
    result=[]
    h=state.humans[human_id]
    for npc in visible_actors(state,h['map_id']):
        plan=courtesy_plan(engine,state,human_id,npc['npc_id'])
        if plan:result.append(LegalAction(action='ask_resident_to_make_way',arguments={'npc_id':npc['npc_id']},known_consequences={'source_resident_courtesy':True,'passage':plan['kind'],'duration_seconds':1}))
    return result


def courtesy_changes(engine,state,human_id,arguments):
    from .engine import EngineError
    if set(arguments)!={'npc_id'}:raise EngineError('Courtesy requires one source resident')
    plan=courtesy_plan(engine,state,human_id,arguments['npc_id'])
    if not plan:raise EngineError('Source resident cannot safely give way')
    nid=plan['npc_id'];x,y=plan['npc_to']
    changes=[{'op':'set','path':f'npcs.{nid}.{key}','value':value} for key,value in {'x':x,'y':y,'facing':plan['npc_facing']}.items()]
    if plan['human_to']!=plan['human_from']:
        x,y=plan['human_to']
        changes.extend({'op':'set','path':f'humans.{human_id}.{key}','value':value} for key,value in {'x':x,'y':y,'facing':plan['human_facing']}.items())
    changes.append({'op':'set','path':f'npcs.{nid}.last_courtesy','value':dict(plan,time=state.simulated_time,human_id=human_id)})
    return changes,plan
