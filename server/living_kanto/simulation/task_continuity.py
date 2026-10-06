"""Model-selected concrete next steps with engine-grounded outcome receipts.

No goal inference, reward, automatic action, or legacy history reconstruction.
"""
import copy
from ..contracts import LegalAction

TASK_ACTIONS = {'plan_next_step', 'pause_task', 'resume_task', 'abandon_task'}
TEXT = '<non-empty text, <=200 chars>'
MOVEMENT = {'journey_to', 'enter_map', 'travel_to', 'walk_to', 'fly_to'}


def result_for(h, option):
    action, args, known = option.action, option.arguments, option.known_consequences
    if action in {'journey_to', 'enter_map', 'fly_to'}:
        return {'kind': 'location', 'map_id': args['map_id']}
    if action == 'travel_to':
        return {'kind': 'location', 'map_id': h['map_id'], 'x': args['x'], 'y': args['y']}
    if action in {'choose_starter', 'receive_source_gift', 'store_withdraw'}:
        return {'kind': 'party_acquisition'}
    if action == 'heal_party' and h.get('party'): return {'kind': 'service', 'role': 'customer'}
    if action == 'serve_customer': return {'kind': 'service', 'role': 'staff', 'request_id': args['request_id']}
    if action in {'work', 'rest'}: return {'kind': 'activity', 'activity_kind': action}
    if action == 'train': return {'kind': 'battle_resolution'}
    return None


def options(h, offered):
    task = (h.get('individual_life') or {}).get('task') or {}
    if task.get('status') in {'planned', 'executing', 'paused'}:
        acts = [LegalAction(action='abandon_task', arguments={'text': TEXT}, known_consequences={'preserves_history': True})]
        acts.append(LegalAction(action='resume_task' if task['status'] == 'paused' else 'pause_task',
                               arguments={'text': TEXT}, known_consequences={'does_not_cancel_engine_activity': True}))
        return acts
    # Only plan actions that remain in the final bounded executable menu.
    candidates = [a for a in offered if result_for(h, a) is not None]
    # Offer several kinds, avoiding three starters consuming the whole menu.
    chosen, seen = [], set()
    for a in candidates:
        key = (a.action, a.known_consequences.get('destination_kind'))
        if key in seen: continue
        seen.add(key); chosen.append(a)
        if len(chosen) == 6: break
    return [LegalAction(action='plan_next_step', arguments={'action': a.action, 'arguments': copy.deepcopy(a.arguments), 'text': TEXT},
        known_consequences={'expected_result': result_for(h, a), 'does_not_execute_action': True,
                            'action_consequences': copy.deepcopy(a.known_consequences)}) for a in chosen]


def action_changes(engine, state, hid, action, args, reason, provenance):
    from .engine import EngineError
    h = state.humans[hid]; life = copy.deepcopy(h.get('individual_life') or {})
    task = life.get('task') or {}
    if not isinstance(args.get('text'), str) or not args['text'].strip() or len(args['text']) > 200:
        raise EngineError('Task changes need a nonempty explanation of at most 200 characters')
    if action == 'plan_next_step':
        if set(args) != {'action', 'arguments', 'text'} or task.get('status') in {'planned', 'executing', 'paused'}:
            raise EngineError('Pause or abandon the existing task before choosing another next step')
        offered = engine.legal_actions(state, hid)
        matching = next((a for a in offered if a.action == action and all(a.arguments[k] == args[k] for k in ('action', 'arguments'))), None)
        if not matching: raise EngineError('Next step must be a currently offered concrete action')
        if task: life['task_history'] = (life.get('task_history', []) + [task])[-8:]
        task = {'task_id': f'task-{state.state_version}-{hid}', 'status': 'planned',
            'purpose': args['text'].strip(), 'decision_explanation': reason, 'created_at': state.simulated_time,
            'action': args['action'], 'arguments': copy.deepcopy(args['arguments']),
            'expected_result': copy.deepcopy(matching.known_consequences['expected_result']),
            'commitment_text': (life.get('commitment') or {}).get('text'),
            'baseline_party': list(h.get('party', [])), 'provenance': copy.deepcopy(provenance)}
    else:
        if set(args) != {'text'} or task.get('status') not in {'planned', 'executing', 'paused'}:
            raise EngineError('No ongoing task to change')
        if action == 'resume_task' and task['status'] != 'paused': raise EngineError('Task is not paused')
        if action == 'pause_task' and task['status'] == 'paused': raise EngineError('Task is already paused')
        task['status'] = {'pause_task': 'paused', 'resume_task': 'executing' if task.get('started_at') is not None else 'planned', 'abandon_task': 'abandoned'}[action]
        task.update(execution_state=task['status'], blocked_reason=None)
        task['last_transition'] = {'at': state.simulated_time, 'action': action, 'reason': args['text'].strip(), 'source': 'accepted_choice'}
    life['task'] = task
    return [{'op': 'set', 'path': f'humans.{hid}.individual_life', 'value': life}]


def record_choice(h, life, action, args, reason, time, version, changes, hid):
    task = life.get('task')
    if not task or task.get('status') not in {'planned', 'executing'} or action in TASK_ACTIONS: return
    if action == task['action'] and args == task['arguments']:
        task.update(status='executing', started_at=time, started_state_version=version)
        if task['expected_result']['kind'] == 'party_acquisition': task['execution_party'] = list(h.get('party', []))
        # Match the precise deferred operation, not any later service/activity.
        for c in changes:
            path, value = c.get('path', ''), c.get('value')
            if path == f'humans.{hid}.service_request' and value: task['request_id'] = value['request_id']
            if path == f'humans.{hid}.activity' and value: task['intent_id'] = value['intent_id']
            if path == f'humans.{hid}.movement_intent' and value: task['intent_id'] = value['intent_id']
            if path == f'humans.{hid}.battle_id' and value: task['battle_id'] = value
        relation = 'executing_planned_step'
    elif action in {'wait', 'wait_for_service', 'wait_until_ready', 'battle_move', 'battle_switch', 'battle_item', 'battle_turn'}:
        relation = 'continuing_or_waiting'
    else:
        relation = 'chose_other_action'
    task['last_transition'] = {'at': time, 'action': action, 'reason': reason, 'relation': relation,
                               'source': 'accepted_choice', 'semantic_relevance_verified': False}


