"""Bounded private feedback grounded in own accepted choices and engine facts.

This view never invents achievements, infers another person's private state,
changes legal choices, or classifies a subjective commitment as verified.
"""
import copy
from collections import Counter

MOVEMENT = {'walk_to', 'travel_to', 'journey_to', 'enter_map', 'fly_to'}
OPPOSITE = {'north': 'south', 'south': 'north', 'east': 'west', 'west': 'east'}


def metrics(h):
    """Own facts only; counts do not imply skill or subjective goal completion."""
    return {'money': h.get('money', 0), 'badges': list(h.get('badges', [])),
            'caught_species': list(h.get('pokedex', [])),
            'owned_pokemon': list(h.get('party', [])) + list(h.get('box', [])),
            'visited_maps': list(h.get('field', {}).get('visited_maps', [])),
            'map_id': h.get('map_id'), 'x': h.get('x'), 'y': h.get('y')}


def metric_changes(before, after):
    result = {'money_change': after['money'] - before.get('money', after['money'])}
    for key in ('badges', 'caught_species', 'owned_pokemon', 'visited_maps'):
        # Legacy baselines cannot establish a delta for absent fields.
        result['new_' + key] = ([x for x in after[key] if x not in before[key]]
                                if key in before else None)
    result['location_changed'] = (any(before.get(k) != after[k] for k in ('map_id', 'x', 'y'))
                                  if all(k in before for k in ('map_id', 'x', 'y')) else None)
    return result


def accepted_effects(h, hid, changes):
    """Summarize writes at acceptance, keeping deferred intentions distinct."""
    tracked = {'money', 'badges', 'pokedex', 'party', 'box', 'field', 'map_id', 'x', 'y', 'movement_intent', 'activity', 'service_request'}
    after = {key: copy.deepcopy(h[key]) for key in tracked if key in h}
    prefix = f'humans.{hid}.'
    for change in changes:
        path = change.get('path', '')
        if change.get('op') != 'set' or not path.startswith(prefix):
            continue
        parts = path[len(prefix):].split('.')
        if parts[0] not in tracked:
            continue
        target = after
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = copy.deepcopy(change['value'])
    result = metric_changes(metrics(h), metrics(after))
    if after.get('movement_intent') != h.get('movement_intent') and after.get('movement_intent'):
        result['movement'] = 'accepted_pending_engine_steps'
    if after.get('activity') != h.get('activity') and after.get('activity'):
        result['activity'] = 'started_not_completed'
    if after.get('service_request') != h.get('service_request') and after.get('service_request'):
        result['service'] = 'queued_not_completed'
    return result


def repetition_warnings(recent):
    rows = recent[-8:]
    result = []
    targets = Counter(r.get('arguments', {}).get('human_id') for r in rows if r.get('action') == 'talk_to')
    for target, count in targets.items():
        if target and count >= 4:
            result.append({'kind': 'repeated_conversation_target', 'human_id': target,
                           'count': count, 'window': len(rows),
                           'meaning': 'Repeated questions are recorded conversations, not evidence of a new answer or completed task.'})
    for kind in ('remember', 'set_goal'):
        count = sum(r.get('action') == kind for r in rows)
        if count >= 4:
            result.append({'kind': 'repeated_bookkeeping', 'action': kind, 'count': count,
                'meaning': 'Rephrased notes or goals do not establish new observations or practical progress. Compare factual results and either execute a feasible step or identify a blocker.'})
    walks = [r for r in rows if r.get('action') == 'walk_to']
    reversals = sum(OPPOSITE.get(a.get('arguments', {}).get('direction')) == b.get('arguments', {}).get('direction')
                    for a, b in zip(walks, walks[1:]) if a.get('arguments', {}).get('direction') in OPPOSITE)
    if reversals >= 2:
        result.append({'kind': 'direction_reversals', 'count': reversals,
                       'meaning': 'Recent walking choices reverse direction; compare actual position and destination rather than the explanation.'})
    destinations = [r.get('arguments', {}).get('map_id') for r in rows
                    if r.get('action') in {'journey_to', 'enter_map'} and r.get('arguments', {}).get('map_id')]
    if len(destinations) >= 4 and len(set(destinations)) == 2 and all(a != b for a, b in zip(destinations, destinations[1:])):
        result.append({'kind': 'alternating_map_targets', 'map_ids': sorted(set(destinations)),
                       'count': len(destinations), 'meaning': 'Repeated entry and return intentions do not themselves start a gym challenge or training.'})
    return result


