"""Project Sid inspired grounding, derived exclusively from the owner's records.

No extra inference, hidden social state, semantic sentiment scoring, or mutation.
Expected task outcomes are engine contracts, not assertions that a goal succeeded.
"""
import copy

POLICY = 'sid-grounding-v1'
GUIDANCE = (
    'Inspect self_state.decision_awareness: compare your concrete step expectation with its '
    'recorded result, and distinguish pending execution from a blocker. Use social evidence '
    'to understand what others actually said, including explicit declines; their intentions '
    'and feelings remain uncertain. Familiarity is not trust. Ground a new or revised '
    'commitment in your experiences, needs and responsibilities, then choose a feasible '
    'action. Reflection alone does not execute that action or establish success. '
)


def action_view(h):
    life = h.get('individual_life') or {}
    task = life.get('task') or {}
    comparison = None
    if task:
        comparison = {key: copy.deepcopy(task[key]) for key in
            ('task_id', 'purpose', 'action', 'arguments', 'expected_result', 'status',
             'execution_state', 'blocked_reason', 'result', 'completed_at') if key in task}
        comparison['evidence_status'] = (
            'engine_result_recorded' if task.get('status') == 'completed' and task.get('result')
            else 'blocked_execution' if task.get('execution_state') == 'blocked'
            else 'abandoned_choice' if task.get('status') == 'abandoned'
            else 'paused_choice' if task.get('status') == 'paused'
            else 'accepted_operation_pending' if task.get('started_at') is not None
            else 'planned_not_executed')
        comparison['whole_goal_completion_verified'] = False
    return {'step_comparison': comparison,
            'review': 'Compare the expected concrete result with its receipt. If pending, allow execution; if blocked, reconsider the method. A resolved battle need not be a victory. You may revise your own purpose after experience.'}


def social_view(h, visible_ids=()):
    """Bounded evidence about known people; never read another human's state."""
    memories = h.get('memories') or {}
    speech = [(str(slot), m) for slot, m in memories.items() if isinstance(m, dict)
              and m.get('source') == 'recorded_speech' and m.get('other')
              and m.get('direction') in {'heard', 'spoken'}]
    def order(row):
        slot, m = row
        version = m.get('source_state_version')
        return (version if type(version) is int else -1, int(slot) if slot.isdigit() else -1, slot)
    speech.sort(key=order)
    # Nearby people with evidence first, then recent conversational partners.
    recent_ids = list(dict.fromkeys(m['other'] for _, m in reversed(speech)))
    visible = set(visible_ids)
    ids = ([hid for hid in recent_ids if hid in visible] +
           [hid for hid in recent_ids if hid not in visible])[:4]
    profiles = []
    for hid in ids:
        records = [(slot, m) for slot, m in speech if m['other'] == hid]
        received = [(slot, m) for slot, m in records if m['direction'] == 'heard']
        statements = []
        for slot, m in received[-2:]:
            statement = {key: copy.deepcopy(m[key]) for key in
                ('text', 'time', 'speech_id', 'reply_to', 'response_disposition') if key in m}
            statement.update(source_memory_id=slot, content_status='reported_speech',
                             intentions_and_feelings_verified=False)
            statements.append(statement)
        own_reply_ids = {m.get('reply_to') for _, m in records if m['direction'] == 'spoken' and m.get('reply_to')}
        own_sent_ids = {m.get('speech_id') for _, m in records if m['direction'] == 'spoken' and m.get('speech_id')}
        incoming_replies = [m for _, m in received if m.get('reply_to') in own_sent_ids]
        relation = h.get('relationships', {}).get(hid, {})
        profile = {'human_id': hid, 'recent_received_statements': statements,
                   'received_messages_without_linked_own_reply': sum(bool(m.get('speech_id')) and m['speech_id'] not in own_reply_ids for _, m in received),
                   'latest_linked_reply_disposition': incoming_replies[-1].get('response_disposition') if incoming_replies else None,
                   'semantic_answer_verified': False}
        if isinstance(relation, dict):
            profile['own_relationship_record'] = {key: copy.deepcopy(relation[key]) for key in
                ('familiarity', 'trust', 'affinity') if key in relation}
        profiles.append(profile)
    return {'known_people': profiles,
            'notice': 'These are your received statements and your relationship records. Speech does not prove a promise was fulfilled or a claim is true. Missing replies do not imply hostility. A decline is an explicit response disposition, not a verified emotion. People may disagree or disengage.'}


def observation_view(h, visible_ids=()):
    return {'policy': POLICY, 'action': action_view(h), 'social': social_view(h, visible_ids),
            'reflection_is_not_action': True}
