"""Source object collision: one tile, compatible elevations, reserved moves.

Reference: event_object_movement.c:GetCollisionAtCoords,
DoesObjectCollideWithObjectAt, AreElevationsCompatible. Reservations adapt
current/previous sprite coordinates to atomic shared-clock boundaries.
"""
def compatible_elevations(a,b):return a==0 or b==0 or a==b

def actor_elevation(game_map,h):
    tile=int(game_map.cells.get((h.get('x'),h.get('y')),{}).get('elevation',0))
    return int(h.get('status',{}).get('collision_elevation',0)) if tile==15 else tile

def occupied_tiles(game_map,h,state=None,reservations=(),*,ignore_origin=True):
    out={};own=h.get('human_id');level=actor_elevation(game_map,h);origin=(h.get('x'),h.get('y'))
    aliases={game_map.map_id,game_map.display_name,h.get('map_id')}
    def blocks(p,other_level):
        bank=bool(h.get('status',{}).get('surfing')) and int(game_map.cells.get(p,{}).get('elevation',0))==3
        return compatible_elevations(3 if bank else level,other_level)
    for hid,other in getattr(state,'humans',{}).items():
        if hid==own or other.get('map_id') not in aliases:continue
        p=(other.get('x'),other.get('y'))
        if ignore_origin and p==origin:continue # Existing overlapping saves may step out, never add new overlaps.
        if blocks(p,actor_elevation(game_map,other)):out[p]=hid
    for hid,mid,x,y,elevation in reservations:
        if hid!=own and mid in aliases and blocks((x,y),elevation):out[(x,y)]=hid
    for nid,npc in getattr(state,'npcs',{}).items():
        if npc.get('linked_human') or npc.get('field_managed') or npc.get('map_id') not in aliases:continue
        if not npc.get('appearance',{}).get('sprite'):continue
        flag=npc.get('visibility_flag');flags=h.get('source_npc_flags',{})
        if flag and flags.get(flag):continue
        p=(npc.get('x'),npc.get('y'));elevation=int(npc.get('source_placement',{}).get('elevation',0))
        if blocks(p,elevation) and not(ignore_origin and p==origin):out[p]=nid
    return out


def environmental_tiles(game_map,h,state=None):
    """The same visible source props as the live field-object renderer."""
    acquisition=h.get('acquisition',{});field=h.get('field',{})
    gfx={'OBJ_EVENT_GFX_ITEM_BALL':'item_ball','OBJ_EVENT_GFX_FOSSIL':'fossil','OBJ_EVENT_GFX_ARTICUNO':'articuno','OBJ_EVENT_GFX_ZAPDOS':'zapdos','OBJ_EVENT_GFX_MEWTWO':'mewtwo'}
    level=actor_elevation(game_map,h);out=set()
    for index,obj in enumerate(game_map.events.get('object_events',[])):
        sprite=gfx.get(obj.get('graphics_id'))
        if not sprite:continue
        key=f"{game_map.map_id}:{obj.get('local_id',index)}";script=obj.get('script','');name=game_map.map_id
        if sprite=='fossil' and ((name=='MtMoon_B2F' and acquisition.get('fossil_choice')) or (name=='PewterCity_Museum_1F' and 'old_amber' in acquisition.get('claims',[]))):continue
        if sprite=='item_ball':
            if f'{key}:{script}' in h.get('collected_source_items',[]):continue
            if name=='PowerPlant' and script.endswith(('EventScript_Electrode1','EventScript_Electrode2')) and script.split('_')[-1].lower() in field.get('electrode_cleared',[]):continue
            if name=='CeladonCity_Condominiums_RoofRoom' and 'eevee' in h.get('source_gifts',[]) and 'Eevee' in script:continue
            if name=='SaffronCity_Dojo' and 'dojo_hitmon' in h.get('source_gifts',[]) and ('Hitmonlee' in script or 'Hitmonchan' in script):continue
        if sprite in {'articuno','zapdos','mewtwo'}:
            encounters=getattr(state,'world_facts',{}).get('static_encounters')
            if encounters is None:continue
            claim=encounters.get(sprite)
            if claim and claim.get('status')!='available':continue
        if compatible_elevations(level,int(obj.get('elevation',0))):out.add((obj['x'],obj['y']))
    return out
