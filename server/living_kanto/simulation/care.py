"""Factual care and service-duty context; intentions remain human choices.

Routes use public geography and the normal permission/collision-aware planner.
No observation, route suggestion, or duty statement changes canonical state.
"""
from collections import deque
from ..contracts.human import LegalAction
from .routeplanner import plan_journey, JourneyUnavailable


def _condition(party):
    rows = []
    for mon in party:
        if mon.get('is_egg'):
            continue
        maximum = mon.get('stats', {}).get('hp', mon.get('max_hp', mon.get('hp', 0)))
        hp = mon.get('hp', 0)
        depleted = [slot.get('move') for slot in mon.get('moves', [])
                    if slot.get('pp', 0) < slot.get('max_pp', slot.get('pp', 0))]
        rows.append({'pokemon_id': mon.get('pokemon_id'), 'hp': hp, 'max_hp': maximum,
                     'fainted': hp <= 0, 'injured': hp < maximum,
                     'status': mon.get('status') or '', 'depleted_pp_moves': depleted})
    return {'needs_care': any(row['injured'] or row['fainted'] or row['status'] or row['depleted_pp_moves'] for row in rows),
            'party_members': rows, 'fainted_count': sum(row['fainted'] for row in rows),
            'injured_count': sum(row['injured'] for row in rows),
            'status_count': sum(bool(row['status']) for row in rows),
            'pp_depleted_count': sum(bool(row['depleted_pp_moves']) for row in rows)}


def _available(h, now):
    return not any(h.get(key) for key in ('battle_id', 'service_request', 'activity', 'movement_intent')) and h.get('ready_at', 0) <= now


def observation_view(engine, state, hid, party, legal_actions):
    """Own condition and duties plus observable local service aggregates only."""
    h = state.humans[hid]
    result = _condition(party)
    result['heal_option_visible'] = any(a.action == 'heal_party' for a in legal_actions)
    result['healing_routes_visible'] = [a.arguments['map_id'] for a in legal_actions
        if a.action == 'journey_to' and engine.service_kind(a.arguments.get('map_id', '')) == 'healing']
    assignment = h.get('service_assignment')
    if assignment:
        at_station = h['map_id'] == assignment['map_id']
        result['service_duty'] = {'kind': assignment['kind'], 'map_id': assignment['map_id'],
            'at_assigned_station': at_station, 'serve_option_visible': any(a.action == 'serve_customer' for a in legal_actions),
            'responsibility': 'Serve waiting customers at your assigned station. Return there to provide the service.',
            'source': 'own_service_assignment'}
        if at_station:
            result['service_duty']['waiting_customers'] = len(engine.service_queue(state, h['map_id']))
    if engine.service_kind(h['map_id']) == 'healing':
        queue = engine.service_queue(state, h['map_id'])
        staff = [other for other in state.humans.values() if other.get('map_id') == h['map_id']
            and (other.get('role') == 'service_staff' or other.get('role') in ('service_staff', 'shop_staff')
                 and other.get('service_assignment', {}).get('kind') == 'healing'
                 and other.get('service_assignment', {}).get('map_id') == h['map_id'])]
        position = next((index + 1 for index, request in enumerate(queue) if request['human_id'] == hid), None)
        result['local_center'] = {'map_id': h['map_id'], 'waiting_customers': len(queue),
            'own_queue_position': position, 'local_staff_count': len(staff),
            'ready_staff_count': sum(_available(worker, state.simulated_time) for worker in staff),
            'service_requires_staff_choice': True}
    return result


def _centers(maps, origin):
    # Bounded public topology discovery. Directed exits do not establish that
    # the actor may cross them; plan_journey performs that separate validation.
    todo = deque([origin]); seen = {origin}; centers = []
    while todo and len(seen) <= 256 and len(centers) < 32:
        mid = todo.popleft()
        if mid != origin and 'PokemonCenter_1F' in mid:
            centers.append(mid)
        for target in sorted(set(maps[mid].exits.values())):
            if target in maps and target not in seen:
                seen.add(target); todo.append(target)
    return centers


def route_actions(engine, state, hid, include_routes=True):
    """At most two feasible care journeys and a legacy staff return option."""
    if not include_routes:
        return []
    h = state.humans[hid]
    if not _available(h, state.simulated_time):
        return []
    own_party = [state.pokemon[pid] for pid in h.get('party', []) if pid in state.pokemon]
    targets = _centers(engine.maps, h['map_id']) if _condition(own_party)['needs_care'] else []
    assignment = h.get('service_assignment')
    duty_target = assignment.get('map_id') if assignment and not h.get('workplace') else None
    if duty_target == h['map_id'] or duty_target not in engine.maps:
        duty_target = None
    if duty_target and duty_target not in targets:
        targets.append(duty_target)
    cache = {}; routes = []
    for target in targets:
        try:
            route = plan_journey(engine.maps, h, target, state=state, max_nodes=48, max_tiles=1000, path_cache=cache)
        except JourneyUnavailable:
            continue
        duration = sum(len(segment['steps']) + 1 for segment in route)
        kind = 'workplace' if target == duty_target else 'healing'
        action = LegalAction(action='journey_to', arguments={'map_id': target},
            known_consequences={'destination_kind': kind, 'engine_owned_route': True,
                'duration_seconds': duration, 'maps_crossed': len(route), 'may_interrupt': True,
                'service_requires_staff_choice': True})
        routes.append((duration, target, action))
    healing = sorted((row for row in routes if row[2].known_consequences['destination_kind'] == 'healing'), key=lambda row: row[:2])[:2]
    duty = [row for row in routes if row[2].known_consequences['destination_kind'] == 'workplace']
    return [row[2] for row in duty + healing]
