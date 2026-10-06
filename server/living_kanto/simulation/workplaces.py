"""Declared workplaces and coverage constraints; humans still choose every action.

A sole service worker remains responsible for coverage. Relief permits outings.
Officeholders have an eight-hour duty period in a twelve-hour simulation day.
Homes are declared bases, not invented residential buildings.
"""
import copy
import json
from ..contracts.human import LegalAction

OFFICE_ROLES = {'gym_leader', 'elite_four', 'initial_champion', 'professor'}
POLICY = 'workplaces-v2-counter-posts'


def assignments(engine, humans):
    source = {h['human_id']: h for h in json.loads((engine.content_root / 'population.json').read_text())['humans']}
    result = {}
    used_posts = {}
    for hid, h in sorted(humans.items()):
        station = h.get('service_assignment')
        if station:
            mid, kind = station['map_id'], station['kind']
        elif h.get('role') in OFFICE_ROLES:
            mid, kind = source.get(hid, {}).get('map_id'), 'office'
        elif h.get('source_office') == 'dojo_master':
            mid, kind = 'SaffronCity_Dojo', 'office'
        else:
            continue
        if mid not in engine.maps:
            continue
        gm = engine.maps[mid]
        objects = gm.events.get('object_events', [])
        anchor = next((o for o in objects if kind == 'healing' and o.get('graphics_id') == 'OBJ_EVENT_GFX_NURSE'
                       or kind == 'shop' and 'Shop' in o.get('script', '')), None)
        near = (anchor['x'], anchor['y']) if anchor else (h['x'], h['y']) if h['map_id'] == mid else (5, 5)
        x, y = gm.first_open_cell(near)
        post = None
        if anchor and kind == 'healing':
            # Source nurse stands on a real floor tile in an enclosed counter bay.
            cells = [(anchor['x'], anchor['y']), (anchor['x'] + 1, anchor['y'])]
            used = used_posts.setdefault(mid, set())
            post = next((cell for cell in cells if gm.can_stand(*cell) and cell not in used), None)
            if post:
                used.add(post); x, y = post
        result[hid] = {'map_id': mid, 'x': x, 'y': y, 'kind': kind, 'source': 'declared_workplace', 'policy': POLICY}
        if post:
            result[hid]['service_post'] = {'x': x, 'y': y, 'facing': 'south',
                'customer_side': {'x': anchor['x'], 'y': anchor['y'] + 2},
                'source_object': anchor.get('local_id', anchor.get('script'))}
    return result


def initialize(engine, humans):
    for hid, workplace in assignments(engine, humans).items():
        h = humans[hid]
        h['workplace'] = workplace
        h['home_location'] = {'map_id': workplace['map_id'], 'source': 'declared_base'}
        h.update({key: workplace[key] for key in ('map_id', 'x', 'y')})
        if workplace.get('service_post'): h['facing'] = 'south'


def at_service_post(h):
    post = (h.get('workplace') or {}).get('service_post')
    return not post or (h['map_id'] == h['workplace']['map_id'] and (h['x'], h['y']) == (post['x'], post['y']))


def post_action(engine, state, hid, entering):
    h = state.humans[hid]; w = h.get('workplace') or {}; post = w.get('service_post')
    if not post or h['map_id'] != w['map_id']: return None
    if entering == at_service_post(h): return None
    if not entering and duty_info(state, hid)['on_duty']: return None
    side = post['customer_side']; destination = post if entering else side
    # Taking the enclosed post is a staff-only counter passage, not general teleportation.
    if entering and abs(h['x']-side['x']) + abs(h['y']-side['y']) > 1: return None
    from .field import actor_map
    if not actor_map(engine.maps[h['map_id']], h, state).can_stand(destination['x'], destination['y']): return None
    return LegalAction(action='take_service_post' if entering else 'leave_service_post', arguments={},
        known_consequences={'arrives_at':[destination['x'],destination['y']], 'duration_seconds':5,
                            'staff_counter_passage':True, 'returns_to_counter':entering})


def post_changes(engine, state, hid, action, args):
    from .engine import EngineError
    option = post_action(engine, state, hid, action == 'take_service_post')
    if args or not option: raise EngineError('Service counter passage unavailable')
    x,y = option.known_consequences['arrives_at']
    return [{'op':'set','path':f'humans.{hid}.{key}','value':value}
            for key,value in {'x':x,'y':y,'facing':'south'}.items()]