def observation_view(engine, state, hid, legal_actions):
    """Return detached own facts and options that are actually legal now."""
    h = state.humans[hid]
    life = h.get('individual_life') or {}
    recent = life.get('recent_decisions', [])[-8:]
    rows = []
    for row in recent:
        item = {key: copy.deepcopy(row[key]) for key in ('action', 'arguments', 'at', 'accepted_effects') if key in row}
        item['evidence_status'] = 'accepted_choice'  # explanations are not outcome receipts
        rows.append(item)
    own_battles = [b for b in state.world_facts.get('battles', {}).values()
                   if hid in (b.get('challenger'), b.get('opponent'))]
    # Version-derived IDs are sortable by the numeric accepted boundary.
    def battle_order(b):
        try: return int(b.get('battle_id', '').split('-')[1])
        except (ValueError, IndexError): return -1
    battles = [{'battle_id': b.get('battle_id'), 'ended': b.get('ended', False),
                'outcome': b.get('outcome'), 'last_catch': copy.deepcopy(b.get('last_catch'))}
               for b in sorted(own_battles, key=battle_order)[-3:]]
    commitment = life.get('commitment')
    activity_receipt = h.get('last_activity') or {}
    progress = {'current': metrics(h), 'recent_battle_results': battles,
                'last_service': {key: copy.deepcopy(h['last_service'][key]) for key in
                    ('kind', 'requested_at', 'completed_at', 'busy_until', 'outcome', 'refund') if key in h.get('last_service', {})}}
    progress['last_completed_activity'] = {key: copy.deepcopy(activity_receipt[key]) for key in
        ('activity_kind', 'started_at', 'completed_at', 'reward') if key in activity_receipt}
    if commitment:
        progress['since_commitment'] = metric_changes(commitment.get('baseline', {}), metrics(h))
        progress['commitment_assessment'] = {'status': commitment.get('status'),
            'assessment_source': commitment.get('assessment_source', 'unassessed'),
            'verified_goal_completion': False,
            'meaning': 'Own metric changes are factual. Whether an open-text aspiration is satisfied remains a personal assessment.'}
    categories = {'get_pokemon': {'choose_starter', 'receive_source_gift', 'revive_fossil', 'pc_withdraw'},
        'earn_money': {'work', 'shop_sell'}, 'train_or_compete': {'train', 'start_battle', 'challenge_trainer', 'accept_challenge', 'league_enter'},
        'field_notes': {'catch', 'remember'}, 'care': {'heal_party', 'rest', 'serve_customer'},
        'respond_to_invitation': {'accept_challenge', 'decline_challenge'}}
    pathways = {}
    for category, kinds in categories.items():
        options = [a for a in legal_actions if a.action in kinds][:4]
        if options:
            pathways[category] = [{'action': a.action, 'arguments': copy.deepcopy(a.arguments),
                                   'known_consequences': copy.deepcopy(a.known_consequences)} for a in options]
    for a in legal_actions:
        if a.action == 'journey_to' and a.known_consequences.get('destination_kind') in {'starter', 'training', 'pokemon_source', 'workplace', 'healing'}:
            pathways.setdefault('feasible_routes', []).append({'action': a.action, 'arguments': copy.deepcopy(a.arguments),
                'known_consequences': copy.deepcopy(a.known_consequences)})
    prerequisites = {'party_size': len(h.get('party', [])), 'stored_pokemon_count': len(h.get('box', [])),
        'training_option_visible': any(a.action == 'train' for a in legal_actions),
        'work_option_visible': any(a.action == 'work' for a in legal_actions),
        'starter_option_visible': any(a.action == 'choose_starter' for a in legal_actions),
        'meaning': 'No party means no current team to train or improve. Acquiring or withdrawing a Pokemon is a separate legal action; asking for one does not transfer ownership.' if not h.get('party') else 'Battle and activity results come from engine resolution, not stated intentions.'}
    return {'prerequisites': prerequisites, 'recent_action_feedback': rows, 'repetition_warnings': repetition_warnings(recent),
            'grounded_progress': progress, 'pathways': pathways,
            'boundaries': ['Talking records speech and relationships; it does not award a starter, income, training, a badge, or a journal achievement.',
                'Entering a gym is movement; a legal battle action and completed victory are separate requirements.',
                'Clinical patients, moss, and insect surveys are not implemented game tasks. Use observed Pokemon, reachable places, own memories and legal options to ground an aspiration.',
                'Options below are possibilities, not instructions or guaranteed results.']}
