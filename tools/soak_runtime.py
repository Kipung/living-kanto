#!/usr/bin/env python3
"""Bounded actual-model world soak; never substitutes scripted decisions."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
from living_kanto.runtime import LocalModelConfig, LocalModelProvider, RuntimeController
from living_kanto.simulation.world import WorldEngine
from living_kanto.store import RunStore


def fingerprints():
    paths = list((ROOT / "server/living_kanto").rglob("*.py")) + list((ROOT / "content").rglob("*.json")) + list((ROOT / "server").rglob("*.cjs"))
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths) if "node_modules" not in path.parts}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database', required=True)
    p.add_argument('--run-id', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--seconds', type=float, default=7200)
    p.add_argument('--seed', type=int, default=123)
    p.add_argument('--concurrency', type=int, choices=range(1, 9), default=1)
    args = p.parse_args()
    if args.seconds <= 0:
        p.error('seconds must be positive')
    db, output = Path(args.database), Path(args.output)
    if db.exists():
        p.error('Use a fresh database for an auditable zero-event soak')
    db.parent.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    engine, store = WorldEngine(ROOT / 'content'), RunStore(db)
    state = engine.initialize(store, args.run_id, args.seed, 'observer')
    runtime = RuntimeController(engine, store, args.run_id,
                                LocalModelProvider(LocalModelConfig.from_env()), concurrency=args.concurrency)
    start = time.monotonic()
    report = {'run_id': args.run_id, 'requested_seconds': args.seconds,
              'initial_hash': state.state_hash, 'initial_population': 100,
              'model': runtime.provider.model_id, 'accepted_decisions': 0,
              'actors_observed': [], 'failures': [], 'complete': False,
              'release_verified': False, 'champion_trial_verified': False}
    report['source_files_sha256'] = fingerprints()
    report['accepted_events'] = 0
    report['engine_continuations'] = 0
    actors = set()

    def save():
        current = store.load_run(args.run_id)[1]
        replay = store.replay(args.run_id)
        # RunStore.replay returns the reconstructed WorldState.
        report.update(elapsed_seconds=time.monotonic() - start,
                      final_hash=current.state_hash,
                      replay_hash=replay.state_hash,
                      replay_matches=replay.state_hash == current.state_hash,
                      state_version=current.state_version,
                      simulated_time=current.simulated_time,
                      actors_observed=sorted(actors), runtime=runtime.status())
        final_fingerprints = fingerprints()
        report['source_changed_during_run'] = final_fingerprints != report['source_files_sha256']
        report['changed_source_files'] = sorted(key for key in set(final_fingerprints) | set(report['source_files_sha256']) if final_fingerprints.get(key) != report['source_files_sha256'].get(key))
        report['final_source_files_sha256'] = final_fingerprints
        report['current_source_soak_verified'] = bool(report['complete'] and report['replay_matches'] and not report['source_changed_during_run'])
        temp = output.with_suffix('.tmp')
        temp.write_text(json.dumps(report, indent=2) + '\n')
        temp.replace(output)

    try:
        while time.monotonic() - start < args.seconds:
            result = runtime.step()
            if not result.get('accepted'):
                report['failures'].append(result)
                break
            report['accepted_events'] += 1
            event = store.iter_events(args.run_id)[-1]
            cause = event.causation
            decisions = cause.get('decisions', [])
            model_actors = [d['human_id'] for d in decisions if d.get('provenance', {}).get('kind') == 'model']
            if cause.get('provenance', {}).get('kind') == 'model' and not result.get('engine_continuation'):
                model_actors.append(cause['human_id'])
            report['accepted_decisions'] += len(model_actors)
            report['engine_continuations'] += not bool(model_actors)
            actors.update(model_actors)
            if report['accepted_events'] % 10 == 0:
                save()
                print(json.dumps({'accepted': report['accepted_decisions'],
                                  'actors': len(actors), 'elapsed': report['elapsed_seconds']}), flush=True)
        report['complete'] = not report['failures'] and time.monotonic() - start >= args.seconds
    except (Exception, KeyboardInterrupt) as exc:
        report['failures'].append({'reason': str(exc), 'type': type(exc).__name__})
    finally:
        runtime.close()
        save()
        store.close()
    print(json.dumps({'report': str(output), 'complete': report['complete'],
                      'accepted': report['accepted_decisions']}), flush=True)


if __name__ == '__main__':
    main()
