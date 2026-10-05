"""Tests for event-log replay from the immutable genesis snapshot.

Replay is exercised through the production store path (RunStore.replay),
which starts from the stored verified genesis, applies every recorded event
via StateUpdate.apply_to, and validates full state, hashes, versions, and
chain linkage. No models are involved.
"""

from pathlib import Path
import json
import sqlite3

import pytest

from living_kanto.contracts.events import CanonicalEvent
from living_kanto.contracts.state import StateUpdate, WorldState
from living_kanto.store.run_store import RunStore, StoreError

from tests.helpers import append_chain_event, make_run_metadata, make_world_state


@pytest.fixture
def store(tmp_path):
    return RunStore(str(tmp_path / "replay_test.db"))


def _build(store: RunStore, tmp_path: Path, n_events: int = 3) -> str:
    """Create a run and append n_events chained events."""
    initial_state = make_world_state()
    meta = make_run_metadata(initial_state=initial_state)
    run_id = store.create_run(meta, initial_state)
    state = initial_state
    for tick in range(1, n_events + 1):
        append_chain_event(store, run_id, tick=tick, prior_state=state)
        _, state, _ = store.load_run(run_id)
    return run_id


def _replay(store: RunStore, run_id: str) -> WorldState:
    """Reproduce a run's final state from its persisted event log.

    Delegates to the production replay path: immutable stored genesis, all
    recorded events applied via StateUpdate.apply_to, full-state/hash/version
    and chain validation. Raises StoreError on any divergence.
    """
    return store.replay(run_id)


def test_replay_reconstructs_final_state(store: RunStore, tmp_path: Path) -> None:
    run_id = _build(store, tmp_path, n_events=5)
    _, stored_state, _ = store.load_run(run_id)
    replayed = _replay(store, run_id)
    assert replayed.to_dict() == stored_state.to_dict()


def test_replay_matches_stored_snapshot(store: RunStore, tmp_path: Path) -> None:
    run_id = _build(store, tmp_path, n_events=3)
    _, stored_state, _ = store.load_run(run_id)
    replayed = _replay(store, run_id)
    assert replayed.state_hash == stored_state.state_hash
    assert replayed.state_version == stored_state.state_version
    assert replayed.tick == stored_state.tick
    assert replayed.simulated_time == stored_state.simulated_time


def test_replay_detects_corrupted_event_transaction(store: RunStore, tmp_path: Path) -> None:
    """If an event's recorded state hash is wrong, replay must fail."""
    run_id = _build(store, tmp_path, n_events=2)
    # Corrupt the state_after_hash of the first event.
    with sqlite3.connect(str(store.path)) as conn:
        conn.execute(
            "UPDATE events SET state_after_hash = ? WHERE run_id = ? AND event_index = 0",
            ("e" * 64, run_id),
        )
        conn.commit()
    try:
        _replay(store, run_id)
    except StoreError as exc:
        assert "replay hash mismatch" in str(exc)
    else:
        raise AssertionError("replay should have detected corrupted event")


def test_replay_detects_corrupted_stored_snapshot(store: RunStore, tmp_path: Path) -> None:
    """If the stored snapshot drifts from the log, replay/load must reject it.

    Corruption must RAISE: neither replay nor load may hand back a snapshot
    that disagrees with the verified genesis+event chain.
    """
    run_id = _build(store, tmp_path, n_events=2)
    # Corrupt the stored snapshot's hash column.
    with sqlite3.connect(str(store.path)) as conn:
        conn.execute(
            "UPDATE runs SET state_hash = ? WHERE run_id = ?",
            ("f" * 64, run_id),
        )
        conn.commit()
    with pytest.raises(StoreError):
        store.replay(run_id)
    with pytest.raises(StoreError):
        store.load_run(run_id)


def test_replay_empty_run_returns_genesis(store: RunStore, tmp_path: Path) -> None:
    initial_state = make_world_state()
    meta = make_run_metadata(initial_state=initial_state)
    run_id = store.create_run(meta, initial_state)
    replayed = _replay(store, run_id)
    assert replayed.to_dict() == initial_state.to_dict()


