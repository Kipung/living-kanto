"""FastAPI app: run lifecycle, event log, status, WebSocket snapshot.

Storage topology: ONE SQLite database per run. ``create_app(base_dir)`` treats
``base_dir`` as the home for per-run databases named ``{run_id}.db``. There is
no shared/global database; opening a run lazily opens (and registers) only its
own store, and shutdown closes every registered store.
"""

from __future__ import annotations

import asyncio
import re
import sqlite3
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Body
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from living_kanto.contracts import CanonicalEvent, ContractError, RunMetadata, StateUpdate, WorldState
from living_kanto.store import RunStore, StoreError

# run_id must be a safe filename component: no separators, no dot-leading,
# no '..'. This prevents path traversal via the run_id in URLs or payloads.
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class CreateRunRequest(BaseModel):
    metadata: dict
    state: dict


def _safe_run_id(run_id: str) -> bool:
    return bool(_RUN_ID_RE.match(run_id)) and ".." not in run_id


# Per-database-file creation/open locks, keyed by absolute db path string.
# Keyed at module level (not per-app) so two app instances opened over the
# same base dir inside one process still serialize the check-create-register
# window for the same run file. This is the registry-ownership lock: without
# it, two overlapping creates could both observe the file absent and the
# loser's failure-cleanup could unlink the winner's committed database.
_CREATE_LOCKS: dict[str, threading.Lock] = {}
_CREATE_LOCKS_GUARD = threading.Lock()


def _creation_lock(path: Path) -> threading.Lock:
    key = str(path)
    with _CREATE_LOCKS_GUARD:
        lock = _CREATE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _CREATE_LOCKS[key] = lock
        return lock


def _safe_file(root: Path, rel: str) -> Path | None:
    """Resolve ``rel`` inside ``root`` for read-only static serving.

    Returns the target path only if every component is a plain name (no
    ``.``/``..``/empty), the fully resolved target (symlinks included)
    stays inside the resolved root, and it is an existing regular file.
    Anything else returns None so callers answer 404 without revealing
    whether a check failed or the file is absent.
    """
    if not rel or rel.startswith(("/", "\\")) or "\x00" in rel:
        return None
    parts = rel.replace("\\", "/").split("/")
    if any(p in ("", ".", "..") for p in parts):
        return None
    root_resolved = root.resolve()
    target = (root_resolved / Path(*parts)).resolve()
    if target == root_resolved or root_resolved not in target.parents:
        return None
    return target if target.is_file() else None


