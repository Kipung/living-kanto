"""Lawful public gift-station approaches for people without owned Pokemon."""
from ..contracts import LegalAction
from ..mechanics.source_gifts import gift_templates
from .routeplanner import plan_journey, JourneyUnavailable
from .field import actor_map, permission
from .pathfinding import shortest_path, PathNotFound


def route_actions(engine, state, hid, offered, include_routes=True):
    h=state.humans[hid]
    if not include_routes or h.get('party') or h.get('box') or h.get('battle_id'):
        return []
    # Existing starter access already supplies a first-Pokemon path. Keep the
    # alternative search bounded instead of filling the menu with distant gifts.
    if any(a.action=='journey_to' and a.known_consequences.get('destination_kind')=='starter' for a in offered):
        return []
    claimed=set(h.get('source_gifts',[]));result=[];cache={}
    for gift in gift_templates().values():
        if gift['claim_group'] in claimed or gift.get('requires_dojo_win') and not h.get('access',{}).get('dojo_master_defeated'):
            continue
        consequences={'destination_kind':'pokemon_source','gift_id':gift['gift_id'],'species':gift['species'],
            'separate_action_required':'receive_source_gift','arrival_does_not_grant_pokemon':True}
        if h['map_id']==gift['map_id']:
            radius=1 if engine.maps[h['map_id']].events.get('requires_flash') and not h.get('field',{}).get('flash_active') else 6
            if abs(gift['x']-h['x'])>radius or abs(gift['y']-h['y'])>radius:continue
            if any(a.action=='receive_source_gift' and a.arguments.get('gift_id')==gift['gift_id'] for a in offered):continue
            gm=actor_map(engine.maps[h['map_id']],h,state)
            candidates=[]
            for dx,dy in ((0,1),(1,0),(0,-1),(-1,0)):
                point=(gift['x']+dx,gift['y']+dy)
                try:path=shortest_path(gm,(h['x'],h['y']),point,surfing=bool(h.get('status',{}).get('surfing')) and (permission(state,h,'SURF') or h.get('status',{}).get('source_forced_surfing')))
                except PathNotFound:continue
                if path:candidates.append((len(path),point))
            if candidates:
                length,point=min(candidates)
                result.append(LegalAction(action='travel_to',arguments={'x':point[0],'y':point[1]},
                    known_consequences={**consequences,'changes_map':False,'map_id':h['map_id'],'arrives_at':list(point),'route_length':length}))
        else:
            try:journey=plan_journey(engine.maps,h,gift['map_id'],state=state,max_nodes=256,max_tiles=1000,path_cache=cache)
            except JourneyUnavailable:continue
            result.append(LegalAction(action='journey_to',arguments={'map_id':gift['map_id']},
                known_consequences={**consequences,'engine_owned_route':True,'changes_map':True,'destination_map':gift['map_id'],
                    'arrives_at':journey[-1]['destination'],'maps_crossed':len(journey),'may_interrupt':True}))
        if result:break
    return result