# ---------------------------------------------------------------------------
# Operator probes 1510: redundant SQL bindings must be rejected on replay,
# load and append - never silently replayed.
# ---------------------------------------------------------------------------

def _corrupt(store: RunStore, sql: str, params: tuple) -> None:
    conn = sqlite3.connect(store.path)
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        # Guard against fixture bugs: the UPDATE must actually mutate exactly
        # one row, otherwise the "corruption" test would silently be a no-op.
        assert cur.rowcount == 1, f"corruption UPDATE touched {cur.rowcount} rows: {sql}"
    finally:
        conn.close()


def _setup_two_events(store: RunStore, tmp_path) -> str:
    run_id = _build(store, tmp_path, n_events=2)
    return run_id


def _replay_ignoring_corruption(store: RunStore, run_id: str) -> WorldState:
    """Rebuild a plausible next-input state straight from stored event JSON,
    bypassing the store's validation (to prove append itself rejects)."""
    conn = sqlite3.connect(store.path)
    try:
        rows = conn.execute(
            "SELECT event_json FROM events WHERE run_id=? ORDER BY event_index",
            (run_id,),
        ).fetchall()
    finally:
        conn.close()
    state = store.load_genesis(run_id)
    for (ej,) in rows:
        ev = CanonicalEvent.from_dict(json.loads(ej))
        state = StateUpdate.from_dict(ev.transaction).apply_to(state)
    return state


@pytest.mark.parametrize(
    "sql,make_params",
    [
        ("UPDATE runs SET head_hash=? WHERE run_id=?", lambda r: ("a" * 64, r)),
        ("UPDATE runs SET state_version=? WHERE run_id=?", lambda r: (r["sv"] + 1, r)),
        ("UPDATE runs SET tick=? WHERE run_id=?", lambda r: (r["tick"] + 100, r)),
        ("UPDATE runs SET simulated_time=? WHERE run_id=?", lambda r: (r["sim"] + 1000.0, r)),
        ("UPDATE events SET event_id=? WHERE run_id=? AND event_index=1", lambda r: ("tampered-id", r)),
        ("UPDATE events SET event_hash=? WHERE run_id=? AND event_index=1", lambda r: ("e" * 64, r)),
        ("UPDATE events SET previous_head=? WHERE run_id=? AND event_index=1", lambda r: ("d" * 64, r)),
        ("UPDATE events SET event_index=? WHERE run_id=? AND event_index=1", lambda r: (99, r)),
    ],
    ids=["head_hash", "state_version", "tick", "simulated_time",
         "event_id", "event_hash", "previous_head", "event_index"],
)
def test_sql_binding_corruption_rejected_everywhere(store, tmp_path, sql, make_params):
    run_id = _setup_two_events(store, tmp_path)
    conn = sqlite3.connect(store.path)
    try:
        row = conn.execute(
            "SELECT state_version AS sv, tick, simulated_time AS sim FROM runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
    finally:
        conn.close()
    base = {"sv": row[0], "tick": row[1], "sim": row[2], "run": run_id}
    p = make_params(base)
    if isinstance(p[1], dict):
        p = (p[0], run_id)
    _corrupt(store, sql, p)

    with pytest.raises(StoreError):
        store.replay(run_id)
    with pytest.raises(StoreError):
        store.load_run(run_id)
    honest = _replay_ignoring_corruption(store, run_id)
    with pytest.raises(StoreError):
        append_chain_event(store, run_id, tick=honest.tick + 1, prior_state=honest)


def test_valid_baseline_load_and_append_still_work(store, tmp_path):
    """Positive control: uncorrupted load/append must keep passing."""
    run_id = _setup_two_events(store, tmp_path)
    meta, state, head = store.load_run(run_id)
    assert state.state_version == 2
    ev = append_chain_event(store, run_id, tick=state.tick + 1, prior_state=state)
    _, loaded_state, loaded_head = store.load_run(run_id)
    assert loaded_state.state_version == 3
    assert loaded_head == ev.event_hash
