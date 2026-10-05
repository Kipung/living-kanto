"""Runtime tests use explicitly identified scripted providers, never release evidence."""
import json
import threading
from pathlib import Path

import pytest

from living_kanto.runtime import RuntimeController, LocalModelConfig, ProviderError
from living_kanto.simulation import SimulationEngine, GameMap
from living_kanto.store.run_store import RunStore
from test_simulation_m0 import write_fixture_map


class TestProvider:
    __test__ = False
    model_id = "scripted-runtime-test-only"
    protocol = "test"
    test_provider = True

    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = []

    def complete(self, observation, correction=None):
        self.calls.append((observation, correction))
        output = next(self.outputs)
        if isinstance(output, Exception):
            raise output
        return output


def action(name="wait", arguments=None):
    return json.dumps({"action": name, "arguments": arguments or {},
                       "decision_explanation": "I choose to pause and consider my goal."})


@pytest.fixture
def runtime(tmp_path):
    engine = SimulationEngine({"pallet-town": GameMap.from_content("pallet-town", write_fixture_map(tmp_path))})
    store = RunStore(tmp_path / "world.sqlite")
    engine.create_run(store, run_id="runtime-test", humans=[("alice", "Alice"), ("bob", "Bob")])
    controller = RuntimeController(engine, store, "runtime-test", TestProvider([action(), action()]))
    yield controller
    controller.close()
    store.close()


def test_atomic_explanation_and_inference_free_replay(runtime):
    assert runtime.status()["phase"] == "paused"
    assert runtime.step()["accepted"]
    event = runtime.store.iter_events(runtime.run_id)[0]
    assert event.causation["decision_explanation"].startswith("I choose")
    assert event.causation["provenance"]["test_provider"] is True
    _, committed, _ = runtime.store.load_run(runtime.run_id)
    assert committed.humans["alice"]["last_decision"]["explanation"].startswith("I choose")
    assert committed.simulated_time == 1
    assert runtime.store.replay(runtime.run_id).state_hash == committed.state_hash
    assert len(runtime.provider.calls) == 1
    assert runtime.store.get_status(runtime.run_id) == "paused"


def test_one_corrective_retry_and_actor_rotation(runtime):
    runtime.provider = TestProvider(["bad JSON", action(), action()])
    assert runtime.step()["accepted"]
    assert runtime.step()["accepted"]
    assert runtime.provider.calls[1][1]
    assert runtime.provider.calls[2][0]["human_id"] == "bob"
    assert runtime.status()["corrective_retries"] == 1


@pytest.mark.parametrize("outputs", [[action("become_champion"), action("become_champion")],
                                     [ProviderError("Endpoint unavailable")]])
def test_failure_preserves_committed_state_and_same_boundary(runtime, outputs):
    _, before, _ = runtime.store.load_run(runtime.run_id)
    runtime.provider = TestProvider(outputs)
    result = runtime.step()
    assert not result["accepted"]
    assert runtime.status()["failure"]["human_id"] == "alice"
    assert runtime.store.event_count(runtime.run_id) == 0
    assert runtime.store.load_run(runtime.run_id)[1].state_hash == before.state_hash
    runtime.provider = TestProvider([action()])
    assert runtime.step()["accepted"]
    assert runtime.provider.calls[0][0]["human_id"] == "alice"


def test_pause_discards_inflight_model_result(runtime):
    entered, release = threading.Event(), threading.Event()
    class BlockingProvider(TestProvider):
        def complete(self, observation, correction=None):
            entered.set()
            assert release.wait(2)
            return action()
    runtime.provider = BlockingProvider([])
    results = []
    thread = threading.Thread(target=lambda: results.append(runtime.step()))
    thread.start()
    assert entered.wait(2)
    runtime.pause()
    release.set()
    thread.join(2)
    assert results == [{"accepted": False, "cancelled": True}]
    assert runtime.store.event_count(runtime.run_id) == 0


def test_local_configuration_blocks_public_endpoint():
    with pytest.raises(ProviderError, match="Cloud/public"):
        LocalModelConfig("https://8.8.8.8/v1", "model").validate()
    assert LocalModelConfig("http://127.0.0.1:11434", "model", "ollama").validate()

