"""Frozen private-observation ablations and factual interval evaluation.

These helpers never commit, create a run, change model settings, or judge prose
as an achievement. Frozen proposals alone cannot establish behavioral gains.
"""
import copy
from collections import Counter
from ..simulation.behavior_feedback import metrics, metric_changes, repetition_warnings

CONDITIONS = ('full', 'without_action_awareness', 'without_social_awareness', 'recent_memory_only')


def ablate(observation, condition, *, own_archive=None):
    if condition not in CONDITIONS:
        raise ValueError('Unknown evaluation condition')
    result = copy.deepcopy(observation)
    own = result.get('self_state', {})
    awareness = own.get('decision_awareness', {})
    if condition == 'without_action_awareness':
        own.pop('behavior_feedback', None)
        awareness.pop('action', None)
        # Preserve the actual task and legal options; only remove review aids.
    elif condition == 'without_social_awareness':
        awareness.pop('social', None)
        own.pop('conversation_context', None)
        own.pop('relationships', None)
        # Direct messages in recall and reply choices stay: this tests the
        # structured social aid, not deprivation of legitimately heard speech.
    elif condition == 'recent_memory_only':
        if own_archive is None:
            raise ValueError('Recent-memory comparison requires the owner archive')
        memories = [copy.deepcopy(m) for m in own_archive.values() if isinstance(m, dict)]
        def time(m):
            value = m.get('time')
            return value if isinstance(value, (int, float)) else -1
        result['memories'] = sorted(memories, key=time)[-8:]
        own.pop('memory_recall', None)
    return result


def interval_report(before, after):
    """Snapshot facts, with bounded-history coverage explicitly reported."""
    if before.run_id != after.run_id or after.state_version < before.state_version:
        raise ValueError('Supply ordered snapshots of the same run')
    people = []
    for hid in sorted(set(before.humans) & set(after.humans)):
        old, new = before.humans[hid], after.humans[hid]
        life = new.get('individual_life') or {}
        rows = life.get('recent_decisions', [])
        recent = [r for r in rows if type(r.get('source_state_version')) is int
                  and before.state_version <= r['source_state_version'] < after.state_version]
        tasks = life.get('task_history', []) + ([life['task']] if life.get('task') else [])
        old_life = old.get('individual_life') or {}
        old_tasks = old_life.get('task_history', []) + ([old_life['task']] if old_life.get('task') else [])
        previously_done = {t.get('task_id') for t in old_tasks
                           if t.get('status') == 'completed' and t.get('result')}
        # Deduplicate current/history copies. Completion, not self-report.
        done = {t['task_id']: t for t in tasks if t.get('task_id') and t.get('status') == 'completed'
                and t.get('result') and isinstance(t.get('completed_at'), (int, float))
                and before.simulated_time <= t['completed_at'] <= after.simulated_time
                and t['task_id'] not in previously_done}
        people.append({'human_id': hid, 'facts': metric_changes(metrics(old), metrics(new)),
                       'completed_steps_retained': len(done),
                       'retained_decision_counts': dict(Counter(r.get('action') for r in recent)),
                       'repetition_flags': repetition_warnings(recent),
                       'retained_decisions': len(recent),
                       'decision_window_may_be_truncated': len(rows) >= 8,
                       'task_window_may_be_truncated': len(life.get('task_history', [])) >= 8})
    return {'run_id': before.run_id, 'before_version': before.state_version,
            'after_version': after.state_version,
            'elapsed_simulated_time': after.simulated_time - before.simulated_time,
            'people': people, 'population_before': len(before.humans), 'population_after': len(after.humans),
            'notice': 'Snapshot deltas are facts, not causal attribution. Retained task and decision windows are lower-bound samples; use canonical event history for complete counts. Repetition flags identify review candidates, not verified futile behavior. Self-assessed commitments do not count as completed steps.'}
