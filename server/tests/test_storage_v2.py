"""Storage upgrades preserve canonical history and reject poisoned saves."""
from __future__ import annotations

import json
import sqlite3
import sys
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from living_kanto.store.run_store import RunStore, StoreError
from tests.helpers import make_event, make_run_metadata, make_world_state


@pytest.fixture
def saved(tmp_path):
    path = tmp_path / 'world.db'
    store = RunStore(path)
    genesis = make_world_state()
    genesis.humans['person'] = {'name': 'Pia', 'memories': {
        '0': {'text': 'Original memory'}, '900': {'text': 'Sparse memory'}}}
    genesis.world_facts['battles'] = {'old': {'ended': True, 'turns': [1, 2]}}
    genesis.state_hash = genesis.compute_state_hash()
    run_id = store.create_run(make_run_metadata(initial_state=genesis), genesis)
    events = []
    for tick in range(1, 6):
        _, prior, head = store.load_run(run_id)
        event = make_event(run_id, tick=tick, event_index=len(events),
                           previous_head=head, prior_state=prior)
        store.append_event(event, event.transaction['state_hash'])
        events.append(event)
    yield store, run_id, path, events
    store.close()


def _next(store, run_id, changes=None):
    _, prior, head = store.load_run(run_id)
    return make_event(run_id, tick=prior.tick, event_index=prior.state_version,
                      previous_head=head, prior_state=prior, changes=changes or [],
                      default_change=False)


def test_upgrade_preserves_genesis_state_full_replay_and_event_exports(saved):
    store, run_id, path, events = saved
    before = store.load_run(run_id)
    genesis = store.load_genesis(run_id).to_dict()
    store.optimize_storage(run_id, checkpoint_interval=2)
    assert store.load_run(run_id)[1].to_dict() == before[1].to_dict()
    assert store.load_head(run_id) == before[2]
    assert store.load_genesis(run_id).to_dict() == genesis
    assert store.replay(run_id).to_dict() == before[1].to_dict()
    assert [e.to_dict() for e in store.iter_events(run_id)] == [e.to_dict() for e in events]
    assert [e.to_dict() for e in store.iter_events(run_id, after_index=2)] == [e.to_dict() for e in events[3:]]
    compressed = store._db.execute('SELECT event_json FROM events').fetchall()
    assert all(isinstance(row[0], bytes) for row in compressed)
    assert json.loads(zlib.decompress(compressed[0][0][4:])) == events[0].to_dict()
    cold = RunStore(path)
    try:
        assert cold.load_run(run_id)[1].to_dict() == before[1].to_dict()
    finally:
        cold.close()


def test_failed_append_leaves_event_state_and_checkpoint_unchanged(saved):
    store, run_id, _, _ = saved
    store.optimize_storage(run_id, checkpoint_interval=2)
    before = store.load_run(run_id)[1].to_dict()
    event = _next(store, run_id, [{'op': 'set', 'path': 'humans.person.memories.901',
                                 'value': {'text': 'Must roll back'}}])
    rows = list(store._db.iterdump())
    with pytest.raises(StoreError):
        store.append_event(event, 'f' * 64)
    assert store.event_count(run_id) == 5
    assert store.load_run(run_id)[1].to_dict() == before
    assert list(store._db.iterdump()) == rows


def test_sparse_memories_battle_history_and_copy_isolation(saved):
    store, run_id, path, _ = saved
    store.optimize_storage(run_id, checkpoint_interval=2)
    event = _next(store, run_id, [
        {'op': 'set', 'path': 'humans.person.memories.901', 'value': {'text': 'Newest memory'}},
        {'op': 'set', 'path': 'world_facts.battles.new', 'value': {'ended': False, 'turns': []}},
    ])
    store.append_event(event, event.transaction['state_hash'])
    expected = store.load_run(run_id)[1].to_dict()
    returned = store.load_run(run_id)[1]
    returned.humans['person']['memories']['0']['text'] = 'Caller mutation'
    returned.world_facts['battles']['old']['turns'].append(999)
    assert store.load_run(run_id)[1].to_dict() == expected
    assert store.replay(run_id).to_dict() == expected
    cold = RunStore(path)
    try:
        loaded = cold.load_run(run_id)[1]
        assert set(loaded.humans['person']['memories']) == {'0', '900', '901'}
        assert loaded.world_facts['battles']['old']['turns'] == [1, 2]
        assert loaded.world_facts['battles']['new']['ended'] is False
    finally:
        cold.close()


@pytest.mark.parametrize('external', [False, True])
def test_early_event_corruption_invalidates_warm_cache_and_checkpoint(saved, external):
    store, run_id, path, _ = saved
    store.optimize_storage(run_id, checkpoint_interval=2)
    store.load_run(run_id)
    connection = sqlite3.connect(path) if external else store._db
    connection.execute("UPDATE events SET event_hash = ? WHERE event_index = 0", ('f' * 64,))
    connection.commit()
    if external:
        connection.close()
    with pytest.raises(StoreError):
        store.load_run(run_id)
    with pytest.raises(StoreError):
        store.replay(run_id)


