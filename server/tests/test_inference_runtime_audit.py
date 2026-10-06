"""Explicit TEST proposals verify observer traces track engine outcomes."""
import json
from concurrent.futures import Future
import pytest
from living_kanto.runtime import RuntimeController, LocalModelConfig, LocalModelProvider
from test_runtime_shared import shared_world

class TracedTestProvider(LocalModelProvider):
    test_provider = True
    def __init__(self, action='wait'):
        super().__init__(LocalModelConfig('http://127.0.0.1:9999/v1', 'audit-test-only'))
        self.action = action
    def _infer(self, messages, schema=None):
        return json.dumps({'action': self.action, 'arguments': {}, 'decision_explanation': 'Explicit TEST proposal.'})


def test_manual_shared_trace_links_to_committed_event(shared_world):
    engine, store = shared_world
    engine.activate_shared_clock(store, 'shared')
    provider = TracedTestProvider()
    runtime = RuntimeController(engine, store, 'shared', provider)
    try:
        result = runtime.step('alice')
        assert result['accepted']
        trace = provider._trace_sink.records('alice')[0]
        assert trace['outcome'] == 'accepted'
        assert trace['event_id'] == result['event_id']
        assert trace['state_version'] == result['state_version']
        assert 'trace_id' not in json.dumps(engine.observation_for(store.load_run('shared')[1], 'alice').to_dict())
        assert store.replay('shared').state_hash == store.load_run('shared')[1].state_hash
    finally:
        runtime.close()


def test_manual_rejected_trace_does_not_claim_acceptance(shared_world):
    engine, store = shared_world
    engine.activate_shared_clock(store, 'shared')
    provider = TracedTestProvider('invented_action')
    runtime = RuntimeController(engine, store, 'shared', provider)
    before = store.load_run('shared')[1].state_version
    try:
        result = runtime.step('alice')
        assert not result['accepted']
        assert store.load_run('shared')[1].state_version == before
        traces = provider._trace_sink.records('alice')
        assert len(traces) == 2
        assert all(t['outcome'] == 'engine_rejected' and not t.get('event_id') for t in traces)
        assert traces[0]['corrective_retry']
    finally:
        runtime.close()


def test_async_trace_links_parsed_choice(shared_world):
    engine, store = shared_world
    engine.activate_shared_clock(store, 'shared')
    provider = TracedTestProvider()
    runtime = RuntimeController(engine, store, 'shared', provider)
    try:
        obs, token = engine.capture_decision_boundary(store.load_run('shared')[1], 'alice')
        raw = provider.complete(obs.to_dict())
        future = Future(); future.set_result(runtime._parse(raw, obs))
        runtime._async_jobs['alice'] = {'phase':'inference', 'future':future, 'observation':obs,
            'actor':'alice', 'token':token, 'generation':runtime._generation, 'sequence':1,
            'attempt':0, 'started':__import__('time').monotonic()}
        store.set_status('shared', 'running')
        runtime._complete_human_requests()
        trace = provider._trace_sink.records('alice')[0]
        assert trace['outcome'] == 'accepted'
        assert trace['event_id']
        assert runtime.status()['inference_audit']['records'] == 1
    finally:
        runtime.close()


def test_pause_marks_finished_uncommitted_proposal_cancelled(shared_world):
    engine, store = shared_world
    engine.activate_shared_clock(store, 'shared')
    provider = TracedTestProvider()
    runtime = RuntimeController(engine, store, 'shared', provider)
    try:
        obs, token = engine.capture_decision_boundary(store.load_run('shared')[1], 'alice')
        raw = provider.complete(obs.to_dict())
        future = Future(); future.set_result(runtime._parse(raw, obs))
        runtime._async_jobs['alice'] = {'phase':'inference', 'future':future, 'observation':obs,
            'actor':'alice', 'token':token, 'generation':runtime._generation, 'sequence':1,
            'attempt':0, 'started':__import__('time').monotonic()}
        before = store.load_run('shared')[1].state_version
        runtime.pause()
        trace = provider._trace_sink.records('alice')[0]
        assert trace['outcome'] == 'cancelled' and not trace.get('event_id')
        assert store.load_run('shared')[1].state_version == before
    finally:
        runtime.close()