def coverage(state, hid):
    h = state.humans[hid]
    station = h.get('service_assignment')
    if not station:
        return []
    return [other for other, worker in state.humans.items() if other != hid
            and worker.get('role') in {'service_staff', 'shop_staff'}
            and worker.get('ready_at', 0) <= state.simulated_time
            and worker.get('service_assignment') == station and worker.get('map_id') == station['map_id']
            and not worker.get('battle_id') and not worker.get('service_request')
            and not worker.get('movement_intent') and not worker.get('activity') and at_service_post(worker)]


def duty_info(state, hid):
    h = state.humans[hid]
    workplace = h.get('workplace')
    if not workplace:
        return {}
    service = bool(h.get('service_assignment'))
    at_workplace = h['map_id'] == workplace['map_id']
    # Remote colleagues' current whereabouts/activity are not private knowledge.
    relief = coverage(state, hid) if service and at_workplace else []
    on_duty = (not at_workplace or not relief) if service else state.simulated_time % 43200 < 28800
    return {'workplace': copy.deepcopy(workplace), 'home_location': copy.deepcopy(h.get('home_location')),
            'on_duty': on_duty, 'at_workplace': h['map_id'] == workplace['map_id'],
            'at_service_post': at_service_post(h), 'covering_staff': relief, 'responsibility': 'Serve waiting customers from your assigned counter post; remain at the post while on duty. Rest and socialize here. Return to the post when duty resumes.'}


def actions(engine, state, hid, acts, include_routes):
    h = state.humans[hid]
    info = duty_info(state, hid)
    if not info:
        return acts
    mid = info['workplace']['map_id']
    if h['map_id'] != mid:
        acts = [a for a in acts if a.action != 'work' and (not info['on_duty'] or a.action not in {'journey_to', 'fly_to'} or a.arguments.get('map_id') == mid)]
        if include_routes and not any(a.action == 'journey_to' and a.arguments.get('map_id') == mid for a in acts):
            from .routeplanner import plan_journey, JourneyUnavailable
            try:
                route = plan_journey(engine.maps, h, mid, state=state, max_nodes=48, max_tiles=1000)
                acts.insert(0, LegalAction(action='journey_to', arguments={'map_id': mid},
                    known_consequences={'destination_kind': 'workplace', 'engine_owned_route': True,
                                        'duration_seconds': sum(len(s['steps']) + 1 for s in route), 'may_interrupt': True}))
            except JourneyUnavailable:
                pass
    elif info['on_duty']:
        acts = [a for a in acts if a.action not in {'enter_map', 'journey_to', 'fly_to', 'ride_elevator'}]
    if info['on_duty']:
        for a in acts:
            if a.action == 'work' and h.get('service_assignment'):
                # Long generic work must not make the sole nurse unavailable.
                acts = [x for x in acts if x.action != 'work']
                break
    post = info['workplace'].get('service_post')
    if post and h['map_id'] == mid:
        if info['on_duty'] and at_service_post(h):
            acts = [a for a in acts if a.action not in {'walk_to','travel_to','journey_to','fly_to','enter_map','ride_elevator','turn_to'} or a.action=='turn_to' and a.arguments.get('direction')=='south']
        for entering in (True,False):
            option = post_action(engine,state,hid,entering)
            if option: acts.insert(0,option)
        if info['on_duty'] and not at_service_post(h) and include_routes:
            from .field import actor_map
            from .pathfinding import shortest_path, PathNotFound
            side = post['customer_side']; target=(side['x'],side['y'])
            try: path = shortest_path(actor_map(engine.maps[mid],h,state),(h['x'],h['y']),target)
            except PathNotFound: path = None
            if path:
                acts.insert(0, LegalAction(action='travel_to',arguments={'x':target[0],'y':target[1]},
                    known_consequences={'destination_kind':'workplace','duration_seconds':len(path),'returns_to_counter':True}))
    # Serving and returning home must remain visible through the menu cap.
    acts.sort(key=lambda a: 0 if a.action in {'serve_customer','take_service_post'} or a.known_consequences.get('destination_kind') == 'workplace' else 1)
    return acts