def test_upgraded_append_does_not_rewrite_whole_world(saved):
    store, run_id, _, _ = saved
    store.optimize_storage(run_id, checkpoint_interval=50)
    event = _next(store, run_id, [{'op': 'set', 'path': 'humans.person.name', 'value': 'Pia New'}])
    statements = []
    store._db.set_trace_callback(statements.append)
    try:
        store.append_event(event, event.transaction['state_hash'])
    finally:
        store._db.set_trace_callback(None)
    updates = [s.lower() for s in statements if s.lstrip().lower().startswith('update runs')]
    assert updates
    header = store._db.execute('SELECT state_json FROM runs WHERE run_id = ?', (run_id,)).fetchone()[0]
    assert len(header.encode()) < 2048
    assert 'Original memory' not in header
    assert 'Sparse memory' not in header
    assert 'turns' not in header
    archive_writes = [s for s in statements if s.lstrip().lower().startswith(
        ('insert', 'update', 'delete')) and 'storage_archive' in s.lower()]
    assert not archive_writes


@pytest.mark.parametrize('table,column', [
    ('storage_checkpoints', 'state_blob'),
    ('storage_records', 'payload'),
    ('storage_archive', 'payload'),
])
def test_corrupt_checkpoint_or_split_record_is_rejected(saved, table, column):
    store, run_id, path, _ = saved
    store.optimize_storage(run_id, checkpoint_interval=2)
    store.load_run(run_id)
    connection = sqlite3.connect(path)
    connection.execute(f"UPDATE {table} SET {column} = ? WHERE rowid = (SELECT rowid FROM {table} LIMIT 1)",
                       (b'LKZ2invalid compressed content',))
    connection.commit()
    connection.close()
    with pytest.raises(StoreError):
        store.load_run(run_id)


def test_checkpoint_rejects_altered_prefix_binding(saved):
    store, run_id, _, _ = saved
    store.optimize_storage(run_id, checkpoint_interval=2)
    store._db.execute("UPDATE storage_checkpoints SET prefix_digest = ?", ('f' * 64,))
    store._db.commit()
    with pytest.raises(StoreError):
        store.load_run(run_id)


def test_checkpoint_load_applies_only_tail_but_explicit_replay_audits_all(saved, monkeypatch):
    from living_kanto.contracts import StateUpdate
    store, run_id, path, _ = saved
    store.optimize_storage(run_id, checkpoint_interval=2)
    event = _next(store, run_id, [{'op': 'set', 'path': 'humans.person.name', 'value': 'Pia Tail'}])
    store.append_event(event, event.transaction['state_hash'])
    calls = []
    original = StateUpdate.apply_to
    def tracked(update, state):
        calls.append(update.event_index)
        return original(update, state)
    monkeypatch.setattr(StateUpdate, 'apply_to', tracked)
    cold = RunStore(path)
    try:
        cold.load_run(run_id)
        assert len(calls) <= 1
        calls.clear()
        cold.replay(run_id)
        assert calls == list(range(6))
    finally:
        cold.close()


def test_single_memory_append_writes_only_changed_history_records(saved):
    store, run_id, _, _ = saved
    store.optimize_storage(run_id, checkpoint_interval=256)
    seed = _next(store, run_id, [{'op': 'set', 'path': 'humans.person.memories',
        'value': {str(n): {'text': 'Historical memory ' + str(n)} for n in range(100)}}])
    store.append_event(seed, seed.transaction['state_hash'])
    event = _next(store, run_id, [{'op': 'set', 'path': 'humans.person.memories.100',
                                 'value': {'text': 'Only changed entry'}}])
    statements = []
    store._db.set_trace_callback(statements.append)
    try:
        store.append_event(event, event.transaction['state_hash'])
    finally:
        store._db.set_trace_callback(None)
    archive_writes = [s for s in statements if s.lstrip().lower().startswith(
        ('insert', 'update', 'delete')) and 'storage_archive' in s.lower()]
    assert 1 <= len(archive_writes) <= 3
    assert len(store.load_run(run_id)[1].humans['person']['memories']) == 101


def test_archived_deletions_and_empty_collections_survive_cold_load(saved):
    store, run_id, path, _ = saved
    store.optimize_storage(run_id, checkpoint_interval=2)
    event = _next(store, run_id, [
        {'op': 'remove', 'path': 'humans.person.memories.900'},
        {'op': 'remove', 'path': 'world_facts.battles.old'},
    ])
    store.append_event(event, event.transaction['state_hash'])
    event = _next(store, run_id, [
        {'op': 'set', 'path': 'humans.person.memories', 'value': {}},
    ])
    store.append_event(event, event.transaction['state_hash'])
    cold = RunStore(path)
    try:
        state = cold.load_run(run_id)[1]
        assert state.humans['person']['memories'] == {}
        assert state.world_facts['battles'] == {}
        assert cold.replay(run_id).to_dict() == state.to_dict()
    finally:
        cold.close()


def test_upgrade_is_idempotent_and_preserves_pause_status(saved):
    store, run_id, _, events = saved
    store.set_status(run_id, 'paused')
    before = store.load_run(run_id)[1].to_dict()
    store.optimize_storage(run_id, checkpoint_interval=2)
    store.optimize_storage(run_id, checkpoint_interval=2)
    assert store.get_status(run_id) == 'paused'
    assert store.load_run(run_id)[1].to_dict() == before
    assert [e.to_dict() for e in store.iter_events(run_id)] == [e.to_dict() for e in events]
