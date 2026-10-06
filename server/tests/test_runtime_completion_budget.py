"""Slow atomic commits must not monopolize the shared clock or pause control."""
import threading
import time

from living_kanto.runtime import RuntimeController
from living_kanto.simulation.world import WorldEngine
from living_kanto.store import RunStore
from test_runtime_shared import create_fixture_run, ConcurrentProvider, response, wait_until
from test_simulation_m0 import write_fixture_map


def test_simultaneous_completion_backlog_yields_to_clock_and_pause(tmp_path):
    write_fixture_map(tmp_path, width=14, height=14)
    engine = WorldEngine(tmp_path)
    store = RunStore(tmp_path / 'drain.db')
    actors = [f'person-{i}' for i in range(8)]
    create_fixture_run(engine, store, 'drain', actors)
    class HeldProvider(ConcurrentProvider):
        def complete(self, observation, correction=None):
            with self.lock:
                self.calls.append((observation, correction))
                self.active += 1
            try:
                assert self.release.wait(15)
                return response('rest')
            finally:
                with self.lock: self.active -= 1
    provider = HeldProvider()
    original_commit = engine.commit
    original_tick = engine.tick_shared_time
    tick_model_counts = []
    committing = threading.Event()
    def slow_commit(store, event):
        if event.causation.get('provenance', {}).get('kind') == 'model':
            committing.set()
            time.sleep(.25)
        return original_commit(store, event)
    def tick(store, run_id, target):
        state = store.load_run(run_id)[1]
        count = sum(h.get('last_decision', {}).get('provenance', {}).get('kind') == 'model'
                    for h in state.humans.values())
        event = original_tick(store, run_id, target)
        if event: tick_model_counts.append(count)
        return event
    engine.commit = slow_commit
    engine.tick_shared_time = tick
    controller = RuntimeController(engine, store, 'drain', provider, concurrency=8)
    try:
        controller.resume('1')
        wait_until(lambda: provider.active == 5)  # 2 slow-thought slots and 1 urgent slot remain reserved.
        provider.release.set()
        wait_until(lambda: any(0 < count < 8 for count in tick_model_counts), seconds=10)
        # A new in-progress atomic commit cannot hold pause behind all remaining
        # answers. At most that current commit finishes before cancellation.
        committing.clear()
        assert committing.wait(5)
        started = time.monotonic()
        controller.pause()
        assert time.monotonic() - started < .7
        assert controller.status()['accepted_decisions'] < 8
        version = store.load_run('drain')[1].state_version
        time.sleep(.1)
        assert store.load_run('drain')[1].state_version == version
        state = store.load_run('drain')[1]
        assert store.replay('drain').state_hash == state.state_hash
    finally:
        provider.release.set()
        controller.close()
        store.close()
