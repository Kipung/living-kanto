"""Observer pages over both physical event encodings, without writer scans."""
import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from living_kanto.api.history_paging import history_page, install_history_paging
from living_kanto.store.storage_layout import pack


@pytest.fixture(params=[1, 2])
def history_store(tmp_path, request):
    path = tmp_path / 'history.db'
    events = [
        {'event_index': 0, 'event_kind': 'human.talk', 'causation': {'human_id': 'b', 'action': 'talk_to', 'action_arguments': {'human_id': 'a', 'text': 'private target'}}},
        {'event_index': 1, 'event_kind': 'pokemon.healed', 'after': {'id': 'owned'}},
        {'event_index': 2, 'event_kind': 'human.moved', 'causation': {'human_id': 'a'}},
        {'event_index': 3, 'event_kind': 'badge.earned', 'after': {'a': {'badge': 'boulder'}}},
        {'event_index': 4, 'event_kind': 'world.shared_tick', 'deterministic_inputs': {'routes': [{'human_id': 'a', 'event_kind': 'human.moved'}]}},
        {'event_index': 5, 'event_kind': 'pokemon.healed', 'after': {'id': 'party'}},
        {'event_index': 6, 'event_kind': 'pokemon.healed', 'after': {'id': 'box'}},
        {'event_index': 7, 'event_kind': 'human.rest', 'causation': {'human_id': 'b'}},
        {'event_index': 8, 'event_kind': 'world.shared_tick', 'deterministic_inputs': {'activity_completions': ['a'], 'routes': []}},
    ]
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE events (run_id TEXT,event_index INTEGER,event_json,PRIMARY KEY(run_id,event_index))')
        connection.executemany('INSERT INTO events VALUES (?,?,?)', [('run', e['event_index'], pack(e) if request.param == 2 else json.dumps(e)) for e in events])
    state = SimpleNamespace(state_version=9, humans={'a': {'name': 'Alice', 'party': ['party'], 'box': ['box']}, 'b': {'name': 'Bob'}},
                            pokemon={'owned': {'owner_id': 'a'}, 'party': {'owner_id': 'b'}, 'box': {}}, npcs={})
    # load_run is the integrity boundary; the page scans only its own RO connection.
    return SimpleNamespace(path=path, load_run=lambda run_id: (None, state, None)), events


def test_complete_traversal_and_exact_events(history_store):
    store, originals = history_store
    cursor = None
    results = []
    while True:
        page = history_page(store, 'run', 'a', before=cursor, limit=2)
        assert len(page['events']) <= 2 and page['through_version'] == 9
        results.extend(page['events'])
        if not page['has_more']:
            assert page['next_before'] is None
            break
        cursor = page['next_before']
    expected = [originals[i] for i in [8, 6, 5, 3, 2, 1, 0]]
    assert results == expected
    assert len({event['event_index'] for event in results}) == len(results)


def test_categories_target_refs_and_name_search(history_store):
    store, originals = history_store
    assert history_page(store, 'run', 'a', category='interactions')['events'] == [originals[0]]
    assert history_page(store, 'run', 'a', category='pokemon')['events'] == [originals[i] for i in [6, 5, 1]]
    assert history_page(store, 'run', 'a', category='travel')['events'] == [originals[2]]
    assert history_page(store, 'run', 'a', category='progress')['events'] == [originals[3]]
    assert history_page(store, 'run', 'a', search='Bob chatted with Alice')['events'] == [originals[0]]
    assert history_page(store, 'run', 'a', search='PRIVATE TARGET')['events'] == [originals[0]]
    assert history_page(store, 'run', 'a', before=0)['events'] == []


def test_http_validation_and_unknown_person(history_store):
    store, _ = history_store
    app = FastAPI()
    install_history_paging(app, lambda run_id: store)
    with TestClient(app) as client:
        for query in ['limit=101', 'limit=0', 'before=-1', 'category=other']:
            assert client.get('/runs/run/history?human_id=a&' + query).status_code == 422
        assert client.get('/runs/run/history?human_id=missing').status_code == 404
        assert client.get('/runs/run/history?human_id=a&limit=1').json()['has_more']


def test_cursor_excludes_new_commits(history_store):
    store, originals = history_store
    first = history_page(store, 'run', 'a', limit=2)
    with sqlite3.connect(store.path) as connection:
        connection.execute('INSERT INTO events VALUES (?,?,?)', ('run', 9, json.dumps({'event_index': 9, 'event_kind': 'human.rest', 'causation': {'human_id': 'a'}})))
    store.load_run('run')[1].state_version = 10
    remaining = history_page(store, 'run', 'a', before=first['next_before'])
    assert all(event['event_index'] < first['next_before'] for event in remaining['events'])
    assert remaining['through_version'] == 10


def test_npc_target_history(history_store):
    store, _ = history_store
    store.load_run('run')[1].npcs['resident'] = {'name': 'Original resident'}
    event = {'event_index': 9, 'event_kind': 'human.talk', 'causation': {'human_id': 'a', 'action': 'talk_to', 'action_arguments': {'npc_id': 'resident'}}}
    with sqlite3.connect(store.path) as connection:
        connection.execute('INSERT INTO events VALUES (?,?,?)', ('run', 9, pack(event)))
    store.load_run('run')[1].state_version = 10
    assert history_page(store, 'run', 'resident')['events'] == [event]