def migration_changes(engine, state):
    """One explicit user intervention; busy people return through model choices."""
    changes = []
    relocated = []
    homes = assignments(engine, state.humans)
    preview = copy.deepcopy(state.humans)
    for hid, workplace in homes.items():
        h = preview[hid]
        h['workplace'] = workplace
        h['home_location'] = {'map_id': workplace['map_id'], 'source': 'declared_base'}
        busy = any(h.get(key) for key in ('battle_id', 'service_request', 'activity', 'movement_intent', 'active_plan')) or h.get('ready_at', 0) > state.simulated_time or h.get('status', {}).get('surfing', False)
        if not busy and (h['map_id'] != workplace['map_id'] or workplace.get('service_post') and ((h['x'],h['y']) != (workplace['x'],workplace['y']) or h.get('facing')!='south')):
            h.update({key: workplace[key] for key in ('map_id', 'x', 'y')})
            relocated.append(hid)
    # Reuse validated distinct floor placement only for relocated staff.
    # Existing people keep their exact locations and ongoing activities.
    from .field import actor_map, WATER
    occupied = {(h['map_id'], h['x'], h['y']) for hid, h in preview.items() if hid not in relocated}
    for hid in relocated:
        h = preview[hid]; gm = actor_map(engine.maps[h['map_id']], h, state)
        if h['workplace'].get('service_post'):
            target=(h['map_id'],h['x'],h['y'])
            if target in occupied: raise ValueError('Occupied nurse counter post for ' + hid)
            occupied.add(target); h['facing']='south'; continue
        candidates = [(abs(x-h['x'])+abs(y-h['y']), y, x) for y in range(gm.height) for x in range(gm.width)
                      if (h['map_id'], x, y) not in occupied and gm.can_stand(x, y)
                      and (x, y) not in gm.exits and int(gm.cells.get((x,y), {}).get('behavior',0)) not in WATER]
        if not candidates:
            raise ValueError('No safe workplace placement for ' + hid)
        _, h['y'], h['x'] = min(candidates)
        occupied.add((h['map_id'], h['x'], h['y']))
    for hid in homes:
        for key in ('workplace', 'home_location') + (('map_id', 'x', 'y', 'facing') if hid in relocated else ()):
            if state.humans[hid].get(key) != preview[hid][key]:
                changes.append({'op':'set', 'path':f'humans.{hid}.{key}', 'value':preview[hid][key]})
    changes.append({'op':'set', 'path':'world_facts.creative_modified', 'value':True})
    changes.append({'op':'set', 'path':'world_facts.last_intervention', 'value':{'author':'workplace-update', 'kind':'workplace_migration', 'human_ids':sorted(homes), 'relocated':relocated}})
    changes.append({'op':'set', 'path':'world_facts.workplace_policy', 'value':{'version':POLICY, 'relocated':relocated, 'applied_at':state.simulated_time}})
    return changes


def build_migration_event(engine, before, head):
    from ..contracts import CanonicalEvent, StateUpdate
    from ..contracts.base import content_hash
    changes = migration_changes(engine, before)
    after = before.with_advanced_version(changes)
    idx = before.state_version
    eid = f'evt-{idx}-{content_hash(changes)[:24]}'
    update = StateUpdate(run_id=before.run_id, event_id=eid, event_index=idx, prior_state_version=idx,
        prior_state_hash=before.state_hash, previous_head=head, state_version=after.state_version,
        state_hash=after.state_hash, changes=changes).validate()
    def values(snapshot):
        result = {}
        saved = snapshot.to_dict()
        for change in changes:
            parts = change['path'].split('.')
            value = saved
            for part in parts:
                value = value.get(part) if isinstance(value, dict) else None
            result[change['path']] = value
        return result
    people = sorted({c['path'].split('.')[1] for c in changes if c['path'].startswith('humans.')})
    event = CanonicalEvent(run_id=before.run_id, event_id=eid, event_index=idx, state_version=after.state_version,
        previous_head=head, event_kind='intervention.applied', tick=after.tick, simulated_time=after.simulated_time,
        real_wall_time=engine._wall_time(),
        causation={'human_id':'user','decision_explanation':'User authorized declared workplaces and service coverage; preserve ongoing activities and history',
                   'provenance':{'kind':'user','author':'workplace-update'}},
        affected=[{'human_id':hid} for hid in people], before=values(before), after=values(after),
        deterministic_inputs={'workplace_policy':POLICY},
        transaction={'kind':'state_update', **update.to_dict()}, visibility={'public':True}).validate()
    return event, after
