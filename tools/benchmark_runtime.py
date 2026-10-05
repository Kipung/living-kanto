#!/usr/bin/env python3
"""Benchmark a configured local human endpoint against an existing paused save.

Does not create saves, start models, or commit decisions. Sample private battle
and everyday observations from the supplied run, validate every accepted choice
against the authoritative engine, and emit a reviewable capacity report.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from living_kanto.runtime import LocalModelConfig, LocalModelProvider
from living_kanto.runtime.benchmark import benchmark_provider
from living_kanto.simulation.world import WorldEngine
from living_kanto.store import RunStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--content-root', default='content')
    parser.add_argument('--output', required=True)
    parser.add_argument('--requests-per-level', type=int, default=16)
    parser.add_argument('--observations', type=int, default=8)
    parser.add_argument('--humans', nargs='*', help='Explicit private-observation actor IDs')
    args = parser.parse_args()
    database = Path(args.database)
    if not database.is_file():
        parser.error('Database must be an existing paused save')
    engine = WorldEngine(args.content_root)
    provider = LocalModelProvider(LocalModelConfig.from_env())
    store = RunStore(database)
    try:
        _, state, _ = store.load_run(args.run_id)
        if store.get_status(args.run_id) != 'paused':
            parser.error('Pause this run before benchmarking; world state must remain unchanged')
        before_hash = state.state_hash
        actors = args.humans or sorted(state.humans, key=lambda actor: (not bool(state.humans[actor].get('battle_id')), actor))
        observations = []
        for actor in actors:
            if actor == 'player':
                continue
            obs = engine.observation_for(state, actor)
            if obs.legal_actions:
                observations.append(obs)
            if len(observations) >= args.observations:
                break
        report = benchmark_provider(provider, observations, args.requests_per_level, engine=engine, store=store)
        after = store.load_run(args.run_id)[1]
        if after.state_hash != before_hash:
            raise RuntimeError('Run changed during benchmark; results cannot be trusted')
        report.update({'run_id': args.run_id, 'state_hash': before_hash, 'committed_world_changes': 0,
                       'source_reference': '037335f4c725d7c9aecdac87066f2002b4bd7e14',
                       'release_capacity_verified': False,
                       'missing_release_metrics': ['endpoint memory usage', 'actual simulated time per wall-clock minute']})
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'report': str(target), 'recommended_concurrency': report['recommended_concurrency'],
                          'battle_observations': report['battle_observation_count']}))
    finally:
        store.close()


if __name__ == '__main__':
    main()
