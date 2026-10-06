"""Bounded detached observation preparation, with identified TEST minds."""
import threading
import time

from living_kanto.runtime import RuntimeController
from living_kanto.simulation.world import WorldEngine
from living_kanto.store import RunStore
from test_runtime_shared import create_fixture_run, ConcurrentProvider, wait_until
from test_simulation_m0 import write_fixture_map


def test_parallel_preparation_does_not_hold_clock_or_pause_and_preserves_snapshot(tmp_path):
    write_fixture_map(tmp_path, width=14, height=14)
    engine = WorldEngine(tmp_path)
    store = RunStore(tmp_path / 'preparation.db')
    actors = ['alice', 'bob', 'carol', 'dave', 'erin']
    create_fixture_run(engine, store, 'prep', actors)
    provider = ConcurrentProvider()
    original = engine.capture_decision_boundary
    release = threading.Event()
    lock = threading.Lock()
    captures = []
    def blocked(snapshot, actor):
        before = snapshot.to_dict()
        with lock:
            captures.append((actor, snapshot, before))
        assert release.wait(15), 'TEST preparation release timed out'
        assert snapshot.to_dict() == before
        result = original(snapshot, actor)
        assert snapshot.to_dict() == before
        return result
    engine.capture_decision_boundary = blocked
    controller = RuntimeController(engine, store, 'prep', provider, concurrency=4)
    try:
        controller.resume('1')
        wait_until(lambda: len(captures) == 3)
        baseline = store.load_run('prep')[1].simulated_time
        wait_until(lambda: store.load_run('prep')[1].simulated_time > baseline, seconds=5)
        # Clock updates apply to fresh canonical objects, never worker snapshots.
        assert all(snapshot.to_dict() == before for _, snapshot, before in captures)
        started = time.monotonic()
        controller.pause()
        assert time.monotonic() - started < 1
        version = store.load_run('prep')[1].state_version
        controller.resume('1')
        time.sleep(.1)
        assert len(captures) == 3  # Retiring preparation retains the capacity.
        release.set()
        wait_until(lambda: len(captures) >= 6)
        wait_until(lambda: controller.status()['accepted_decisions'] > 0)
        controller.pause()
        assert len({actor for actor, _, _ in captures[:3]}) == 3
        assert 'erin' in {actor for actor, _, _ in captures[3:6]}  # Fair cursor continues after retirement.
        assert all(obs['observation_version'] >= version for obs, _ in provider.calls)
        state = store.load_run('prep')[1]
        assert store.replay('prep').state_hash == state.state_hash
    finally:
        release.set()
        controller.close()
        store.close()


def test_preparation_failure_pauses_without_requesting_model(tmp_path):
    write_fixture_map(tmp_path, width=14, height=14)
    engine = WorldEngine(tmp_path)
    store = RunStore(tmp_path / 'failed-preparation.db')
    create_fixture_run(engine, store, 'prep', ['alice'])
    provider = ConcurrentProvider()
    def broken(snapshot, actor):
        raise ValueError('TEST observation preparation failure')
    engine.capture_decision_boundary = broken
    controller = RuntimeController(engine, store, 'prep', provider, concurrency=1)
    try:
        controller.resume('1')
        wait_until(lambda: controller.status()['failure'] is not None)
        status = controller.status()
        assert not status['running']
        assert status['failure']['human_id'] == 'alice'
        assert 'TEST observation preparation failure' in status['failure']['reason']
        assert provider.calls == []
        assert status['accepted_decisions'] == 0
    finally:
        controller.close()
        store.close()
