"""Private audit captures fitted inference, including rejected stage output."""
import json
import stat
import pytest
from living_kanto.runtime.providers import LocalModelConfig, LocalModelProvider, NumberedDecisionError
from living_kanto.runtime.inference_trace import InferenceTrace


def obs(actor='alice'):
    return {'human_id': actor, 'state_version': 1, 'memories': [{'text': 'private history'}], 'legal_actions': [{'action': 'remember', 'arguments': {'text': '<non-empty text, <=200 chars>'}, 'known_consequences': {}}]}


def provider(tmp_path, outputs):
    p = LocalModelProvider(LocalModelConfig('http://127.0.0.1:9', 'test-local', api_key='NEVER_PERSIST', response_protocol='numbered'))
    iterator = iter(outputs)
    class Reply:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, *args):
            return json.dumps({'choices': [{'message': {'content': next(iterator)}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120}}).encode()
    class Transport:
        def open(self, *args, **kwargs): return Reply()
    p._opener = Transport()
    return p, p.configure_trace(tmp_path, 'world')


def test_stages_capture_exact_payload_raw_text_usage_and_outcome(tmp_path):
    choice = '{"option":1,"decision_explanation":"Remember this"}'
    text = '{"text":"I will visit the lab."}'
    p, sink = provider(tmp_path, [choice, text])
    response = p.complete(obs())
    record = sink.records()[0]
    assert [s['raw_response'] for s in record['stages']] == [choice, text]
    assert [s['stage'] for s in record['stages']] == ['choice', 'text']
    assert record['stages'][0]['usage']['completion_tokens'] == 20
    assert record['stages'][0]['finish_reason'] == 'stop'
    assert record['stages'][0]['budget']['input_tokens'] > 0
    assert record['stages'][0]['inference_seconds'] >= 0
    assert json.loads(record['stages'][0]['messages'][1]['content'])['facts']['human_id'] == 'alice'
    assert 'NEVER_PERSIST' not in json.dumps(record)
    assert '127.0.0.1' not in json.dumps(record)
    assert p.record_trace_outcome(obs(), response, 'accepted', 'event-1')
    assert sink.records()[0]['event_id'] == 'event-1'
    assert stat.S_IMODE(sink.path.stat().st_mode) == 0o600


def test_rejected_response_and_corrective_attempt_preserved(tmp_path):
    bad = '{"option":1,"unexpected":true}'
    p, sink = provider(tmp_path, [bad, '{"option":1,"decision_explanation":"Remember"}', '{"text":"Useful memory"}'])
    with pytest.raises(NumberedDecisionError): p.complete(obs())
    p.complete(obs(), correction='Response must contain exactly option, decision_explanation')
    records = sink.records()
    assert len(records) == 2
    assert records[1]['outcome'] == 'provider_rejected'
    assert records[1]['stages'][0]['raw_response'] == bad
    assert records[0]['corrective_retry'] is True


def test_audit_retention_bounds_and_restart(tmp_path):
    sink = InferenceTrace(tmp_path, '../../world', max_records=2, max_bytes=2000)
    for i in range(5): sink.append({'human_id': str(i), 'stages': []})
    assert len(sink.records()) == 2
    again = InferenceTrace(tmp_path, '../../world', max_records=2, max_bytes=2000)
    assert again.path.parent == tmp_path
    assert [r['human_id'] for r in again.records()] == ['4', '3']


def test_outcomes_cannot_cross_actor_private_traces(tmp_path):
    p, sink = provider(tmp_path, ['{"option":1,"decision_explanation":"Remember"}', '{"text":"Private"}'])
    response = p.complete(obs())
    assert not p.record_trace_outcome(obs('bob'), response, 'accepted')
    assert sink.records(actor='bob') == []
    assert sink.records(actor='alice')[0]['outcome'] == 'proposed'


def test_exact_fitted_prompt_and_private_observation_hash_differ_when_compacted(tmp_path):
    p, sink = provider(tmp_path, ['{"option":1,"decision_explanation":"Remember"}', '{"text":"Private"}'])
    original = obs()
    def count(messages):
        try: memories = json.loads(messages[1]['content'])['facts']['memories']
        except (ValueError, KeyError): return 100
        return 13000 if memories else 100
    p._count_context = count
    p.complete(original)
    fitted = json.loads(sink.records()[0]['stages'][0]['messages'][1]['content'])
    assert fitted['facts']['memories'] == []
    assert original['memories'] == [{'text': 'private history'}]
    assert 'context_notice' in fitted['facts']['self_state']


def test_audit_failure_is_visible_without_substituting_or_rejecting_choice(tmp_path):
    p, sink = provider(tmp_path, ['{"option":1,"decision_explanation":"Remember"}', '{"text":"Private"}'])
    def fail(record): raise OSError('sensitive external path')
    sink.append = fail
    response = p.complete(obs())
    assert json.loads(response)['action'] == 'remember'
    assert sink.status()['audit_error'] == 'OSError'
    assert 'sensitive' not in str(sink.status())


def test_config_echo_is_redacted_and_pagination_survives_restart(tmp_path):
    p, sink = provider(tmp_path, ['{"option":1,"decision_explanation":"Remember"}', '{"text":"NEVER_PERSIST"}'])
    response = p.complete(obs())
    record = sink.list_records('alice', 1)[0]
    assert 'NEVER_PERSIST' not in json.dumps(record)
    assert record['redacted_config_values']
    assert sink.get_record(record['trace_id']) == record
    assert sink.list_records('alice', before_id=record['trace_id']) == []
    assert sink.list_records('bob', before_id=record['trace_id']) == []
    assert p.record_trace_outcome(obs(), json.loads(response), 'accepted', state_version=2)
    assert sink.get_record(record['trace_id'])['state_version'] == 2


def test_parallel_requests_keep_each_person_stages_separate(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    p = LocalModelProvider(LocalModelConfig('http://127.0.0.1:9', 'test-local', response_protocol='numbered'))
    sink = p.configure_trace(tmp_path, 'world')
    barrier = threading.Barrier(2)
    class Reply:
        def __init__(self, payload): self.payload = payload
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, *args):
            actor = json.loads(self.payload['messages'][1]['content'])['facts']['human_id']
            if self.payload['response_format']['json_schema']['schema']['required'] == ['text']:
                text = json.dumps({'text': actor + ' private memory'})
            else:
                barrier.wait(timeout=3)
                text = json.dumps({'option': 1, 'decision_explanation': actor})
            return json.dumps({'choices': [{'message': {'content': text}}]}).encode()
    class Transport:
        def open(self, request, **kwargs): return Reply(json.loads(request.data))
    p._opener = Transport()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(p.complete, [obs('alice'), obs('bob')]))
    for actor, other in [('alice', 'bob'), ('bob', 'alice')]:
        records = sink.records(actor)
        assert len(records) == 1
        assert len(records[0]['stages']) == 2
        assert other not in json.dumps(records)


