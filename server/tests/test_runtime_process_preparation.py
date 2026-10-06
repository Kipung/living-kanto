"""Actual spawn workers prepare private observations without canonical writes."""
import json
import threading
import time

import pytest

from living_kanto.runtime import RuntimeController
from living_kanto.runtime.preparation import process_preparation_pool, prepare_in_process, preparation_mode
from living_kanto.simulation.world import WorldEngine
from living_kanto.store import RunStore
from test_runtime_shared import create_fixture_run, wait_until, response
from test_simulation_m0 import write_fixture_map


def fixture_world(tmp_path):
    write_fixture_map(tmp_path, width=14, height=14)
    engine = WorldEngine(tmp_path)
    store = RunStore(tmp_path / 'process.db')
    create_fixture_run(engine, store, 'process', ['alice', 'bob'])
    engine.commit_changes(store, 'process', [
        {'op': 'set', 'path': 'humans.alice.memory_summary', 'value': 'ALICE PRIVATE'},
        {'op': 'set', 'path': 'humans.bob.memory_summary', 'value': 'BOB PRIVATE'},
    ], kind='world.public_event', actor='engine', explanation='Identified TEST private memory setup',
        provenance={'kind': 'engine'}, expected_version=1)
    return engine, store


def test_spawn_capture_matches_parent_and_keeps_private_observation(tmp_path):
    engine, store = fixture_world(tmp_path)
    try:
        snapshot = store.load_run('process')[1]
        before = snapshot.to_dict()
        with process_preparation_pool(tmp_path, 2) as pool:
            futures = {actor: pool.submit(prepare_in_process, snapshot, actor) for actor in ['alice', 'bob']}
            for actor, future in futures.items():
                obs, token = future.result(timeout=20)
                expected_obs, expected_token = engine.capture_decision_boundary(snapshot, actor)
                assert obs.to_dict() == expected_obs.to_dict()
                assert token == expected_token
                text = json.dumps(obs.to_dict())
                assert actor.upper() + ' PRIVATE' in text
                assert ('BOB PRIVATE' if actor == 'alice' else 'ALICE PRIVATE') not in text
                assert 'world_facts' not in obs.to_dict() and 'humans' not in obs.to_dict()
        assert snapshot.to_dict() == before
        assert store.load_run('process')[1].state_version == snapshot.state_version
    finally:
        store.close()


class HeldTestProvider:
    model_id = 'identified-process-preparation-test'
    protocol = 'test'
    test_provider = True

    def __init__(self):
        self.release = threading.Event()
        self.lock = threading.Lock()
        self.calls = []

    def complete(self, observation, correction=None):
        with self.lock:
            self.calls.append(observation)
        assert self.release.wait(15), 'TEST provider hold timed out'
        return response()


def test_process_runtime_clock_pause_retirement_and_replay(tmp_path, monkeypatch):
    monkeypatch.setenv('LK_PREPARATION_MODE', 'process')
    engine, store = fixture_world(tmp_path)
    provider = HeldTestProvider()
    controller = RuntimeController(engine, store, 'process', provider, concurrency=2)
    try:
        controller.resume('1')
        wait_until(lambda: len(provider.calls) == 2, seconds=20)
        baseline = store.load_run('process')[1].simulated_time
        wait_until(lambda: store.load_run('process')[1].simulated_time > baseline, seconds=5)
        controller.pause()
        version = store.load_run('process')[1].state_version
        controller.resume('1')
        time.sleep(.1)
        assert len(provider.calls) == 2  # Retired requests occupy configured slots.
        provider.release.set()
        wait_until(lambda: controller.status()['accepted_decisions'] >= 2, seconds=20)
        controller.pause()
        assert controller.status()['cancelled_requests'] >= 2
        assert controller._preparation_mode == 'process'
        assert all(obs['observation_version'] >= version for obs in provider.calls[2:])
        state = store.load_run('process')[1]
        assert store.replay('process').state_hash == state.state_hash
        model_events = [event for event in store.iter_events('process')
                        if event.causation.get('provenance', {}).get('kind') == 'model']
        assert model_events
        assert all(event.causation['observation_version'] >= version for event in model_events)
    finally:
        provider.release.set()
        controller.close()
        store.close()


def test_preparation_mode_defaults_and_invalid_value(monkeypatch, tmp_path):
    monkeypatch.delenv('LK_PREPARATION_MODE', raising=False)
    assert preparation_mode() == 'thread'
    engine, store = fixture_world(tmp_path)
    try:
        monkeypatch.setenv('LK_PREPARATION_MODE', 'invalid')
        with pytest.raises(ValueError, match='LK_PREPARATION_MODE must be thread or process'):
            RuntimeController(engine, store, 'process', HeldTestProvider())
    finally:
        store.close()