@pytest.mark.parametrize("protocol,path", [("openai", "/v1/chat/completions"), ("ollama", "/api/chat")])
def test_local_http_provider_contract(protocol, path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from living_kanto.runtime import LocalModelProvider
    captured = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            captured.append((self.path, body))
            result = {"choices": [{"message": {"content": action()}}]} if protocol == "openai" else {"message": {"content": action()}}
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        provider = LocalModelProvider(LocalModelConfig(f"http://127.0.0.1:{server.server_port}", "local-test", protocol, timeout_seconds=2))
        assert json.loads(provider.complete({"human_id": "alice"}, correction="bad action"))["action"] == "wait"
        assert captured[0][0] == path
        assert captured[0][1]["model"] == "local-test"
        assert captured[0][1]["stream"] is False
        if protocol == "openai":
            assert captured[0][1]["chat_template_kwargs"] == {"enable_thinking": False}
        assert "bad action" in captured[0][1]["messages"][-1]["content"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)

def test_reconfigured_provider_cannot_commit_old_inflight_result(runtime):
    entered, release = threading.Event(), threading.Event()
    class OldProvider(TestProvider):
        def complete(self, observation, correction=None):
            entered.set()
            assert release.wait(2)
            return action()
    runtime.provider = OldProvider([])
    results = []
    thread = threading.Thread(target=lambda: results.append(runtime.step()))
    thread.start()
    assert entered.wait(2)
    runtime.pause()
    with runtime.shared_lock:
        runtime.provider = TestProvider([action()])
    # Reconfiguration follows pause; do not start background worker until old request settles.
    release.set()
    thread.join(2)
    assert results == [{'accepted': False, 'cancelled': True}]
    assert runtime.step()['accepted']
    assert runtime.store.event_count(runtime.run_id) == 1
    assert len(runtime.provider.calls) == 1

def test_scheduler_skips_actor_with_pending_choice(runtime):
    original = runtime.engine.observation_for
    def observation(state, human_id):
        obs = original(state, human_id)
        if human_id == 'alice':
            obs.legal_actions = ()
        return obs
    runtime.engine.observation_for = observation
    assert runtime.step()['accepted']
    assert runtime.provider.calls[0][0]['human_id'] == 'bob'


def test_player_boundary_pauses_without_any_model_call(runtime):
    runtime.engine.runtime_blocker = lambda state: {'human_id':'player','reason':'Player battle input required'}
    result = runtime.step()
    assert not result['accepted']
    assert runtime.status()['phase'] == 'paused'
    assert runtime.status()['failure']['human_id'] == 'player'
    assert len(runtime.provider.calls) == 0
    assert runtime.store.event_count(runtime.run_id) == 0

def test_benchmark_engine_validates_arguments_without_mutation(runtime):
    from living_kanto.runtime.benchmark import benchmark_provider
    runtime.provider = TestProvider([action('walk_to', {'direction':'invented'})] * 16)
    obs = runtime.engine.get_observation(runtime.store, runtime.run_id, 'alice')
    before = runtime.store.load_run(runtime.run_id)[1].state_hash
    report = benchmark_provider(runtime.provider, [obs], requests_per_level=8, engine=runtime.engine, store=runtime.store)
    assert report['engine_arguments_validated']
    assert report['levels'][0]['failures'] == 8
    assert report['levels'][0]['corrective_retries'] == 8
    assert report['recommended_concurrency'] is None
    assert runtime.store.event_count(runtime.run_id) == 0
    assert runtime.store.load_run(runtime.run_id)[1].state_hash == before

def test_restart_restores_scheduler_from_atomic_model_receipt(runtime):
    assert runtime.step()['accepted']
    runtime.close()
    provider = TestProvider([action()])
    resumed = RuntimeController(runtime.engine, runtime.store, runtime.run_id, provider)
    try:
        assert resumed.status()['phase'] == 'paused'
        assert resumed.step()['accepted']
        assert provider.calls[0][0]['human_id'] == 'bob'
        assert runtime.store.replay(runtime.run_id).state_hash == runtime.store.load_run(runtime.run_id)[1].state_hash
    finally:
        resumed.close()

@pytest.mark.parametrize('operation', ['load_run', 'replay'])
def test_independent_store_reader_has_consistent_snapshot(runtime, operation, monkeypatch):
    reader = RunStore(runtime.store.path)
    writer = runtime.store
    writer.set_status(runtime.run_id, 'running')
    before = writer.load_run(runtime.run_id)[1]
    original = reader._get_run_row
    triggered = []
    def interleave(run_id):
        row = original(run_id)
        if not triggered:
            triggered.append(True)
            event, _ = runtime.engine.build_action_event(writer, run_id, 'alice', action='wait', arguments={},
                observation_version=0, expected_state_version=0, decision_explanation='Concurrent write fixture',
                decision_provenance={'kind':'model','model_id':'scripted-test-only'})
            runtime.engine.commit(writer, event)
        return row
    monkeypatch.setattr(reader, '_get_run_row', interleave)
    try:
        loaded = getattr(reader, operation)(runtime.run_id)
        old = loaded[1] if operation == 'load_run' else loaded
        assert old.state_hash == before.state_hash
        if operation == 'load_run':
            assert loaded[2] == '0' * 64
        assert reader.load_run(runtime.run_id)[1].state_version == 1
        assert not reader._db.in_transaction
    finally:
        reader.close()

@pytest.mark.parametrize('external', [False, True])
def test_verified_cache_rejects_event_tampering(runtime, external):
    from living_kanto.store import StoreError
    import sqlite3
    assert runtime.step()['accepted']
    runtime.store.load_run(runtime.run_id) # populate strict cache
    connection=sqlite3.connect(runtime.store.path) if external else runtime.store._db
    row=connection.execute('SELECT event_json FROM events WHERE run_id=?',(runtime.run_id,)).fetchone()
    event=json.loads(row[0]);event['causation']['decision_explanation']='Tampered receipt'
    connection.execute('UPDATE events SET event_json=? WHERE run_id=?',(json.dumps(event),runtime.run_id));connection.commit()
    try:
        for _ in range(2):
            with pytest.raises(StoreError):runtime.store.load_run(runtime.run_id)
        with pytest.raises(StoreError):runtime.store.replay(runtime.run_id)
    finally:
        if external:connection.close()


def test_verified_cache_returns_independent_state_and_explicit_replay_audits(runtime, monkeypatch):
    assert runtime.step()['accepted']
    original=runtime.store.replay;calls=[]
    def audited(run_id):
        calls.append(run_id);return original(run_id)
    monkeypatch.setattr(runtime.store,'replay',audited)
    first=runtime.store.load_run(runtime.run_id)[1]
    count=len(calls)
    first.humans['alice']['last_decision']['provenance']['model_id']='Mutated caller copy'
    second=runtime.store.load_run(runtime.run_id)[1]
    assert second.humans['alice']['last_decision']['provenance']['model_id']=='scripted-runtime-test-only'
    assert len(calls)==count
    runtime.store.replay(runtime.run_id)
    assert len(calls)==count+1

@pytest.mark.parametrize('blocked',[False,True])
def test_persisted_journey_continues_without_inference_or_pauses_on_block(tmp_path,blocked):
    from living_kanto.contracts.human import LegalAction
    class JourneyFixtureEngine(SimulationEngine):
        def legal_actions(self,state,hid):
            base=super().legal_actions(state,hid)
            return base+(LegalAction(action='journey_to',arguments={'map_id':'destination'},known_consequences={}),)
    home=GameMap('pallet-town',150,8,['1'*150]*8,{(149,5):'destination'},events={'connections':[{'direction':'right','map':'destination','offset':0}]})
    dest=GameMap('destination',5,8,['11111']*8,{})
    engine=JourneyFixtureEngine({'pallet-town':home,'destination':dest})
    db=tmp_path/'journey.sqlite';store=RunStore(db)
    engine.create_run(store,run_id='journey-test',humans=[('alice','Alice')])
    provider=TestProvider([action('journey_to',{'map_id':'destination'})])
    first=RuntimeController(engine,store,'journey-test',provider)
    assert first.step()['accepted']
    current=store.load_run('journey-test')[1];plan=current.humans['alice']['active_plan']
    assert plan['kind']=='journey' and plan['accepted_state_version']==0
    assert len(provider.calls)==1
    first.close();store.close()
    if blocked:
        # A changed physical obstacle makes the old accepted route unavailable.
        for row in home._walk:row[140]=False
    store=RunStore(db);continued=RuntimeController(engine,store,'journey-test',None)
    try:
        before=store.load_run('journey-test')[1]
        result=continued.step()
        after=store.load_run('journey-test')[1]
        if blocked:
            assert not result['accepted'] and 'Accepted journey blocked' in result['failure']['reason']
            assert after.state_hash==before.state_hash
            assert after.humans['alice']['active_plan']==plan
        else:
            assert result['accepted'] and after.humans['alice']['map_id']=='destination'
            assert continued.status()['engine_continuations']==1
            assert continued.status()['accepted_decisions']==0
            assert continued.status()['last_decision_seconds'] is None
            assert after.humans['alice']['active_plan'] is None
            receipt=store.iter_events('journey-test')[-1].causation
            assert receipt['provenance']['engine_continuation'] is True
            assert receipt['provenance']['continuation_of_state_version']==0
            assert receipt['provenance']['model_id']==provider.model_id
            assert receipt['decision_explanation']==plan['explanation']
        assert store.replay('journey-test').state_hash==after.state_hash
    finally:continued.close();store.close()

def test_cache_cannot_verify_old_snapshot_under_new_external_tamper_version(runtime,monkeypatch):
    import sqlite3
    from living_kanto.store import StoreError
    assert runtime.step()['accepted']
    reader=RunStore(runtime.store.path);writer=sqlite3.connect(runtime.store.path)
    original=reader._get_run_row;triggered=[]
    def interleave(run_id):
        row=original(run_id)
        if not triggered:
            triggered.append(True)
            event=json.loads(writer.execute('SELECT event_json FROM events WHERE run_id=?',(run_id,)).fetchone()[0])
            event['causation']['decision_explanation']='Concurrent corruption after snapshot row read'
            writer.execute('UPDATE events SET event_json=? WHERE run_id=?',(json.dumps(event),run_id));writer.commit()
        return row
    monkeypatch.setattr(reader,'_get_run_row',interleave)
    try:
        # The established read snapshot legitimately contains the old intact log.
        assert reader.load_run(runtime.run_id)[1].state_version==1
        # A subsequent snapshot must reject even though all run-row keys match.
        with pytest.raises(StoreError):reader.load_run(runtime.run_id)
    finally:reader.close();writer.close()