def outcome(state, h, task):
    if task.get('started_at') is None: return None
    expected = task['expected_result']; kind = expected['kind']
    if kind == 'location':
        if all(h.get(k) == v for k, v in expected.items() if k != 'kind'):
            return {'kind': 'arrived', **{k: h[k] for k in ('map_id', 'x', 'y')}}
    elif kind == 'party_acquisition':
        new = [p for p in h.get('party', []) if p not in task.get('execution_party', task['baseline_party'])]
        if new: return {'kind': 'party_acquisition', 'pokemon_ids': new}
    elif kind == 'service':
        receipt = h.get('last_service') or {}; rid = task.get('request_id', expected.get('request_id'))
        if rid and receipt.get('request_id') == rid and receipt.get('outcome') not in {'cancelled', 'refunded'} and receipt.get('completed_at') is not None:
            return {'kind': 'service_completed', 'request_id': rid, 'completed_at': receipt['completed_at']}
    elif kind == 'activity':
        receipt = h.get('last_activity') or {}
        if task.get('intent_id') and receipt.get('intent_id') == task['intent_id'] and receipt.get('completed_at') is not None:
            return {'kind': 'activity_completed', 'intent_id': task['intent_id'], 'reward': copy.deepcopy(receipt.get('reward'))}
    elif kind == 'battle_resolution':
        battle = state.world_facts.get('battles', {}).get(task.get('battle_id'), {})
        if battle.get('ended') or battle.get('outcome'):
            return {'kind': 'battle_resolved', 'battle_id': task['battle_id'], 'outcome': battle.get('outcome'), 'victory_not_implied': True}
    return None


def settle(state):
    changes = []
    for hid, h in state.humans.items():
        task = (h.get('individual_life') or {}).get('task') or {}
        if task.get('status') not in {'planned', 'executing', 'paused'}: continue
        updated = copy.deepcopy(task)
        receipt = outcome(state, h, task)
        if receipt:
            updated.update(status='completed', result=receipt, completed_at=state.simulated_time,
                           execution_state='completed', blocked_reason=None)
        else:
            reason = None
            if task['status'] == 'executing' and not any(h.get(k) for k in ('movement_intent','activity','service_request','battle_id')):
                reason = 'The accepted operation ended or was interrupted without its expected result.'
            if task['status'] == 'planned' and task['action'] in {'journey_to','enter_map','fly_to'}:
                from .workplaces import duty_info
                duty = duty_info(state, hid)
                if duty.get('on_duty') and duty.get('at_workplace') and task['arguments'].get('map_id') != h.get('map_id'):
                    reason = 'Departure is blocked by current workplace duty; wait for relief or revise the step.'
            updated.update(execution_state='blocked' if reason else task['status'], blocked_reason=reason)
        if updated != task:
            life = copy.deepcopy(h['individual_life']); life['task'] = updated
            changes.append({'op': 'set', 'path': f'humans.{hid}.individual_life', 'value': life})
    return changes


def view(h, offered, duty):
    task = copy.deepcopy((h.get('individual_life') or {}).get('task'))
    def private(v):
        if isinstance(v, dict): return {k: private(x) for k, x in v.items() if k != 'provenance'}
        if isinstance(v, list): return [private(x) for x in v]
        return v
    blocked = []
    if (h.get('service_request') or {}).get('kind') == 'healing' and not h.get('party'):
        blocked.append({'kind': 'healing_without_party', 'reason': 'Your own healing request is queued, but you have no party Pokémon to heal. Serving customers is a separate serve_customer action. Consider cancel_service if this request is not useful.'})
    if duty.get('on_duty') and duty.get('at_workplace'):
        blocked.append({'kind': 'workplace_duty', 'reason': duty['responsibility'],
                        'meaning': 'An exit approach stays inside; departure requires an offered enter_map or journey_to action.'})
    if task and task.get('status') == 'planned' and not any(a.action == task['action'] and a.arguments == task['arguments'] for a in offered):
        blocked.append({'kind': 'next_step_unavailable', 'reason': 'The planned action is not currently offered. Reassess, pause, or abandon it; do not describe another action as completing it.'})
    if task and task.get('status') == 'executing' and not any(h.get(k) for k in ('movement_intent', 'activity', 'service_request', 'battle_id')):
        blocked.append({'kind': 'no_running_operation', 'reason': 'The accepted operation ended or was interrupted without the expected result. Choose a feasible retry or explain a change.'})
    return {'task': private(task), 'blockers': blocked, 'next_step_choices': [private(a.to_dict()) for a in offered if a.action in TASK_ACTIONS],
            'meaning': 'A task is one chosen concrete step; completing it does not establish that the whole commitment is fulfilled.'}


def settle_changes(state, changes):
    if not any((h.get('individual_life') or {}).get('task') for h in state.humans.values()) and not any(
            c.get('path','').endswith('.individual_life') and isinstance(c.get('value'),dict) and c['value'].get('task') for c in changes):
        return []
    return settle(state.apply_changes(changes))
