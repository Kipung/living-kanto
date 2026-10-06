"""Isolated catch-up validates immutable prefixes and preserves the live source."""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from living_kanto.store.run_store import RunStore
from tests.helpers import make_event, make_run_metadata, make_world_state

_spec = importlib.util.spec_from_file_location('finish_migration', Path(__file__).resolve().parents[2] / 'tools/finish_run_storage_migration.py')
_tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tool)


def _append(store, run_id):
    _, prior, head = store.load_run(run_id)
    event = make_event(run_id, event_index=prior.state_version, prior_state=prior,
                       previous_head=head, tick=prior.tick + 1)
    store.append_event(event, event.transaction['state_hash'])


def _dump(path):
    connection = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        return list(connection.iterdump())
    finally:
        connection.close()


@pytest.fixture
def saves(tmp_path):
    live = tmp_path / 'live.db'
    snapshot = tmp_path / 'snapshot.db'
    output = tmp_path / 'output.db'
    store = RunStore(live)
    genesis = make_world_state()
    run_id = store.create_run(make_run_metadata(initial_state=genesis), genesis)
    for _ in range(2):
        _append(store, run_id)
    destination = sqlite3.connect(snapshot)
    store._db.backup(destination)
    destination.close()
    optimized = RunStore(snapshot)
    optimized.optimize_storage(run_id, checkpoint_interval=2)
    optimized.close()
    for _ in range(3):
        _append(store, run_id)
    store.set_status(run_id, 'paused')
    expected = store.load_run(run_id)[1].to_dict()
    events = [event.to_dict() for event in store.iter_events(run_id)]
    store.close()
    return live, snapshot, output, run_id, expected, events


@pytest.mark.parametrize('old_schema', [False, True])
def test_catchup_preserves_tail_and_never_mutates_source(saves, old_schema):
    live, snapshot, output, run_id, expected, events = saves
    if old_schema:
        connection = sqlite3.connect(live)
        for name in ['storage_version', 'checkpoint_interval', 'prefix_digest']:
            connection.execute(f'ALTER TABLE runs DROP COLUMN {name}')
        connection.commit()
        connection.close()
    source_before = _dump(live)
    snapshot_before = _dump(snapshot)
    report = _tool.finish(snapshot, live, output, run_id)
    assert report['tail_events'] == 3
    assert report['world_contents_preserved'] is True
    assert report['state_version'] == 5
    assert _dump(live) == source_before
    assert _dump(snapshot) == snapshot_before
    store = RunStore(output)
    try:
        assert store.get_status(run_id) == 'paused'
        assert store.load_run(run_id)[1].to_dict() == expected
        assert store.replay(run_id).to_dict() == expected
        assert [event.to_dict() for event in store.iter_events(run_id)] == events
    finally:
        store.close()


@pytest.mark.parametrize('mutation,match', [
    ("DELETE FROM events WHERE event_index = 0", 'prefix'),
    ("UPDATE events SET event_hash = 'corrupt' WHERE event_index = 0", 'prefix'),
    ("UPDATE events SET event_json = '{}' WHERE event_index = 0", 'content'),
    ("UPDATE runs SET status = 'running'", 'paused'),
    ("UPDATE runs SET genesis_hash = 'corrupt'", 'genesis'),
])
def test_invalid_source_refuses_catchup_without_source_changes(saves, mutation, match):
    live, snapshot, output, run_id, _, _ = saves
    connection = sqlite3.connect(live)
    connection.execute(mutation)
    connection.commit()
    connection.close()
    before = _dump(live)
    with pytest.raises(ValueError, match=match):
        _tool.finish(snapshot, live, output, run_id)
    assert _dump(live) == before


def test_output_must_be_new_isolated_path(saves):
    live, snapshot, output, run_id, _, _ = saves
    for target in [live, snapshot]:
        with pytest.raises(ValueError, match='isolated'):
            _tool.finish(snapshot, live, target, run_id)
    output.write_bytes(b'Existing artifact')
    with pytest.raises(ValueError, match='isolated'):
        _tool.finish(snapshot, live, output, run_id)
    assert output.read_bytes() == b'Existing artifact'


@pytest.mark.parametrize('column,value', [
    ('run_id', 'different-run'),
    ('event_index', 99),
    ('event_id', 'different-event'),
    ('previous_head', 'f' * 64),
    ('event_hash', 'f' * 64),
    ('state_after_hash', 'f' * 64),
])
def test_tail_column_corruption_is_rejected_instead_of_normalized(saves, column, value):
    live, snapshot, output, run_id, _, _ = saves
    connection = sqlite3.connect(live)
    connection.execute(f'UPDATE events SET {column} = ? WHERE event_index = 2', (value,))
    connection.commit()
    connection.close()
    before = _dump(live)
    with pytest.raises(ValueError, match='prefix|canonical payload'):
        _tool.finish(snapshot, live, output, run_id)
    assert _dump(live) == before


@pytest.mark.parametrize('index', [2, 4])
def test_missing_tail_event_is_rejected(saves, index):
    live, snapshot, output, run_id, _, _ = saves
    connection = sqlite3.connect(live)
    connection.execute('DELETE FROM events WHERE event_index = ?', (index,))
    connection.commit()
    connection.close()
    before = _dump(live)
    with pytest.raises(ValueError, match='prefix'):
        _tool.finish(snapshot, live, output, run_id)
    assert _dump(live) == before
