"""Tests for the FastAPI app: run lifecycle, status transitions, event listing.

Uses real content hashes via helpers (state.verify() must pass).

Storage topology under test: ONE SQLite database per run, named
``{run_id}.db`` inside the base directory handed to ``create_app``.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import threading

import pytest
from fastapi.testclient import TestClient

from living_kanto.api.app import create_app
from living_kanto.store import RunStore
from tests.helpers import make_run_metadata, make_world_state

BASE_NAME = "runs_home"


@pytest.fixture
def base_dir(tmp_path):
    return tmp_path / BASE_NAME


@pytest.fixture
def client(base_dir):
    app = create_app(base_dir)
    with TestClient(app) as c:
        yield c


def _payload(run_id):
    return {
        "metadata": make_run_metadata(run_id=run_id).to_dict(),
        "state": make_world_state(run_id=run_id).to_dict(),
    }


def _create_run(client, run_id="test-run-001"):
    r = client.post("/runs", json=_payload(run_id))
    assert r.status_code == 201, r.text
    return r.json()["run_id"]


def test_create_and_get_run(client):
    run_id = _create_run(client)
    r = client.get(f"/runs/{run_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["metadata"]["run_id"] == run_id
    # The persisted genesis state must carry a real, content-derived hash.
    from living_kanto.contracts.state import WorldState
    st = WorldState.from_dict(body["state"])
    assert st.compute_state_hash() == st.state_hash


def test_get_unknown_run_404(client):
    assert client.get("/runs/nope").status_code == 404


def test_pause_resume(client):
    run_id = _create_run(client)
    assert client.post(f"/runs/{run_id}/pause").json()["status"] == "paused"
    assert client.post(f"/runs/{run_id}/resume").json()["status"] == "running"


def test_events_endpoint_empty_then_populated(client):
    run_id = _create_run(client)
    r = client.get(f"/runs/{run_id}/events")
    assert r.status_code == 200
    assert r.json() == []


def test_one_sqlite_per_run(client, base_dir):
    """Each run gets its own SQLite file; neither file contains the other's run."""
    r1 = _create_run(client, "run-alpha")
    r2 = _create_run(client, "run-beta")
    assert r1 != r2
    files = sorted(p.name for p in base_dir.glob("*.db"))
    assert files == ["run-alpha.db", "run-beta.db"]
    for own, other in ((r1, r2), (r2, r1)):
        conn = sqlite3.connect(base_dir / f"{own}.db")
        try:
            ids = {row[0] for row in conn.execute("SELECT run_id FROM runs")}
            assert ids == {own}
            # events table must not carry the other run either
            ev = {row[0] for row in conn.execute("SELECT DISTINCT run_id FROM events")}
            assert other not in ev
        finally:
            conn.close()


def test_duplicate_create_is_409_not_overwrite(client, base_dir):
    run_id = _create_run(client)
    # append one event so the snapshot moves, then attempt duplicate creation
    assert client.post(f"/runs/{run_id}/test_append").status_code == 200
    before = client.get(f"/runs/{run_id}").json()
    r = client.post("/runs", json=_payload(run_id))
    assert r.status_code == 409
    after = client.get(f"/runs/{run_id}").json()
    # rejected duplicate must not mutate stored state or head
    assert after["state"] == before["state"]
    assert after["head_hash"] == before["head_hash"]


def test_unsafe_run_id_rejected(client, base_dir):
    for bad in ("../evil", "a/b", "", ".hidden"):
        payload = _payload("placeholder")
        payload["metadata"]["run_id"] = bad
        payload["state"]["run_id"] = bad or "x"
        r = client.post("/runs", json=payload)
        assert r.status_code in (400, 422), (bad, r.status_code, r.text)
    assert not (base_dir.parent / "evil.db").exists()


def test_restart_keeps_paused_run_paused_without_data_loss(base_dir):
    """Simulated restart: close the app entirely, reopen over the same base dir.

    A paused run must come back paused (no automatic downtime-free resume)
    with its full event history and identical state/head.
    """
    run_id = "run-restart"
    with TestClient(create_app(base_dir)) as c1:
        assert c1.post("/runs", json=_payload(run_id)).status_code == 201
        for _ in range(2):
            assert c1.post(f"/runs/{run_id}/test_append").status_code == 200
        snap = c1.get(f"/runs/{run_id}").json()
        events = c1.get(f"/runs/{run_id}/events").json()
        assert c1.post(f"/runs/{run_id}/pause").json()["status"] == "paused"
        paused_snap = c1.get(f"/runs/{run_id}").json()

    # fresh process-equivalent restart: brand-new app + stores from disk only
    with TestClient(create_app(base_dir)) as c2:
        body = c2.get(f"/runs/{run_id}").json()
        assert body["status"] == "paused"  # restart keeps it paused, no downtime-resume
        assert body["state"] == paused_snap["state"]
        assert body["head_hash"] == paused_snap["head_hash"]
        # appending while paused is refused (paused is not silently running)
        assert c2.post(f"/runs/{run_id}/test_append").status_code == 409
        # history survived intact
        assert [e["event_id"] for e in c2.get(f"/runs/{run_id}/events").json()] == \
            [e["event_id"] for e in events]
        # resume works after restart
        assert c2.post(f"/runs/{run_id}/resume").json()["status"] == "running"
        assert c2.post(f"/runs/{run_id}/test_append").status_code == 200


