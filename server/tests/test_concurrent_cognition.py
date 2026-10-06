"""Identified test minds: slow thought must not occupy a person's action slot."""
import json
import threading
import pytest
from living_kanto.runtime import RuntimeController
from living_kanto.simulation import cognition
from living_kanto.simulation.engine import StaleActionError
from test_runtime_shared import shared_world, wait_until, response, ConcurrentProvider


def activate(engine, store):
    engine.activate_shared_clock(store, 'shared'); store.set_status('shared', 'running')


def choose(engine, store, actor, action, args=None):
    obs, token = engine.capture_decision_boundary(store.load_run('shared')[1], actor)
    event, _ = engine.build_revalidated_action_event(store, 'shared', actor,
        {'action': action, 'arguments': args or {}, 'decision_explanation': 'Identified test choice'},
        obs.observation_version, token, {'kind': 'model', 'model_id': 'test-only', 'test_provider': True})
    engine.commit(store, event)
    return event


def test_background_thought_preserves_activity_and_replays(shared_world):
    engine, store = shared_world; activate(engine, store); choose(engine, store, 'alice', 'rest')
    before = store.load_run('shared')[1]; obs, token = cognition.capture(engine, before, 'alice')
    thought = {'action': 'remember', 'arguments': {'text': 'Consider visiting the lab after rest.'}, 'decision_explanation': 'Reflect while resting'}
    event, _ = cognition.build_event(engine, store, 'shared', 'alice', thought, obs, token,
                                   {'kind': 'model', 'model_id': 'test-only', 'test_provider': True})
    engine.commit(store, event); after = store.load_run('shared')[1]
    for key in ('activity', 'ready_at', 'last_decision', 'individual_life', 'memories'):
        assert after.humans['alice'].get(key) == before.humans['alice'].get(key)
    assert after.simulated_time == before.simulated_time
    assert after.humans['alice']['cognition']['latest']['execution_authorized'] is False
    assert engine.observation_for(after, 'bob').self_state['cognition']['latest'] is None
    assert store.replay('shared').state_hash == after.state_hash


def test_delivered_speech_supersedes_background_thought(shared_world):
    engine, store = shared_world; activate(engine, store); choose(engine, store, 'alice', 'rest')
    obs, token = cognition.capture(engine, store.load_run('shared')[1], 'alice')
    choose(engine, store, 'bob', 'talk_to', {'human_id': 'alice', 'text': 'Where are you going next?'})
    with pytest.raises(StaleActionError):
        cognition.build_event(engine, store, 'shared', 'alice',
            {'action': 'remember', 'arguments': {'text': 'An old thought'}, 'decision_explanation': 'test'}, obs, token, {})


def test_reply_during_rest_keeps_deadline_and_activity(shared_world):
    engine, store = shared_world; activate(engine, store); choose(engine, store, 'alice', 'rest')
    before = store.load_run('shared')[1].humans['alice']
    choose(engine, store, 'bob', 'talk_to', {'human_id': 'alice', 'text': 'Hello, can we talk?'})
    state = store.load_run('shared')[1]
    assert engine.shared_actor_ready(state, 'alice')
    option = engine.immediate_reply_actions(state, 'alice')[0]
    choose(engine, store, 'alice', 'respond_to', {**option.arguments, 'text': 'Yes, I am resting.'})
    after = store.load_run('shared')[1].humans['alice']
    assert after['activity'] == before['activity'] and after['ready_at'] == before['ready_at']
    assert after['last_decision']['action'] == 'respond_to'
    assert not engine.immediate_reply_actions(store.load_run('shared')[1], 'alice')