def create_app(
    base_dir: str | Path,
    *,
    content_root: str | Path | None = None,
    client_root: str | Path | None = None,
) -> FastAPI:
    """Create the API over a base directory holding one SQLite file per run.

    Also serves same-origin read-only static routes (m0-service-002 phase 1):
    ``/content/<path>`` from the original content tree, ``/client/<path>``
    from the frontend bundle, and ``/`` from ``client/index.html`` when
    present (explicit 404 JSON otherwise). Roots default to
    ``base_dir/content`` and ``base_dir/client`` and are configurable via
    ``content_root`` / ``client_root``. Neither root is created or written.
    """
    app = FastAPI(title="Living Kanto", version="0.1.0")
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)

    # Read-only static roots (never created here: a missing client root must
    # surface as an explicit "client bundle missing" response, not be
    # silently invented).
    content_dir = Path(content_root) if content_root is not None else base / "content"
    client_dir = Path(client_root) if client_root is not None else base / "client"

    # Registry of opened stores: run_id -> RunStore. Each store owns exactly
    # one SQLite file: base / f"{run_id}.db".
    stores: dict[str, RunStore] = {}
    app.state.base_dir = base
    app.state.stores = stores
    app.state.content_dir = content_dir
    app.state.client_dir = client_dir
    app.state.creation_lock = _creation_lock

    def _db_path(run_id: str) -> Path:
        if not _safe_run_id(run_id):
            raise HTTPException(status_code=400, detail=f"run_id {run_id!r} is not a safe identifier")
        return base / f"{run_id}.db"

    def _open_store(run_id: str) -> RunStore:
        """Return the store for an existing run, opening its DB lazily.

        Runs under the same per-file lock as creation so at most one store
        handle is ever registered per run file, and an open can never observe
        (or clean up) a database mid-creation.
        """
        path = _db_path(run_id)
        with _creation_lock(path):
            if run_id in stores:
                return stores[run_id]
            if not path.exists():
                raise HTTPException(status_code=404, detail=f"no database for run {run_id}")
            store = RunStore(path)
            stores[run_id] = store
            return store

    def _recover_existing_runs() -> None:
        """Restore persisted runs at app construction (simulated restart).

        The engine was down; nothing advanced while it was down, and a run
        must not auto-resume across downtime: any run persisted as
        ``running`` is restored as ``paused``. Only the runs.status column is
        written - state, head, tick/simulated-time counters and event history
        are left byte-identical, so there is no downtime advancement.
        """
        for db in sorted(base.glob("*.db")):
            run_id = db.stem
            lock = _creation_lock(db)
            store = None
            try:
                with lock:
                    if run_id in stores:
                        continue
                    store = RunStore(db)
                    if store.get_status(run_id) == "running":
                        store.set_status(run_id, "paused")
                    stores[run_id] = store
                    store = None
            except (StoreError, sqlite3.Error, OSError):
                # Not a usable per-run store (foreign/corrupt file, or the
                # run row disagrees with the filename): leave it unregistered
                # and let lazy open decide on demand.
                if store is not None:
                    try:
                        store.close()
                    except Exception:
                        pass

    @app.on_event("shutdown")
    def shutdown():
        for controller in getattr(app.state, "runtime_controllers", {}).values():
            controller.close()
        for store in list(stores.values()):
            store.close()
        stores.clear()

    @app.get("/health")
    def health():
        return {"status": "ok", "engine": "living-kanto"}

    @app.post("/runs", status_code=201)
    def create_run(req: CreateRunRequest):
        try:
            metadata = RunMetadata.from_dict(req.metadata)
            state = WorldState.from_dict(req.state)
        except (ValueError, ContractError) as e:
            raise HTTPException(status_code=400, detail=str(e))

        if metadata.world_id == "living-kanto":
            raise HTTPException(403, detail="Production worlds must be initialized through /worlds")
        path = _db_path(metadata.run_id)
        # The whole existence-check -> create -> register window is held under
        # this run file's lock. A losing concurrent request therefore either
        # sees the winner's file/registration and answers 409 WITHOUT touching
        # the file, or runs first and can only ever unlink its OWN fresh file.
        with _creation_lock(path):
            if metadata.run_id in stores or path.exists():
                raise HTTPException(
                    status_code=409,
                    detail=f"run {metadata.run_id} already exists (one SQLite per run: {path.name})",
                )
            store = None
            try:
                store = RunStore(path)
                run_id = store.create_run(metadata, state)
                store.optimize_storage(run_id)
            except (StoreError, ContractError, ValueError) as e:
                # Failed creation must not leave a half-owned store registered.
                # Under the lock the file did not exist beforehand, so any
                # file here is this request's own; an accepted run's database
                # can never be deleted from this path.
                if store is not None:
                    store.close()
                if path.exists() and metadata.run_id not in stores:
                    path.unlink()
                raise HTTPException(status_code=400, detail=str(e))
            stores[metadata.run_id] = store
        return {"run_id": run_id}

    @app.get("/runs/{run_id}")
    def get_run(run_id: str):
        store = _open_store(run_id)
        try:
            metadata, state, head = store.load_run(run_id)
        except StoreError as e:
            raise HTTPException(status_code=404, detail=str(e))
        return {
            "run_id": run_id,
            "status": store.get_status(run_id),
            "head_hash": head,
            "state": state.to_dict(),
            "metadata": metadata.to_dict(),
        }

    @app.post("/runs/{run_id}/pause")
    def pause_run(run_id: str):
        store = _open_store(run_id)
        try:
            if run_id in getattr(app.state, "runtime_controllers", {}):
                app.state.runtime_controllers[run_id].pause()
            else:
                store.set_status(run_id, "paused")
        except StoreError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"run_id": run_id, "status": "paused"}

    @app.post("/runs/{run_id}/resume")
    def resume_run(run_id: str, options: dict | None = Body(default=None)):
        store = _open_store(run_id)
        try:
            metadata, _, _ = store.load_run(run_id)
            if metadata.world_id == "living-kanto":
                try: app.state.get_runtime_controller(run_id).resume((options or {}).get("speed"))
                except (ValueError, RuntimeError) as exc: raise HTTPException(400, detail=str(exc))
            else:
                store.set_status(run_id, "running")
        except StoreError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"run_id": run_id, "status": "running"}

    @app.get("/runs/{run_id}/events")
    def get_events(run_id: str, after: int = -1):
        store = _open_store(run_id)
        try:
            events = store.iter_events(run_id, after_index=after)
        except StoreError as e:
            raise HTTPException(status_code=404, detail=str(e))
        return [e.to_dict() for e in events]

    @app.post("/runs/{run_id}/test_append")
    def test_append(run_id: str):
        """Append one canonical time.advanced event through the real contract
        and store paths (no models). The transaction is a real StateUpdate;
        the store re-verifies prior hash/version, applies the delta, and
        persists event + snapshot + version + head atomically.
        """
        store = _open_store(run_id)
        try:
            metadata, state, head = store.load_run(run_id)
        except StoreError as e:
            raise HTTPException(status_code=404, detail=str(e))
        if metadata.world_id == "living-kanto":
            raise HTTPException(403, detail="Test actions are prohibited in production worlds")
        if store.get_status(run_id) != "running":
            raise HTTPException(status_code=409, detail=f"run {run_id} is not running")

        event_index = store.event_count(run_id)
        event_id = f"evt-test-{run_id}-{event_index:06d}"
        changes = [
            {"op": "set", "path": f"pokemon.test_{event_index:06d}.species", "value": "pikachu"},
            {"op": "set", "path": f"world_facts.test_append_{event_index}", "value": event_index},
            {"op": "advance_clock", "seconds": 1},
        ]
        try:
            post = state.with_advanced_version(changes)
            transaction = StateUpdate(
                schema_version=1,
                run_id=run_id,
                event_id=event_id,
                event_index=event_index,
                prior_state_version=state.state_version,
                prior_state_hash=state.state_hash,
                state_version=post.state_version,
                previous_head=head,
                state_hash=post.state_hash,
                changes=tuple(changes),
            )
            transaction.validate()
            event = CanonicalEvent(
                schema_version=1,
                run_id=run_id,
                event_id=event_id,
                event_index=event_index,
                state_version=post.state_version,
                previous_head=head,
                event_kind="time.advanced",
                tick=state.tick + 1,
                simulated_time=state.simulated_time + 1,
                real_wall_time=f"test-append-{event_index:06d}",
                causation={"kind": "system", "actor_id": "engine", "action_id": event_id},
                affected=[],
                before={},
                after={},
                deterministic_inputs={"source": "test_append"},
                transaction=transaction.to_dict(),
                visibility={"public": True, "private": {}},
            )
            event.validate()
            event_hash = store.append_event(event, post.state_hash)
        except (ContractError, StoreError) as e:
            raise HTTPException(status_code=409, detail=str(e))

        _, new_state, _ = store.load_run(run_id)
        return {
            "run_id": run_id,
            "event_id": event.event_id,
            "event_index": event.event_index,
            "event_hash": event_hash,
            "state": new_state.to_dict(),
        }

    # --- Same-origin static serving (m0-service-002 phase 1) -------------
    # Read-only views over the original content tree and the frontend
    # bundle. Traversal and symlink escapes resolve to 404, never to a
    # file outside the configured root.
    @app.get("/content/{path:path}")
    def content_file(path: str):
        target = _safe_file(content_dir, path)
        if target is None:
            raise HTTPException(status_code=404, detail=f"no such content file: {path}")
        return FileResponse(target)

    @app.get("/client/{path:path}")
    def client_file(path: str):
        target = _safe_file(client_dir, path)
        if target is None:
            raise HTTPException(status_code=404, detail=f"no such client file: {path}")
        return FileResponse(target)

    @app.get("/")
    def root_index():
        # Route through the same containment check as /client/<path>: a
        # symlinked index.html pointing outside client_root must be
        # rejected (404), not served.
        target = _safe_file(client_dir, "index.html")
        if target is not None:
            return FileResponse(target)
        return JSONResponse(
            status_code=404,
            content={
                "detail": "client bundle missing",
                "checked": str(client_dir / "index.html"),
                "hint": "build the frontend into this directory or pass client_root to create_app",
            },
        )

    @app.websocket("/ws/{run_id}")
    async def ws_snapshot(websocket: WebSocket, run_id: str, after: int = -1):
        await websocket.accept()
        try:
            store = _open_store(run_id)
        except (StoreError, HTTPException):
            await websocket.close(code=4004)
            return

        def capture(cursor, previous_status=None):
            # One database snapshot binds head, event cursor, and state even
            # when another process writes while this viewer reconnects.
            with store._read_snapshot():
                row = store._get_run_row(run_id)
                if previous_status is not None and cursor == row["state_version"] - 1 and previous_status == row["status"]:
                    return None
                _, state, head = store.load_run(run_id)
                if cursor < -1 or cursor >= state.state_version:
                    if not (cursor == -1 and state.state_version == 0):
                        raise ValueError("event cursor outside committed history")
                return {"run_id": run_id, "status": store.get_status(run_id),
                        "head_hash": head, "event_cursor": state.state_version - 1,
                        "state": state.to_dict(),
                        "events": [event.to_dict() for event in store.iter_events(run_id, cursor)]}

        try:
            snapshot = await asyncio.to_thread(capture, after)
            await websocket.send_json({"type": "snapshot", **snapshot})
            cursor = snapshot["event_cursor"]
            status = snapshot["status"]
            while True:
                try:
                    message = await asyncio.wait_for(websocket.receive_text(), timeout=0.25)
                    if message == "ping":
                        await websocket.send_json({"type": "pong"})
                except asyncio.TimeoutError:
                    pass
                update = await asyncio.to_thread(capture, cursor, status)
                if update is None:
                    continue
                if update["event_cursor"] != cursor or update["status"] != status:
                    await websocket.send_json({"type": "update", **update})
                    cursor, status = update["event_cursor"], update["status"]
        except WebSocketDisconnect:
            pass
        except ValueError as exc:
            await websocket.send_json({"type": "error", "detail": str(exc)})
            await websocket.close(code=4009)
        except (StoreError, sqlite3.Error):
            await websocket.close(code=4004)

    # A freshly constructed app over an existing base dir IS the restart
    # boundary: restore persisted runs now so no request can ever observe -
    # or act on - a run that self-resumed through downtime.
    _recover_existing_runs()
    from .world_api import install_world_routes
    install_world_routes(app, _open_store, _safe_run_id, _creation_lock)

    return app


def main() -> None:
    """Loopback launcher (see tools/run_local.sh): host 127.0.0.1, port 8877.

    ``python -m living_kanto.api.app --data-dir ... --content-root ...
    --client-root ...``
    """
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Living Kanto local service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8877)
    parser.add_argument("--data-dir", default="data/local", help="base dir holding one SQLite file per run")
    parser.add_argument("--content-root", default="content", help="read-only original content tree")
    parser.add_argument("--client-root", default="client", help="frontend bundle directory")
    args = parser.parse_args()
    app = create_app(
        args.data_dir,
        content_root=args.content_root,
        client_root=args.client_root,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