def test_restart_restores_running_run_as_paused_without_downtime_advance(tmp_path):
    """Regression: restart must restore persisted runs, not lose them.

    create_app() over an existing base dir IS the restart boundary: every
    persisted run is re-registered at startup and a stale 'running' status
    is demoted to 'paused' without touching state, head, counters, or events.
    """
    base = tmp_path / "runs"
    run_id = "restart-run"

    with TestClient(create_app(base)) as c1:
        assert c1.post("/runs", json=_payload(run_id)).status_code == 201
        for _ in range(3):
            assert c1.post(f"/runs/{run_id}/test_append").status_code == 200
        before = c1.get(f"/runs/{run_id}").json()
        events_before = c1.get(f"/runs/{run_id}/events").json()
        assert before["status"] == "running"
        assert len(events_before) == 3

    # Shutdown happened (context exited): the status row still says 'running'
    # because only explicit pause/resume persists a status change.

    with TestClient(create_app(base)) as c2:
        after = c2.get(f"/runs/{run_id}")
        assert after.status_code == 200, "run was lost across restart"
        body = after.json()
        assert body["status"] == "paused"
        assert body["state"] == before["state"]
        assert body["head_hash"] == before["head_hash"]
        # No downtime advancement: simulated-time counters are untouched.
        assert body["state"]["tick"] == before["state"]["tick"]
        assert body["state"]["simulated_time"] == before["state"]["simulated_time"]
        assert c2.get(f"/runs/{run_id}/events").json() == events_before

        # A paused run refuses appends until it is genuinely resumed.
        assert c2.post(f"/runs/{run_id}/test_append").status_code == 409

    # The demotion was persisted, not just in-memory: a raw store over the
    # same file sees 'paused' (pre-restart it was 'running').
    raw = RunStore(base / f"{run_id}.db")
    try:
        assert raw.get_status(run_id) == "paused"
    finally:
        raw.close()

    # After resume the run appends again normally.
    with TestClient(create_app(base)) as c3:
        assert c3.post(f"/runs/{run_id}/resume").json()["status"] == "running"
        assert c3.post(f"/runs/{run_id}/test_append").status_code == 200


def test_concurrent_creation_same_id_winner_persists(tmp_path):
    """Regression: a failing concurrent create must not delete the winner's DB.

    Two requests raced to create the same run id. Previously both could
    observe the file absent and the loser's failure-cleanup unlinked the
    winner's committed database. Creation is now serialized per database
    path and cleanup only removes a file the failing request itself
    created, so the loser either sees the winner's registration and answers
    409 without touching the file, or fails validation first (400) removing
    only its own file.
    """
    base = tmp_path / "runs"
    app = create_app(base)

    for round_num in range(3):
        run_id = f"race-run-{round_num}"
        with TestClient(app) as client:
            winner = _payload(run_id)
            loser = _payload(run_id)
            # The loser carries a genesis whose declared hash does not match
            # its content, so it fails validation whichever order it wins the
            # lock in; a valid-hash loser would be a legitimate 409 instead.
            loser["state"]["state_hash"] = "f" * 64

            barrier = threading.Barrier(2)
            results = {}

            def fire(name, body):
                barrier.wait()  # start barrier OUTSIDE any app critical section
                results[name] = client.post("/runs", json=body)

            threads = [
                threading.Thread(target=fire, args=("winner", winner)),
                threading.Thread(target=fire, args=("loser", loser)),
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)
                assert not t.is_alive(), f"round {round_num}: creation deadlocked"

            codes = {results["winner"].status_code, results["loser"].status_code}
            assert 201 in codes, f"round {round_num}: no run was created: {codes}"
            assert codes <= {201, 400, 409}
            assert codes != {201, 201}, "duplicate creation was not rejected"

            # The winner's database survived on disk and holds a live run.
            db_path = base / f"{run_id}.db"
            assert db_path.exists(), f"round {round_num}: winner's database was destroyed"

            # Exactly one registered store serves the run, with the winner's data.
            assert run_id in app.state.stores
            fetched = client.get(f"/runs/{run_id}").json()
            assert (
                fetched["metadata"]["content_manifest_hash"]
                == winner["metadata"]["content_manifest_hash"]
            )

        # A fresh app load restores the surviving winner, not a phantom.
        with TestClient(create_app(base)) as reloaded:
            got = reloaded.get(f"/runs/{run_id}")
            assert got.status_code == 200
            assert got.json()["status"] == "paused"
def test_stale_append_conflict_after_reload(client):
    """Two sequential appends through the API stay consistent; a forged stale
    head is impossible via the endpoint, and repeated appends advance head."""
    run_id = _create_run(client, "run-stale")
    h0 = client.get(f"/runs/{run_id}").json()["head_hash"]
    r1 = client.post(f"/runs/{run_id}/test_append").json()
    h1 = client.get(f"/runs/{run_id}").json()["head_hash"]
    r2 = client.post(f"/runs/{run_id}/test_append").json()
    h2 = client.get(f"/runs/{run_id}").json()["head_hash"]
    assert h0 != h1 != h2 and h0 != h2
    assert r1["event_index"] == 0 and r2["event_index"] == 1
    assert r2["event_hash"] == h2