def test_slow_thought_does_not_block_same_person_reply(shared_world):
    engine, store = shared_world; activate(engine, store); choose(engine, store, 'alice', 'rest')
    class ThinkingProvider(ConcurrentProvider):
        def __init__(self):
            super().__init__(); self.thinking = threading.Event()
        def complete(self, observation, correction=None):
            if observation['self_state'].get('cognitive_mode') == 'background_deliberation':
                self.thinking.set(); assert self.release.wait(15)
                return response('remember', {'text': 'I can decide my next destination after resting.'})
            offered = observation['legal_actions']
            reply = next((a for a in offered if a['action'] == 'respond_to'), None)
            if reply: return response('respond_to', {**reply['arguments'], 'text': 'I can answer while resting.'})
            return response()
    provider = ThinkingProvider(); controller = RuntimeController(engine, store, 'shared', provider, actor_ids=['alice'], concurrency=4)
    try:
        controller.resume('1'); wait_until(provider.thinking.is_set)
        with controller.shared_lock:
            choose(engine, store, 'bob', 'talk_to', {'human_id': 'alice', 'text': 'What are you doing?'})
            controller._wake.set()
        wait_until(lambda: store.load_run('shared')[1].humans['alice']['last_decision']['action'] == 'respond_to')
        assert not provider.release.is_set()
        assert store.load_run('shared')[1].humans['alice']['activity']['kind'] == 'rest'
        provider.release.set(); wait_until(lambda: controller.status()['stale_deliberations'] == 1)
        assert controller.status()['failure'] is None
    finally:
        provider.release.set(); controller.close()


def test_reply_survives_tile_progress_and_preserves_movement(shared_world):
    engine, store = shared_world; activate(engine, store)
    engine.maps['PalletTown'].source_revision = 'identified-test-source'
    initial = store.load_run('shared')[1].humans['alice']
    choose(engine, store, 'alice', 'travel_to', {'x': initial['x'], 'y': initial['y'] + 3})
    choose(engine, store, 'bob', 'talk_to', {'human_id': 'alice', 'text': 'Can you hear me?'})
    obs, token = engine.capture_decision_boundary(store.load_run('shared')[1], 'alice')
    option = engine.immediate_reply_actions(store.load_run('shared')[1], 'alice')[0]
    engine.tick_shared_time(store, 'shared', 1)
    before = store.load_run('shared')[1]; intent = before.humans['alice']['movement_intent']
    event, _ = engine.build_revalidated_action_event(store, 'shared', 'alice',
        {'action': 'respond_to', 'arguments': {**option.arguments, 'text': 'Yes, I am walking.'}, 'decision_explanation': 'test reply'},
        obs.observation_version, token, {'kind': 'model', 'model_id': 'test-only', 'test_provider': True})
    engine.commit(store, event)
    assert store.load_run('shared')[1].humans['alice']['movement_intent'] == intent
    assert event.causation['observation_version'] < event.state_version


def test_pause_retires_thought_without_late_commit(shared_world):
    engine, store = shared_world; activate(engine, store); choose(engine, store, 'alice', 'rest')
    class HeldThought(ConcurrentProvider):
        def __init__(self): super().__init__(); self.thinking = threading.Event()
        def complete(self, observation, correction=None):
            self.thinking.set(); assert self.release.wait(15)
            return response('remember', {'text': 'A held test thought.'})
    provider = HeldThought(); controller = RuntimeController(engine, store, 'shared', provider, actor_ids=['alice'], concurrency=4)
    try:
        controller.resume('1'); wait_until(provider.thinking.is_set); controller.pause()
        version = store.load_run('shared')[1].state_version
        provider.release.set(); wait_until(lambda: all(j['future'].done() for j in controller._thought_jobs.values()))
        controller._pump_deliberation(store.load_run('shared')[1])
        assert store.load_run('shared')[1].state_version == version
        assert controller.status()['accepted_deliberations'] == 0
        assert controller.status()['deliberation_failure'] is None
    finally:
        provider.release.set(); controller.close()


def test_invalid_background_action_cannot_execute(shared_world):
    engine, store = shared_world; activate(engine, store); choose(engine, store, 'alice', 'rest')
    before = store.load_run('shared')[1]; obs, token = cognition.capture(engine, before, 'alice')
    from living_kanto.simulation.engine import EngineError
    with pytest.raises(EngineError):
        cognition.build_event(engine, store, 'shared', 'alice', {'action': 'cancel_activity', 'arguments': {},
            'decision_explanation': 'Not a thought'}, obs, token, {})
    assert store.load_run('shared')[1].state_hash == before.state_hash


