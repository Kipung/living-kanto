"""Observer inference evidence stays separate from private gameplay observations."""
from test_world_api import world_client, create
from living_kanto.runtime.inference_trace import InferenceTrace


def test_observer_audit_scope_and_bounds(world_client):
    client, app = world_client
    run = create(client)
    runtime = app.state.get_runtime_controller(run)
    class TraceProvider:
        def __init__(self, sink): self._trace_sink = sink
        def trace_status(self): return self._trace_sink.status()
    sink = InferenceTrace(app.state.base_dir / 'inference-traces', run)
    sink.append({'human_id':'human-001','observation_hash':'a','response_hash':'b','outcome':'accepted','stages':[{'messages':[{'role':'user','content':'own private facts'}]}]})
    sink.append({'human_id':'human-002','observation_hash':'c','response_hash':'d','outcome':'proposed','stages':[{'messages':[{'role':'user','content':'another private person'}]}]})
    runtime.provider = TraceProvider(sink)
    result = client.get(f'/runs/{run}/observer/inference/human-001?limit=10')
    assert result.status_code == 200
    assert [r['human_id'] for r in result.json()['records']] == ['human-001']
    assert 'another private person' not in result.text
    assert client.get(f'/runs/{run}/observer/inference/nobody').status_code == 404
    assert client.get(f'/runs/{run}/observer/inference/human-001?limit=100000').status_code == 422
    observation = client.get(f'/runs/{run}/observations/human-001')
    assert observation.status_code == 200
    assert 'trace_id' not in observation.text and 'another private person' not in observation.text
    assert 'behavior_feedback' in observation.json()['self_state']
