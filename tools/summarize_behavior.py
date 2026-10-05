#!/usr/bin/env python3
"""Read-only, coherent RunStore behavior snapshot; never calls a model or engine."""
import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
from living_kanto.store import RunStore


@contextmanager
def coherent_store(database):
    # RunStore's constructor sets WAL/schema pragmas, so open only a private
    # backup with it. SQLite online backup includes committed WAL transactions
    # and supplies one coherent snapshot while the original writer continues.
    with tempfile.TemporaryDirectory(prefix='living-kanto-behavior-') as folder:
        copy = Path(folder) / 'snapshot.db'
        source = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)
        destination = sqlite3.connect(copy)
        started_at = datetime.now(timezone.utc).isoformat()
        try:
            source.backup(destination)
            completed_at = datetime.now(timezone.utc).isoformat()
        finally:
            destination.close()
            source.close()
        store = RunStore(copy)
        try:
            yield store, {'started_at_utc': started_at, 'completed_at_utc': completed_at}
        finally:
            store.close()


def continuation(provenance):
    return bool(provenance.get('engine_continuation') or 'continuation_of_state_version' in provenance)


def summarize(store, run_id, snapshot_interval):
    metadata, state, head = store.load_run(run_id)  # Verifies genesis/chain/current snapshot.
    replay = store.replay(run_id)                 # Explicit inference-free full-chain audit.
    events = store.iter_events(run_id)
    row = store._db.execute('SELECT genesis_json FROM runs WHERE run_id=?', (run_id,)).fetchone()
    genesis = json.loads(row['genesis_json'])
    initial_humans, initial_pokemon = genesis['humans'], genesis['pokemon']
    initial_championship = genesis.get('world_facts', {}).get('championship', {})
    model_actors, model_actions = Counter(), Counter()
    actual_actors, actual_actions = Counter(), Counter()
    user_actions, kinds, engine_kinds = Counter(), Counter(), Counter()
    providers = Counter()
    engine_only = batch_model_events = single_model_events = continuations = 0
    creative_events = []
    captures, evolutions = [], []
    mon_fields = {pid: {'owner_id': p.get('owner_id'), 'species': p.get('species')} for pid, p in initial_pokemon.items()}
    modes = {genesis['mode'], state.mode}
    for event in events:
        cause = event.causation
        provenance = cause.get('provenance') or {}
        kinds[event.event_kind] += 1
        is_continuation = continuation(provenance)
        continuations += is_continuation
        # A batch's engine provenance is an envelope, not a replacement for the
        # accepted human decisions. Count its rows, never an additional single.
        is_batch = isinstance(cause.get('decisions'), list)
        choices = cause['decisions'] if is_batch else [{'human_id': cause.get('human_id'), 'action': cause.get('action'), 'provenance': provenance}]
        model_in_event = human_in_event = 0
        for decision in choices:
            prov = decision.get('provenance') or {}
            if is_continuation or continuation(prov):
                continue
            actor, action = decision.get('human_id'), decision.get('action')
            if not actor or not action:
                continue
            if prov.get('kind') == 'model' and prov.get('model_id'):
                model_in_event += 1
                human_in_event += 1
                model_actors[actor] += 1
                model_actions[action] += 1
                if prov.get('test_provider') is True:
                    providers['explicit_test_provider'] += 1
                elif prov.get('test_provider') is False:
                    providers['explicit_non_test_provider'] += 1
                    actual_actors[actor] += 1
                    actual_actions[action] += 1
                else:
                    providers['provider_marker_unspecified'] += 1
            elif prov.get('kind') == 'user':
                human_in_event += 1
                user_actions[action] += 1
        if model_in_event:
            if is_batch:
                batch_model_events += 1
            else:
                single_model_events += 1
        engine_authored = provenance.get('kind') == 'engine' or cause.get('human_id') == 'engine' or is_continuation
        if engine_authored:
            engine_kinds[event.event_kind] += 1
            engine_only += human_in_event == 0
        changes = event.transaction.get('changes', [])
        touched = {}
        creative = provenance.get('kind') == 'creative' or any(word in event.event_kind.lower() for word in ('creative', 'intervention', 'director'))
        for change in changes:
            path, value, operation = change.get('path', ''), change.get('value'), change.get('op')
            if path == 'mode' and operation == 'set':
                modes.add(value)
            if path == 'world_facts.creative_modified' and value is True:
                creative = True
            parts = path.split('.')
            if len(parts) >= 2 and parts[0] == 'pokemon':
                pid = parts[1]
                if pid not in touched:
                    touched[pid] = dict(mon_fields[pid]) if pid in mon_fields else None
                if len(parts) == 2:
                    if operation == 'remove':
                        mon_fields.pop(pid, None)
                    elif operation == 'set' and isinstance(value, dict):
                        mon_fields[pid] = {key: value.get(key) for key in ('owner_id', 'species')}
                elif len(parts) == 3 and parts[2] in ('owner_id', 'species') and operation == 'set':
                    mon_fields.setdefault(pid, {})[parts[2]] = value
        if creative:
            creative_events.append(event.event_index)
        # Proof is a supported action/event kind PLUS an actual individual
        # transition, not an AI explanation or a species-count increase.
        capture_kind = event.event_kind in ('human.caught_pokemon', 'battle.ended') and cause.get('action') in ('catch', 'safari_action')
        evolution_kind = (event.event_kind == 'human.party_changed' and cause.get('action') == 'evolve') or (event.event_kind == 'human.used_item' and cause.get('action') == 'use_item') or event.event_kind == 'human.traded'
        for pid, before in touched.items():
            after = mon_fields.get(pid)
            if not before or not after:
                continue
            if capture_kind and before.get('owner_id') is None and after.get('owner_id') is not None:
                captures.append({'event_index': event.event_index, 'pokemon_id': pid, 'trainer_id': after['owner_id'], 'species': after.get('species')})
            if evolution_kind and before.get('species') and after.get('species') != before['species']:
                evolutions.append({'event_index': event.event_index, 'pokemon_id': pid, 'trainer_id': after.get('owner_id'), 'from_species': before['species'], 'to_species': after.get('species')})
    current_badges = {hid: list(h.get('badges', [])) for hid, h in state.humans.items() if h.get('badges')}
    setup_badges = {hid: list(h.get('badges', [])) for hid, h in initial_humans.items() if h.get('badges')}
    added_badges = {hid: sorted(set(h.get('badges', [])) - set(initial_humans.get(hid, {}).get('badges', []))) for hid, h in state.humans.items()}
    added_badges = {hid: values for hid, values in added_badges.items() if values}
    championship = state.world_facts.get('championship', {})
    fame = championship.get('hall_of_fame', [])
    initial_fame = initial_championship.get('hall_of_fame', [])
    hall_records = [{'champion_id': entry.get('champion_id'), 'previous_champion': entry.get('previous_champion'), 'battle_ids': list(entry.get('battle_ids', [])), 'present_in_genesis': entry in initial_fame} for entry in fame]
    return {
        'run_id': run_id,
        'snapshot_copy_interval': snapshot_interval,
        'report_generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'snapshot_method': 'SQLite read-only online backup; verified RunStore reads/replay on isolated copy',
        'state_version': state.state_version, 'simulated_time': state.simulated_time, 'event_count': len(events),
        'first_event_wall_time': events[0].real_wall_time if events else None,
        'last_event_wall_time': events[-1].real_wall_time if events else None,
        'population': {'initial_humans': len(initial_humans), 'current_humans': len(state.humans)},
        'decisions': {
            'recorded_model_decisions': sum(model_actors.values()), 'distinct_model_actors': len(model_actors),
            'model_decisions_by_actor': dict(sorted(model_actors.items())), 'model_decisions_by_action': dict(sorted(model_actions.items())),
            'explicit_non_test_model_decisions': sum(actual_actors.values()), 'distinct_explicit_non_test_actors': len(actual_actors),
            'explicit_non_test_by_actor': dict(sorted(actual_actors.items())), 'explicit_non_test_by_action': dict(sorted(actual_actions.items())),
            'provider_markers': dict(sorted(providers.items())),
            'batch_events_with_model_decisions': batch_model_events, 'single_events_with_model_decisions': single_model_events,
            'user_decisions_by_action': dict(sorted(user_actions.items())),
            'continuations_excluded_from_decision_counts': continuations,
        },
        'events': {'by_kind': dict(sorted(kinds.items())), 'engine_authored_by_kind': dict(sorted(engine_kinds.items())), 'engine_only_without_new_human_decision': engine_only},
        'factual_progress': {
            'initial_setup_badges': setup_badges, 'current_badges': current_badges, 'badges_added_since_genesis': added_badges,
            'initial_setup_champion': initial_championship.get('current_champion'), 'current_champion': championship.get('current_champion'),
            'hall_of_fame': hall_records, 'new_hall_of_fame_entries': sum(not entry['present_in_genesis'] for entry in hall_records),
            'initial_pokemon_count': len(initial_pokemon), 'current_pokemon_count': len(state.pokemon),
            'initial_species_counts': dict(sorted(Counter(p['species'] for p in initial_pokemon.values()).items())),
            'current_species_counts': dict(sorted(Counter(p['species'] for p in state.pokemon.values()).items())),
            'proven_captures': captures, 'proven_capture_count': len(captures), 'proven_evolutions': evolutions, 'proven_evolution_count': len(evolutions),
        },
        'creative': {'initial_mode': genesis['mode'], 'current_mode': state.mode, 'modes_observed': sorted(modes), 'creative_modified': bool(state.world_facts.get('creative_modified')), 'creative_event_indexes': creative_events},
        'integrity': {'replay_verified': True, 'replay_matches': replay.state_hash == state.state_hash and replay.state_version == state.state_version, 'state_hash': state.state_hash, 'replay_hash': replay.state_hash, 'head_hash': head, 'snapshot_coherent': True},
        'limitations': ['Model counts prove accepted recorded provenance, not independent observation of the provider hardware; unspecified provider markers are not counted as explicit non-test decisions.', 'Live writers may advance after the isolated snapshot; this report describes the recorded version only.', 'Badges and Hall of Fame are canonical facts, not claims of autonomous earning; Creative status and user decisions must be considered separately.', 'Capture/evolution totals require matching event kinds/actions plus ownership/species transitions; births, spawns, source gifts and initial office teams are not captures.', 'This snapshot does not by itself verify elapsed soak duration, every participant making a model decision, or autonomous championship.'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if not args.database.is_file():
        parser.error('database must be an existing SQLite RunStore file')
    try:
        with coherent_store(args.database) as (store, snapshot_interval):
            report = summarize(store, args.run_id, snapshot_interval)
    except Exception as error:
        parser.exit(1, f'Snapshot failed ({type(error).__name__}); check database, run identifier and RunStore integrity.\n')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'run_id': report['run_id'], 'state_version': report['state_version'], 'recorded_model_decisions': report['decisions']['recorded_model_decisions'], 'explicit_non_test_model_decisions': report['decisions']['explicit_non_test_model_decisions'], 'distinct_model_actors': report['decisions']['distinct_model_actors'], 'replay_matches': report['integrity']['replay_matches']}))

if __name__ == '__main__':
    main()