def test_urgent_reply_runs_while_ordinary_slots_are_saturated(tmp_path):
    from test_runtime_shared import create_fixture_run
    from test_simulation_m0 import write_fixture_map
    from living_kanto.simulation.world import WorldEngine
    from living_kanto.store import RunStore
    write_fixture_map(tmp_path, width=14, height=14)
    engine = WorldEngine(tmp_path); store = RunStore(tmp_path/'urgent.db')
    create_fixture_run(engine, store, 'shared', ['alice', 'bob', 'carol', 'dave', 'eve', 'frank', 'grace'])
    activate(engine, store); choose(engine, store, 'alice', 'rest')
    class Saturated(ConcurrentProvider):
        def complete(self, observation, correction=None):
            reply = next((a for a in observation['legal_actions'] if a['action'] == 'respond_to'), None)
            with self.lock: self.calls.append((observation, correction))
            if reply: return response('respond_to', {**reply['arguments'], 'text': 'Yes, I can answer now.'})
            assert self.release.wait(15)
            if observation['self_state'].get('cognitive_mode') == 'background_deliberation':
                return response('remember', {'text': 'A background thought.'})
            return response()
    provider = Saturated(); controller = RuntimeController(engine, store, 'shared', provider, concurrency=8)
    try:
        controller.resume('1')
        wait_until(lambda: sum(obs['self_state'].get('cognitive_mode') != 'background_deliberation' for obs, _ in provider.calls) == 5)
        with controller.shared_lock:
            choose(engine, store, 'bob', 'talk_to', {'human_id': 'alice', 'text': 'Can you answer now?'})
            controller._wake.set()
        wait_until(lambda: store.load_run('shared')[1].humans['alice']['last_decision']['action'] == 'respond_to')
        assert not provider.release.is_set()
        assert controller.status()['failure'] is None
    finally:
        provider.release.set(); controller.close(); store.close()


def test_conditional_plan_does_not_replace_task_or_execute(shared_world):
    engine, store = shared_world; activate(engine, store); choose(engine, store, 'alice', 'rest')
    before = store.load_run('shared')[1]; obs, token = cognition.capture(engine, before, 'alice')
    plan = next(a for a in obs.legal_actions if a.action == 'plan_next_step')
    choice = {'action': plan.action, 'arguments': {**plan.arguments, 'text': 'Consider this after my current rest.'},
              'decision_explanation': 'An explicitly conditional test plan'}
    event, _ = cognition.build_event(engine, store, 'shared', 'alice', choice, obs, token,
        {'kind': 'model', 'model_id': 'test-only', 'test_provider': True})
    engine.commit(store, event); after = store.load_run('shared')[1]
    assert after.humans['alice'].get('individual_life') == before.humans['alice'].get('individual_life')
    assert after.humans['alice']['activity'] == before.humans['alice']['activity']
    assert after.humans['alice']['cognition']['latest']['kind'] == 'conditional_plan'
    assert store.replay('shared').state_hash == after.state_hash


def test_optional_thought_failure_does_not_pause_execution(shared_world):
    engine, store = shared_world; activate(engine, store); choose(engine, store, 'alice', 'rest')
    from living_kanto.runtime.providers import ProviderError
    class FailedThought(ConcurrentProvider):
        def complete(self, observation, correction=None): raise ProviderError('Identified test thought endpoint failure')
    controller = RuntimeController(engine, store, 'shared', FailedThought(), actor_ids=['alice'], concurrency=4)
    try:
        controller.resume('1'); wait_until(lambda: controller.status()['deliberation_failure'] is not None)
        assert controller.status()['running'] and controller.status()['failure'] is None
        assert store.load_run('shared')[1].humans['alice']['activity']['kind'] == 'rest'
        assert controller.status()['accepted_deliberations'] == 0
    finally: controller.close()