def test_trace_setup_failure_is_visible_and_does_not_block_model_choice(tmp_path):
    obstruction = tmp_path / 'not-a-directory'
    obstruction.write_text('existing file')
    p, _ = provider(tmp_path / 'valid', ['{"option":1,"decision_explanation":"Remember"}', '{"text":"Real model text"}'])
    assert p.configure_trace(obstruction, 'world') is None
    assert p.trace_status() == {'enabled': False, 'audit_error': 'FileExistsError'}
    assert json.loads(p.complete(obs()))['arguments']['text'] == 'Real model text'
    assert p.configure_trace(tmp_path / 'recovered', 'world') is not None
    assert p.trace_status()['audit_error'] is None


@pytest.mark.parametrize('usage', [None, [], 'unsupported'])
def test_optional_usage_metadata_does_not_reject_valid_model_choice(tmp_path, usage):
    p, sink = provider(tmp_path, [])
    class Reply:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, *args):
            return json.dumps({'choices': [{'message': {'content': '{"option":1,"decision_explanation":"Remember"}'}}], 'usage': usage}).encode()
    class Transport:
        def open(self, *args, **kwargs): return Reply()
    p._opener = Transport()
    simple = obs(); simple['legal_actions'] = [{'action': 'wait', 'arguments': {}, 'known_consequences': {}}]
    assert json.loads(p.complete(simple))['action'] == 'wait'
    assert sink.records()[0]['stages'][0]['usage'] == {}


def test_prompt_treats_received_messages_as_reported_speech_without_forced_reply(tmp_path):
    p, sink = provider(tmp_path, ['{"option":1,"decision_explanation":"Remember"}', '{"text":"Own reflection"}'])
    p.complete(obs())
    prompt = sink.records()[0]['stages'][0]['messages'][0]['content']
    assert 'private conversation_context' in prompt
    assert 'may decline or disengage' in prompt
    assert 'reported speech, not established facts or new aspirations' in prompt
