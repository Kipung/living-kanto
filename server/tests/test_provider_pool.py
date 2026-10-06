"""Explicit local endpoint lanes retain private staged decisions and failures."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from living_kanto.runtime.providers import LocalModelConfig, LocalModelProvider, ProviderError
from living_kanto.api.world_api import Endpoint
from test_numbered_provider import observation


def test_pool_balances_complete_staged_decisions_without_cross_lane_text():
    captured = [[], []]
    joined = threading.Barrier(2)
    servers = []
    threads = []
    def handler_for(lane):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                captured[lane].append(payload)
                schema = payload['response_format']['json_schema']['schema']
                if schema['required'] == ['text']:
                    text = {'text': f'Private text lane {lane}'}
                else:
                    joined.wait(timeout=10)
                    text = {'option': 2, 'decision_explanation': 'Remember my own ambition'}
                result = {'choices': [{'message': {'content': json.dumps(text)}}]}
                self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(result).encode())
            def log_message(self, *args): pass
        return Handler
    for lane in range(2):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(lane))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start(); servers.append(server); threads.append(thread)
    try:
        urls = [f'http://127.0.0.1:{server.server_port}' for server in servers]
        provider = LocalModelProvider(LocalModelConfig(urls[0], 'test-local', response_protocol='numbered', additional_endpoints=(urls[1],)))
        observations = [observation(), {**observation(), 'human_id': 'bob', 'memories': [{'text': 'BOB ONLY'}]}]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(provider.complete, observations))
        assert {json.loads(raw)['arguments']['text'] for raw in results} == {'Private text lane 0', 'Private text lane 1'}
        for requests in captured:
            assert len(requests) == 2
            assert requests[0]['messages'][1]['content'] == requests[1]['messages'][1]['content']
        assert provider.protocol == 'openai:numbered-staged:pool'
        assert provider.lane_status() == [
            {'lane': 1, 'active': 0, 'completed': 1, 'failed': 0},
            {'lane': 2, 'active': 0, 'completed': 1, 'failed': 0}]
        assert all(url not in json.dumps(provider.lane_status()) for url in urls)
    finally:
        for server in servers: server.shutdown(); server.server_close()
        for thread in threads: thread.join(2)


def test_pool_error_does_not_fail_over_and_releases_lane():
    provider = LocalModelProvider(LocalModelConfig('http://127.0.0.1:1', 'test-local', additional_endpoints=('http://127.0.0.1:2',)))
    calls = []
    def broken(obs, correction=None):
        calls.append(1)
        raise ProviderError('Identified TEST endpoint unavailable')
    def unused(obs, correction=None):
        calls.append(2)
        return 'unused'
    provider._lanes[0].complete = broken
    provider._lanes[1].complete = unused
    with pytest.raises(ProviderError, match='TEST endpoint unavailable'):
        provider.complete(observation())
    assert calls == [1]
    assert provider.lane_status()[0] == {'lane': 1, 'active': 0, 'completed': 0, 'failed': 1}
    assert provider.complete(observation()) == 'unused'  # Fair tie, explicit next call.
    assert calls == [1, 2]


@pytest.mark.parametrize('extras', [('http://8.8.8.8',), ('http://127.0.0.1:1/',), ('http://127.0.0.1:2', 'http://127.0.0.1:3'), 'http://127.0.0.1:2'])
def test_pool_rejects_public_duplicate_or_excess_endpoints(extras):
    with pytest.raises(ProviderError):
        LocalModelConfig('http://127.0.0.1:1', 'test-local', additional_endpoints=extras).validate()


def test_endpoint_accepts_strict_64_and_at_most_two_lanes():
    values = {'base_url': 'http://127.0.0.1:1', 'model_id': 'test-local', 'concurrency': 64,
              'additional_base_urls': ['http://127.0.0.1:2']}
    assert Endpoint.model_validate(values).concurrency == 64
    for bad in [65, True, 1.5]:
        with pytest.raises(ValueError): Endpoint.model_validate({**values, 'concurrency': bad})
    with pytest.raises(ValueError):
        Endpoint.model_validate({**values, 'additional_base_urls': ['a', 'b']})
