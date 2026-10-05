"""Tests for RunStore: append_event, state mutation, fork/duplicate rejection.

Uses real content hashes via helpers (state.verify() must pass).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from living_kanto.contracts.events import CanonicalEvent
from living_kanto.contracts.state import StateUpdate, WorldState
from living_kanto.store.run_store import RunStore, StoreError
from tests.helpers import (
    append_chain_event,
    genesis_head,
    make_event,
    make_run_metadata,
    make_world_state,
)


@pytest.fixture
def store(tmp_path):
    return RunStore(str(tmp_path / "test.db"))


def _create(store: RunStore):
    run_id = store.create_run(make_run_metadata(), make_world_state())
    return run_id


def test_create_and_get_run(store):
    run_id = _create(store)
    meta, state, head = store.load_run(run_id)
    assert meta.run_id == run_id
    # Genesis state hash must recompute from content (real content hash).
    assert state.compute_state_hash() == state.state_hash
    # runs.head_hash tracks the event chain only: before any event it is the
    # 64-zero seed, never the genesis world hash.
    assert head == "0" * 64


def test_append_event_applies_changes_and_recomputes_hash(store):
    """append_event must apply state_changes and recompute the hash from content."""
    run_id = _create(store)
    meta, prior_state, _head = store.load_run(run_id)
    event = make_event(run_id, tick=1, prior_state=prior_state)
    expected_hash = event.transaction["state_hash"]
    new_hash = store.append_event(event, expected_hash)

    _, state, head = store.load_run(run_id)
    assert head == new_hash
    # The change must be applied to the world content (event_index 0 -> p1).
    # WorldState stores entity collections as plain dicts (see the contract's
    # pokemon: dict[str, dict[str, Any]] annotation), so membership/value are
    # checked by key lookup, not attribute access.
    assert "p1_1" in state.pokemon
    assert state.pokemon["p1_1"]["location"] == "viridian_forest"
    assert state.state_version == 1
    assert state.state_hash == expected_hash
    # The recomputed hash must differ from the prior (genesis) hash, proving a
    # real content change was applied rather than a no-op.
    assert state.state_hash != prior_state.state_hash


def test_append_event_rejects_wrong_resulting_state(store):
    """A caller-supplied hash that does not match the recomputed content is rejected."""
    run_id = _create(store)
    meta, prior_state, _head = store.load_run(run_id)
    event = make_event(run_id, tick=1, prior_state=prior_state)
    bogus_hash = "f" * 64
    with pytest.raises(StoreError):
        store.append_event(event, bogus_hash)
    # Run state must be unchanged after the rejected append.
    _, state, head = store.load_run(run_id)
    assert state.state_version == 0
    assert head == "0" * 64  # chain seed untouched by the rejected append


def test_append_event_rejects_stale_version(store):
    run_id = _create(store)
    meta, prior_state, _head = store.load_run(run_id)
    e1 = make_event(run_id, tick=1, prior_state=prior_state)
    store.append_event(e1, e1.transaction["state_hash"])

    # Re-using the first event (stale version/index) must be rejected.
    with pytest.raises(StoreError):
        store.append_event(e1, e1.transaction["state_hash"])


def test_append_event_rejects_fork(store):
    """Two events at the same index with different previous_head: only one wins."""
    run_id = _create(store)
    meta, prior_state, _head = store.load_run(run_id)

    # Fork A: correct previous_head.
    fork_a = make_event(run_id, tick=1, prior_state=prior_state, event_id="evt-fork-a")
    # Fork B: wrong previous_head (simulates a stale/forked branch).
    fork_b = make_event(
        run_id, tick=1, prior_state=prior_state,
        event_id="evt-fork-b", previous_head="d" * 64,
    )

    store.append_event(fork_a, fork_a.transaction["state_hash"])
    with pytest.raises(StoreError):
        store.append_event(fork_b, fork_b.transaction["state_hash"])


def test_append_event_rejects_duplicate_id(store):
    """Same event_id re-applied at a new index must be rejected."""
    run_id = _create(store)
    meta, prior_state, _head = store.load_run(run_id)
    e1 = make_event(run_id, tick=1, prior_state=prior_state, event_id="evt-dup")
    store.append_event(e1, e1.transaction["state_hash"])

    # A new index but the same event_id. previous_head comes from the store's
    # actual chain head so this isolates the duplicate-event_id rejection from
    # the head-mismatch rejection (a stale head would fail for the wrong reason).
    _, s1, _ = store.load_run(run_id)
    e2 = make_event(
        run_id, tick=2, prior_state=s1,
        event_id="evt-dup", event_index=1,
        previous_head=store.load_head(run_id),
    )
    with pytest.raises(StoreError):
        store.append_event(e2, e2.transaction["state_hash"])


def test_append_event_rejects_wrong_index(store):
    run_id = _create(store)
    meta, prior_state, _head = store.load_run(run_id)
    # Skip ahead: event_index 5 when next is 0.
    bad = make_event(run_id, tick=1, prior_state=prior_state, event_index=5)
    with pytest.raises(StoreError):
        store.append_event(bad, bad.transaction["state_hash"])


def test_append_event_rejects_when_not_running(store):
    run_id = _create(store)
    store.set_status(run_id, "paused")
    meta, prior_state, _head = store.load_run(run_id)
    event = make_event(run_id, tick=1, prior_state=prior_state)
    with pytest.raises(StoreError):
        store.append_event(event, event.transaction["state_hash"])


def test_multiple_events_chain(store):
    run_id = _create(store)
    meta, state, _head = store.load_run(run_id)
    hashes = []
    for tick in range(1, 4):
        # append_chain_event derives previous_head from the store's actual
        # event-chain head; append_event returns the new WORLD hash, which is
        # not the chain link for the next event.
        append_chain_event(store, run_id, tick=tick, prior_state=state)
        _, state, head = store.load_run(run_id)
        hashes.append(store.load_head(run_id))
    assert len(hashes) == 3
    events = list(store.iter_events(run_id))
    assert [e.event_hash for e in events] == hashes


def test_iter_events_after_index(store):
    run_id = _create(store)
    meta, state, _head = store.load_run(run_id)
    for tick in range(1, 4):
        append_chain_event(store, run_id, tick=tick, prior_state=state)
        _, state, _ = store.load_run(run_id)

    all_events = list(store.iter_events(run_id))
    assert len(all_events) == 3
    tail = list(store.iter_events(run_id, after_index=1))
    assert [e.event_index for e in tail] == [2]


def test_status_transitions(store):
    run_id = _create(store)
    assert store.get_status(run_id) == "running"
    store.set_status(run_id, "paused")
    assert store.get_status(run_id) == "paused"
    store.set_status(run_id, "running")
    assert store.get_status(run_id) == "running"


# ---------------------------------------------------------------------------
# Operator probes 1510: malformed genesis must be rejected atomically,
# leaving zero rows in every table.
# ---------------------------------------------------------------------------

def _table_counts(store: RunStore) -> tuple[int, int]:
    import sqlite3

    conn = sqlite3.connect(store.path)
    try:
        runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    finally:
        conn.close()
    return runs, events


def test_genesis_run_id_mismatch_rejected_atomically(store):
    import dataclasses

    meta = make_run_metadata()
    genesis = make_world_state()
    mismatched = dataclasses.replace(genesis, run_id="some-other-run")
    with pytest.raises(StoreError, match="run_id"):
        store.create_run(meta, mismatched)
    assert _table_counts(store) == (0, 0)


def test_declared_genesis_hash_mismatch_rejected_atomically(store):
    meta = make_run_metadata()
    genesis = make_world_state()
    forged = WorldState.from_dict({**genesis.to_dict(), "state_hash": "f" * 64})
    with pytest.raises(StoreError, match="hash"):
        store.create_run(meta, forged)
    assert _table_counts(store) == (0, 0)


def test_empty_declared_genesis_hash_rejected_atomically(store):
    meta = make_run_metadata()
    genesis = make_world_state()
    emptied = WorldState.from_dict({**genesis.to_dict(), "state_hash": ""})
    with pytest.raises(StoreError, match="hash"):
        store.create_run(meta, emptied)
    assert _table_counts(store) == (0, 0)


def test_nonzero_genesis_version_rejected_atomically(store):
    import dataclasses

    meta = make_run_metadata()
    genesis = make_world_state()
    # replace() recomputes a valid content hash, isolating the version defect.
    bumped = dataclasses.replace(genesis, state_version=7)
    with pytest.raises(StoreError, match="version"):
        store.create_run(meta, bumped)
    assert _table_counts(store) == (0, 0)


def test_store_still_usable_after_genesis_rejections(store):
    run_id = _create(store)
    meta, state, head = store.load_run(run_id)
    assert meta.run_id == run_id
    assert head == genesis_head()


# --- identity / mode binding defenses -----------------------------------------


def _sqlite_execute(db_path: str, sql: str, params: tuple = ()) -> int:
    """Apply a raw mutation bypassing the store API; return affected rowcount."""
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def _pending_append(store: RunStore, run_id: str):
    """Build the next valid event + true resulting hash BEFORE any tampering."""
    event = make_event(run_id, event_index=store.event_count(run_id))
    prior = store.load_run(run_id)[1]
    update = StateUpdate.from_dict(event.transaction).apply_to(prior)
    return event, update.state_hash


def test_creation_mode_mismatch_rejected_atomically(store):
    import dataclasses

    meta = make_run_metadata()
    genesis = dataclasses.replace(make_world_state(), mode="survival")
    with pytest.raises(StoreError, match="mode"):
        store.create_run(meta, genesis)
    assert _table_counts(store) == (0, 0)


def test_tampered_metadata_json_run_id_rejected_on_read_and_append(store):
    run_id = _create(store)
    meta = store.load_run(run_id)[0]
    event, after_hash = _pending_append(store, run_id)
    tampered = json.dumps({**meta.to_dict(), "run_id": "evil"})
    assert _sqlite_execute(
        store.path, "UPDATE runs SET metadata_json=?", (tampered,)
    ) == 1
    with pytest.raises(StoreError, match="does not match"):
        store.load_run(run_id)
    with pytest.raises(StoreError, match="does not match"):
        store.replay(run_id)
    with pytest.raises(StoreError, match="does not match"):
        store.append_event(event, after_hash)


def test_tampered_metadata_json_mode_rejected_on_read_and_append(store):
    run_id = _create(store)
    meta = store.load_run(run_id)[0]
    event, after_hash = _pending_append(store, run_id)
    tampered = json.dumps({**meta.to_dict(), "mode": "creative"})
    assert _sqlite_execute(
        store.path, "UPDATE runs SET metadata_json=?", (tampered,)
    ) == 1
    with pytest.raises(StoreError, match="does not match"):
        store.load_run(run_id)
    with pytest.raises(StoreError, match="does not match"):
        store.replay(run_id)
    with pytest.raises(StoreError, match="does not match"):
        store.append_event(event, after_hash)


def test_sql_level_mode_column_change_rejected_on_read_and_append(store):
    run_id = _create(store)
    event, after_hash = _pending_append(store, run_id)
    assert _sqlite_execute(
        store.path, "UPDATE runs SET mode='creative' WHERE run_id=?", (run_id,)
    ) == 1
    with pytest.raises(StoreError, match="does not match"):
        store.load_run(run_id)
    with pytest.raises(StoreError, match="does not match"):
        store.replay(run_id)
    with pytest.raises(StoreError, match="does not match"):
        store.append_event(event, after_hash)


def test_tampered_genesis_json_mode_rejected_on_read(store):
    run_id = _create(store)
    genesis = store.load_genesis(run_id)
    doc = genesis.to_dict()
    doc["mode"] = "creative"
    tampered = WorldState.from_dict(doc)  # from_dict preserves the forged hash
    assert _sqlite_execute(
        store.path, "UPDATE runs SET genesis_json=?", (json.dumps(tampered.to_dict(), sort_keys=True),)
    ) == 1
    with pytest.raises(StoreError, match="does not match"):
        store.load_genesis(run_id)
    with pytest.raises(StoreError, match="does not match"):
        store.load_run(run_id)
