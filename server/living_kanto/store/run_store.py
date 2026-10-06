"""SQLite-backed run store with append-only event log and hash-chained state."""

from __future__ import annotations

import json
import copy
import hashlib
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from living_kanto.contracts import CanonicalEvent, RunMetadata, StateUpdate, WorldState
from living_kanto.contracts.base import canonical_json, ContractError
from . import storage_layout as layout

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    world_revision TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    contracts_version TEXT NOT NULL,
    code_revision TEXT NOT NULL,
    mode TEXT NOT NULL,
    created_at TEXT NOT NULL,
    population_target INTEGER NOT NULL,
    population_actual INTEGER NOT NULL,
    data_directory TEXT NOT NULL,
    content_manifest_hash TEXT NOT NULL,
    model_usage TEXT NOT NULL,
    notes TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    head_hash TEXT NOT NULL,
    state_version INTEGER NOT NULL DEFAULT 0,
    state_hash TEXT NOT NULL,
    tick INTEGER NOT NULL DEFAULT 0,
    simulated_time REAL NOT NULL DEFAULT 0.0,
    state_json TEXT NOT NULL,
    genesis_json TEXT NOT NULL,
    genesis_hash TEXT NOT NULL,
    metadata_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    run_id TEXT NOT NULL,
    event_index INTEGER NOT NULL,
    event_id TEXT NOT NULL,
    event_hash TEXT NOT NULL,
    previous_head TEXT NOT NULL,
    state_after_hash TEXT NOT NULL,
    event_json TEXT NOT NULL,
    PRIMARY KEY (run_id, event_index),
    UNIQUE (run_id, event_id),
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
CREATE INDEX IF NOT EXISTS idx_events_run_index ON events(run_id, event_index);
"""


class StoreError(RuntimeError):
    """Raised when a store-level invariant is violated (fork, out-of-order, paused)."""


class RunStore:
    """One SQLite database, one writer thread at a time (guarded by a lock)."""

    def __init__(self, db_path: str | Path):
        self._db_path = str(db_path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA + layout.SCHEMA)
        # Lightweight migration: pre-genesis-persistence databases lack the
        # immutable genesis columns; add them without touching existing runs.
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(runs)")}
        if "genesis_json" not in cols:
            self._conn.execute("ALTER TABLE runs ADD COLUMN genesis_json TEXT")
        if "genesis_hash" not in cols:
            self._conn.execute("ALTER TABLE runs ADD COLUMN genesis_hash TEXT")
        for name, definition in [('storage_version', 'INTEGER NOT NULL DEFAULT 1'),
                                 ('checkpoint_interval', 'INTEGER NOT NULL DEFAULT 256'),
                                 ('prefix_digest', "TEXT NOT NULL DEFAULT ''")]:
            if name not in cols:
                self._conn.execute(f'ALTER TABLE runs ADD COLUMN {name} {definition}')
        self._conn.commit()
        self._verified_cache = {}
        self.last_recovery = {}

    @property
    def path(self) -> str:
        """Filesystem path of this store's SQLite database."""
        return self._db_path

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---------------------------------------------------------------- runs

    def create_run(self, metadata: RunMetadata, genesis_state: WorldState) -> str:
        """Create a new run with its genesis state. Returns run_id.

        Rejects malformed genesis *before* any insert: a declared ``state_hash``
        that does not match the content-recomputed hash, a genesis bound to a
        different ``run_id`` than the metadata, or a non-zero genesis
        ``state_version``. A rejected creation persists nothing.
        """
        metadata.validate()
        genesis_state.validate()
        if genesis_state.run_id != metadata.run_id:
            raise StoreError(
                f"genesis run_id {genesis_state.run_id!r} does not match "
                f"metadata run_id {metadata.run_id!r}"
            )
        if genesis_state.state_version != 0:
            raise StoreError(
                f"genesis state_version must be 0, got {genesis_state.state_version}"
            )
        if genesis_state.mode != metadata.mode:
            raise StoreError(
                f"genesis mode {genesis_state.mode!r} does not match metadata "
                f"mode {metadata.mode!r}"
            )
        genesis_hash = genesis_state.compute_state_hash()
        if not genesis_state.state_hash:
            raise StoreError("genesis declared state_hash must be present and non-empty")
        if genesis_state.state_hash != genesis_hash:
            raise StoreError(
                "genesis declared state_hash does not match the "
                "content-recomputed genesis hash"
            )
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO runs (run_id, world_id, world_revision, engine_version, "
                "contracts_version, code_revision, mode, created_at, population_target, "
                "population_actual, data_directory, content_manifest_hash, model_usage, "
                "notes, status, head_hash, state_version, state_hash, tick, simulated_time, "
                "state_json, genesis_json, genesis_hash, metadata_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, 0, ?, ?, ?, ?, ?, ?, ?)",
                (
                    metadata.run_id,
                    metadata.world_id,
                    metadata.world_revision,
                    metadata.engine_version,
                    metadata.contracts_version,
                    metadata.code_revision,
                    metadata.mode,
                    metadata.created_at,
                    metadata.population_target,
                    metadata.population_actual,
                    metadata.data_directory,
                    metadata.content_manifest_hash,
                    canonical_json(list(metadata.model_usage)),
                    metadata.notes,
                    "0" * 64,  # event-chain head seed, distinct from world hashes
                    genesis_hash,
                    genesis_state.tick,
                    genesis_state.simulated_time,
                    canonical_json(genesis_state.to_dict()),
                    canonical_json(genesis_state.to_dict()),
                    genesis_hash,
                    canonical_json(metadata.to_dict()),
                ),
            )
        return metadata.run_id

    def _get_run_row(self, run_id: str) -> sqlite3.Row:
        row = self._conn.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise StoreError(f"unknown run {run_id!r}")
        return row

    @contextmanager
    def _read_snapshot(self):
        """Bind multi-query integrity reads to one SQLite WAL snapshot.

        The Python lock protects this connection; BEGIN additionally protects
        against commits through another connection/process. Nested calls reuse
        the caller's read/write transaction and never finish it themselves.
        """
        with self._lock:
            owns_transaction = not self._conn.in_transaction
            if owns_transaction:
                self._conn.execute("BEGIN")
            try:
                yield
            finally:
                if owns_transaction:
                    self._conn.rollback()

    def _cache_key(self,row):
        # Counters detect raw writes through this handle and any other handle.
        # Full redundant row bindings also guard against poisoned metadata or
        # genesis/current snapshot substitution while a read transaction holds.
        data_version=self._conn.execute("PRAGMA data_version").fetchone()[0]
        return (data_version,self._conn.total_changes,tuple(row[key] for key in row.keys()))

    @staticmethod
    def _cached_copy(value):
        return copy.deepcopy(value) if isinstance(value, WorldState) else WorldState.from_dict(json.loads(value))

    def _read_current(self, row):
        try:
            return WorldState.from_dict(layout.read_state(self._conn,row))
        except (ValueError, KeyError, TypeError, layout.zlib.error) as exc:
            raise StoreError(f'Invalid stored world: {exc}') from exc

    @staticmethod
    def _decode_event(value):
        try:
            return CanonicalEvent.from_dict(layout.unpack(value))
        except (ValueError, TypeError, layout.zlib.error) as exc:
            raise StoreError(f'Invalid stored event: {exc}') from exc

    @staticmethod
    def _next_digest(prefix, event_hash):
        return hashlib.sha256((prefix + event_hash).encode('ascii')).hexdigest()

    def _write_checkpoint(self, state, head, prefix):
        self._conn.execute('INSERT OR REPLACE INTO storage_checkpoints VALUES (?,?,?,?,?,?)',
                           (state.run_id,state.state_version,head,state.state_hash,prefix,layout.pack(state.to_dict())))
        # Checkpoints are derived acceleration data; retain two, never remove events.
        self._conn.execute('DELETE FROM storage_checkpoints WHERE run_id=? AND state_version NOT IN '
                           '(SELECT state_version FROM storage_checkpoints WHERE run_id=? ORDER BY state_version DESC LIMIT 2)',
                           (state.run_id,state.run_id))

    def _reject_write_triggers(self):
        # Store-owned schema has no triggers. Unknown triggers could change
        # archive/history rows while a trusted append is preparing its cache.
        trigger=self._conn.execute("SELECT name FROM (SELECT name,type,tbl_name FROM sqlite_master UNION ALL "
                                   "SELECT name,type,tbl_name FROM sqlite_temp_master) WHERE type='trigger' AND tbl_name IN "
                                   "('runs','events','storage_records','storage_archive','storage_checkpoints') LIMIT 1").fetchone()
        if trigger is not None:
            raise StoreError('Unsupported trigger on canonical storage: '+trigger[0])

    def optimize_storage(self, run_id, checkpoint_interval=256):
        """Full-audit legacy data, then atomically upgrade its physical representation.

        Canonical event bytes, hashes, identities and world contents do not change.
        Use on a consistent backup or with the simulation paused. Older binaries
        cannot read v2; rollback uses the preserved v1 database and source together.
        """
        if type(checkpoint_interval) is not int or not 1 <= checkpoint_interval <= 10000:
            raise ValueError('Checkpoint interval must be 1 through 10000')
        with self._lock:
            try:
                self._conn.execute('BEGIN IMMEDIATE')
                row=self._get_run_row(run_id)
                self._reject_write_triggers()
                if row['storage_version'] == 2:
                    self._conn.rollback()
                    return self.storage_status(run_id)
                state=self.replay(run_id)
                prefix=row['genesis_hash']
                for event in self.iter_events(run_id):
                    prefix=self._next_digest(prefix,event.event_hash)
                    self._conn.execute('UPDATE events SET event_json=? WHERE run_id=? AND event_index=?',
                                       (layout.pack(event.to_dict()),run_id,event.event_index))
                layout.write_records(self._conn,state)
                self._conn.execute('UPDATE runs SET storage_version=2,checkpoint_interval=?,prefix_digest=?,state_json=? WHERE run_id=?',
                                   (checkpoint_interval,prefix,canonical_json(layout.header(state)),run_id))
                self._write_checkpoint(state,row['head_hash'],prefix)
                if self._read_current(self._get_run_row(run_id)).to_dict() != state.to_dict():
                    raise StoreError('Storage migration changed world contents')
                self._conn.commit()
                self._verified_cache.pop(run_id,None)
            except Exception:
                self._conn.rollback()
                raise
        return self.storage_status(run_id)

    def storage_status(self, run_id):
        with self._read_snapshot():
            row=self._get_run_row(run_id)
            checkpoint=self._conn.execute('SELECT MAX(state_version) FROM storage_checkpoints WHERE run_id=?',(run_id,)).fetchone()[0]
            return {'storage_version':row['storage_version'],'state_version':row['state_version'],
                    'checkpoint_version':checkpoint,'checkpoint_interval':row['checkpoint_interval'],
                    'event_payload_bytes':self._conn.execute('SELECT COALESCE(SUM(length(event_json)),0) FROM events WHERE run_id=?',(run_id,)).fetchone()[0],
                    'recovery':dict(self.last_recovery)}

    def _recover_checkpoint(self, run_id):
        """Validate EVERY event's content/chain, replay only the checkpoint tail.

        Prefix digest anchors a checkpoint to the exact fully verified history
        that produced it. Corruption fails closed; explicit replay stays genesis
        based. An external write invalidates the warm cache and repeats this audit.
        """
        with self._read_snapshot():
            row=self._get_run_row(run_id)
            meta=RunMetadata.from_dict(json.loads(row['metadata_json']))
            if meta.run_id != run_id or meta.mode != row['mode']:
                raise StoreError('Loaded metadata identity does not match runs row')
            genesis=self.load_genesis(run_id)
            cp=self._conn.execute('SELECT * FROM storage_checkpoints WHERE run_id=? ORDER BY state_version DESC LIMIT 1',(run_id,)).fetchone()
            if cp is None:
                raise StoreError('Version 2 save has no verified checkpoint; full audit required')
            try:
                state=WorldState.from_dict(layout.unpack(cp['state_blob'])).verify()
            except (ValueError, TypeError, layout.zlib.error) as exc:
                raise StoreError(f'Invalid checkpoint: {exc}') from exc
            if state.run_id != run_id or state.state_version != cp['state_version'] or state.state_hash != cp['state_hash']:
                raise StoreError('Checkpoint identity/hash does not match its binding')
            if not 0 <= cp['state_version'] <= row['state_version']:
                raise StoreError('Checkpoint version outside committed history')
            prefix=row['genesis_hash'];head='0'*64;previous_hash=genesis.state_hash;count=0;applied=0
            if cp['state_version'] == 0 and (state.to_dict()!=genesis.to_dict() or cp['head_hash']!=head or cp['prefix_digest']!=prefix):
                raise StoreError('Genesis checkpoint does not match verified genesis')
            for r in self._conn.execute('SELECT * FROM events WHERE run_id=? ORDER BY event_index',(run_id,)):
                event=self._decode_event(r['event_json']);tx=_state_update_from_event(event)
                eh=event.event_hash
                if (r['event_index'] != count or event.event_index != count or event.run_id != run_id
                    or tx.run_id != run_id or r['event_id'] != event.event_id
                    or r['event_hash'] != eh or r['previous_head'] != head or event.previous_head != head
                    or r['state_after_hash'] != tx.state_hash or tx.prior_state_hash != previous_hash
                    or tx.prior_state_version != count or event.state_version != count+1):
                    raise StoreError(f'History content/chain mismatch at event {count}')
                head=eh;previous_hash=tx.state_hash;prefix=self._next_digest(prefix,eh);count+=1
                if count == cp['state_version']:
                    if head != cp['head_hash'] or previous_hash != cp['state_hash'] or prefix != cp['prefix_digest']:
                        raise StoreError('Checkpoint prefix does not match verified history')
                    if state.tick != event.tick or state.simulated_time != event.simulated_time:
                        raise StoreError('Checkpoint clock does not match its anchor event')
                elif count > cp['state_version']:
                    state=tx.apply_to(state);applied+=1
                    if state.tick != event.tick or state.simulated_time != event.simulated_time:
                        raise StoreError('Checkpoint tail event counters disagree')
            current=self._read_current(row)
            current.verify()
            if (count != row['state_version'] or head != row['head_hash'] or prefix != row['prefix_digest']
                or state.to_dict() != current.to_dict() or state.state_hash != row['state_hash']
                or state.tick != row['tick'] or state.simulated_time != row['simulated_time']):
                raise StoreError('Recovered history does not match stored current world')
            self.last_recovery={'checked_events':count,'applied_events':applied,'checkpoint_version':cp['state_version']}
            return state

    def load_run(self, run_id: str) -> tuple[RunMetadata, WorldState, str]:
        """Return a copied, integrity-verified snapshot with a strict cache.

        Any SQLite write invalidates verification. Explicit replay always audits
        the entire chain; cache hits return freshly parsed independent objects.
        """
        with self._read_snapshot():
            row=self._get_run_row(run_id);key=self._cache_key(row)
            cached=self._verified_cache.get(run_id)
            if cached is not None and cached[0]==key:
                verified=self._cached_copy(cached[1])
            else:
                verified=self._recover_checkpoint(run_id) if row["storage_version"] == 2 else self.replay(run_id)
            metadata=RunMetadata.from_dict(json.loads(row["metadata_json"]))
            if metadata.run_id!=run_id or metadata.mode!=row["mode"]:
                raise StoreError(f"loaded metadata identity does not match the runs row for {run_id!r}")
            if cached is None or cached[0]!=key:
                self._verified_cache[run_id]=(key,copy.deepcopy(verified) if row["storage_version"] == 2 else canonical_json(verified.to_dict()))
            return metadata,verified,row["head_hash"]

    def load_head(self, run_id: str) -> str:
        """Return the current event-chain head hash for ``run_id``.

        This is the hash the next event's ``previous_head`` must reference:
        the 64-zero seed before the first event, then the latest event's
        ``event_hash``. Distinct from the world-state hash in ``state_hash``.
        """
        with self._lock:
            row = self._get_run_row(run_id)
        return "0" * 64 if row["state_version"] == 0 else row["head_hash"]

    def get_status(self, run_id: str) -> str:
        with self._lock:
            return self._get_run_row(run_id)["status"]

    def set_status(self, run_id: str, status: str) -> None:
        if status not in {"running", "paused"}:
            raise StoreError(f"invalid status {status!r}")
        with self._lock:
            try:
                if not self._conn.in_transaction:self._conn.execute("BEGIN IMMEDIATE")
                row=self._get_run_row(run_id)  # raises if unknown
                cached=self._verified_cache.get(run_id)
                before_key=self._cache_key(row)
                verified=cached is not None and cached[0]==before_key
                changed=row["status"]!=status
                if row["status"]!=status:
                    self._conn.execute(
                        "UPDATE runs SET status = ? WHERE run_id = ?", (status, run_id)
                    )
                # A status-only write cannot change verified canonical content.
                # Rekey only a matching prior cache, under the SQLite writer
                # lock; unknown/raw/external writes still require full replay.
                after=self._get_run_row(run_id);after_key=self._cache_key(after)
                status_only=(before_key[0]==after_key[0] and
                    after_key[1]-before_key[1]==int(changed) and
                    all(row[key]==after[key] for key in row.keys() if key!='status'))
                prepared=(after_key,cached[1]) if verified and status_only else None
                self._conn.commit()
                if prepared is not None:self._verified_cache[run_id]=prepared
                else:self._verified_cache.pop(run_id,None)
            except Exception:
                self._conn.rollback()
                raise

    # ---------------------------------------------------------------- events

    def append_event(self,event:CanonicalEvent,state_after_hash:str)->str:
        """Verify and append inside one SQLite writer transaction."""
        with self._lock:
            try:
                if not self._conn.in_transaction:self._conn.execute("BEGIN IMMEDIATE")
                prior=self.load_run(event.run_id)[1]
                return self._append_verified_event(event,state_after_hash,prior)
            except Exception:
                self._conn.rollback()
                raise

    def _append_verified_event(self, event: CanonicalEvent, state_after_hash: str, prior=None) -> str:
        """Append one event transactionally. Returns the new head hash.

        Verifies: run exists, run is running, event_index == next index,
        previous_head == stored head, event_hash recomputes, no duplicate event_id.
        """
        event.validate()
        event_hash = event.event_hash
        # Stored bindings must be genuine before the chain is extended: a runs
        # row corrupted out of agreement with genesis+event log is rejected
        # here, never silently appended onto.
        with self._lock:
            row = self._get_run_row(event.run_id)
            self._reject_write_triggers()
            if row["status"] != "running":
                raise StoreError(f"run {event.run_id!r} is {row['status']}; append rejected")
            # Reject duplicate event_id (same event re-applied at a new index)
            dup = self._conn.execute(
                "SELECT 1 FROM events WHERE run_id = ? AND event_id = ?",
                (event.run_id, event.event_id),
            ).fetchone()
            if dup is not None:
                raise StoreError(f"event {event.event_id!r} already exists in run {event.run_id!r}")
            next_index = row["state_version"]
            if event.event_index != next_index:
                raise StoreError(
                    f"event_index {event.event_index} != expected next index {next_index}"
                )
            # Event chain: index 0 links from the 64-zero seed; later events
            # link from the previous event's event_hash. This chain is
            # independent of world content hashes (see CONTRACT_NOTES).
            expected_head = "0" * 64 if next_index == 0 else row["head_hash"]
            if event.previous_head != expected_head:
                raise StoreError(
                    f"previous_head {event.previous_head[:12]}… does not match "
                    f"stored head {expected_head[:12]}… (fork or stale event)"
                )
            try:
                # Atomically commit the event AND the resulting world state.
                # Apply the event's contract StateUpdate to the stored state and
                # recompute the hash from actual content (never trust
                # caller-supplied text).
                if prior is None:
                    prior = self._read_current(row)
                if prior.state_hash != row["state_hash"]:
                    raise StoreError(
                        f"stored snapshot at event {event.event_index} does not recompute: "
                        f"declared {row['state_hash'][:12]}…, content hashes to "
                        f"{prior.state_hash[:12]}…"
                    )
                update = _state_update_from_event(event)
                # Apply the update to the EXACT stored prior state (never a
                # mutated base): apply_to verifies the prior hash/version and
                # recomputes the post hash from content. Elapsed time comes
                # from the update's own advance_clock deltas, so the event's
                # tick/simulated_time must equal the resulting counters.
                new_state = update.apply_to(prior)
                if (
                    event.tick != new_state.tick
                    or event.simulated_time != new_state.simulated_time
                ):
                    raise StoreError(
                        f"event {event.event_id} counters "
                        f"(tick={event.tick}, simulated_time={event.simulated_time}) "
                        f"do not match the resulting state "
                        f"(tick={new_state.tick}, simulated_time={new_state.simulated_time}); "
                        "elapsed time must come from advance_clock deltas in the transaction"
                    )
                # The recomputed hash must match the caller-supplied hash.
                if new_state.state_hash != state_after_hash:
                    raise StoreError(
                        f"state_after_hash mismatch: caller supplied {state_after_hash[:12]}… "
                        f"but content recomputes to {new_state.state_hash[:12]}…"
                    )
                is_v2 = row['storage_version'] == 2
                new_state_json = canonical_json(layout.header(new_state) if is_v2 else new_state.to_dict())
                if is_v2:
                    layout.write_records(self._conn,new_state,prior,update.changes)

                self._conn.execute(
                    "INSERT INTO events (run_id, event_index, event_id, event_hash, "
                    "previous_head, state_after_hash, event_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        event.run_id,
                        event.event_index,
                        event.event_id,
                        event_hash,
                        expected_head,
                        state_after_hash,
                        layout.pack(event.to_dict()) if is_v2 else canonical_json(event.to_dict()),
                    ),
                )
                self._conn.execute(
                    "UPDATE runs SET head_hash = ?, state_version = ?, tick = ?, "
                    "simulated_time = ?, state_hash = ?, state_json = ? WHERE run_id = ?",
                    (
                        event_hash,
                        event.event_index + 1,
                        new_state.tick,
                        new_state.simulated_time,
                        new_state.state_hash,
                        new_state_json,
                        event.run_id,
                    ),
                )
                if is_v2:
                    prefix = self._next_digest(row['prefix_digest'],event_hash)
                    self._conn.execute('UPDATE runs SET prefix_digest=? WHERE run_id=?',(prefix,event.run_id))
                    if new_state.state_version % row['checkpoint_interval'] == 0:
                        self._write_checkpoint(new_state,event_hash,prefix)
                # Trusted objects are private copies; callers cannot poison this cache.
                prepared=(self._cache_key(self._get_run_row(event.run_id)),
                          copy.deepcopy(new_state) if is_v2 else new_state_json)
                self._conn.commit()
                self._verified_cache[event.run_id]=prepared
            except Exception:
                self._conn.rollback()
                raise
            return event_hash

    def load_genesis(self, run_id: str) -> WorldState:
        """Return the immutable verified genesis state for ``run_id``.

        The genesis snapshot is stored separately from the mutable current
        snapshot and is never rewritten by appends. The stored content is
        re-hashed on every read and rejected if it does not match the stored
        genesis hash.
        """
        with self._lock:
            row = self._get_run_row(run_id)
        if not row["genesis_json"]:
            raise StoreError(f"run {run_id!r} has no persisted genesis snapshot")
        genesis_doc = json.loads(row["genesis_json"])
        genesis = WorldState.from_dict(genesis_doc)
        if genesis.run_id != run_id or genesis.mode != row["mode"]:
            raise StoreError(
                f"persisted genesis identity (run_id={genesis.run_id!r}, "
                f"mode={genesis.mode!r}) does not match the runs row "
                f"(run_id={run_id!r}, mode={row['mode']!r})"
            )
        recomputed = genesis.compute_state_hash()
        if recomputed != row["genesis_hash"] or genesis.state_hash != row["genesis_hash"]:
            raise StoreError(
                f"persisted genesis for run {run_id!r} does not verify: stored "
                f"{row['genesis_hash'][:12]}…, recomputed {recomputed[:12]}…"
            )
        return genesis

    def replay(self, run_id: str) -> WorldState:
        """Rebuild the full world state from the stored genesis + event log.

        Deterministic and model-free: starts at the verified immutable genesis
        (never the mutable current snapshot), applies event 0 onward through the
        contract ``StateUpdate.apply_to`` path, and validates after every event:
        event chain linkage, resulting state hash/version against the event's
        declared post-state, and finally the whole rebuilt state against the
        stored current snapshot.
        """
        with self._read_snapshot():
            row = self._get_run_row(run_id)
            # Redundant identity bindings: the metadata blob and the runs-row
            # columns must agree on run_id and mode before anything is trusted.
            try:
                meta_doc = json.loads(row["metadata_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise StoreError(f"run {run_id!r} metadata_json is not parseable") from exc
            if meta_doc.get("run_id") != run_id:
                raise StoreError(
                    f"metadata_json run_id {meta_doc.get('run_id')!r} does not match "
                    f"the runs row run_id {run_id!r}"
                )
            if meta_doc.get("mode") != row["mode"]:
                raise StoreError(
                    f"metadata_json mode {meta_doc.get('mode')!r} does not match "
                    f"the runs row mode {row['mode']!r}"
                )
            if not row["genesis_json"]:
                raise StoreError(f"run {run_id!r} has no persisted genesis snapshot")
            genesis_doc = json.loads(row["genesis_json"])
            genesis = WorldState.from_dict(genesis_doc)
            if genesis.run_id != run_id or genesis.mode != row["mode"]:
                raise StoreError(
                    f"persisted genesis identity (run_id={genesis.run_id!r}, "
                    f"mode={genesis.mode!r}) does not match the runs row "
                    f"(run_id={run_id!r}, mode={row['mode']!r})"
                )
            if genesis.compute_state_hash() != row["genesis_hash"]:
                raise StoreError(f"persisted genesis for run {run_id!r} does not verify")
            event_rows = self._conn.execute(
                "SELECT event_index, event_id, event_hash, previous_head, "
                "state_after_hash, event_json FROM events "
                "WHERE run_id = ? ORDER BY event_index",
                (run_id,),
            ).fetchall()
            current = self._read_current(row)

        if event_rows and event_rows[0]["event_index"] != 0:
            raise StoreError(f"run {run_id!r} event log does not start at index 0")

        state = genesis
        head = "0" * 64  # event-chain seed: distinct from any world-state hash
        for r in event_rows:
            event = self._decode_event(r["event_json"])
            if event.run_id != run_id:
                raise StoreError(
                    f"event {event.event_id} belongs to run {event.run_id!r}, "
                    f"not {run_id!r}"
                )
            if r["event_index"] != event.event_index:
                raise StoreError(
                    f"event log index column {r['event_index']} does not match "
                    f"event_json index {event.event_index}"
                )
            if r["event_id"] != event.event_id:
                raise StoreError(
                    f"event log id column {r['event_id']!r} does not match "
                    f"event_json id {event.event_id!r}"
                )
            if r["previous_head"] != event.previous_head:
                raise StoreError(
                    f"event {event.event_id} previous_head column does not match "
                    "the event payload"
                )
            if event.event_hash != r["event_hash"]:
                raise StoreError(
                    f"event {event.event_id} stored event_hash does not match the "
                    f"recomputed content hash {event.event_hash[:12]}\u2026"
                )
            if event.event_index != state.state_version:
                raise StoreError(
                    f"replay version mismatch at event {event.event_index}: "
                    f"state version is {state.state_version}"
                )
            if event.previous_head != head:
                raise StoreError(
                    f"replay chain mismatch at event {event.event_index}: "
                    f"previous_head does not follow the stored chain"
                )
            update = _state_update_from_event(event)
            state = update.apply_to(state)
            if state.state_hash != update.state_hash:
                raise StoreError(
                    f"replay hash mismatch at event {event.event_index}: rebuilt "
                    f"{state.state_hash[:12]}… != transaction-declared {update.state_hash[:12]}…"
                )
            if state.state_hash != r["state_after_hash"]:
                raise StoreError(
                    f"replay hash mismatch at event {event.event_index}: rebuilt "
                    f"{state.state_hash[:12]}… != logged {r['state_after_hash'][:12]}…"
                )
            if state.state_version != event.state_version:
                raise StoreError(
                    f"replay version mismatch at event {event.event_index}: rebuilt "
                    f"{state.state_version} != event-declared {event.state_version}"
                )
            head = event.event_hash

        if state.to_dict() != current.to_dict():
            raise StoreError(
                "replay hash mismatch: full rebuilt state does not equal the stored "
                "current snapshot"
            )
        if state.state_hash != current.state_hash:
            raise StoreError(
                f"replay hash mismatch: rebuilt {state.state_hash[:12]}… != stored "
                f"current {current.state_hash[:12]}…"
            )
        # Redundant runs-row bindings must agree with the replayed chain.
        if row["state_version"] != state.state_version:
            raise StoreError(
                f"runs.state_version {row['state_version']} does not match the "
                f"replayed version {state.state_version}"
            )
        if row["tick"] != state.tick:
            raise StoreError(
                f"runs.tick {row['tick']} does not match the replayed tick {state.tick}"
            )
        if row["simulated_time"] != state.simulated_time:
            raise StoreError(
                f"runs.simulated_time {row['simulated_time']} does not match the "
                f"replayed simulated_time {state.simulated_time}"
            )
        if state.state_hash != row["state_hash"]:
            raise StoreError(
                f"runs.state_hash {str(row['state_hash'])[:12]}… does not match the "
                f"replayed state hash {state.state_hash[:12]}…"
            )
        expected_head = "0" * 64 if not event_rows else head
        if row["head_hash"] != expected_head:
            raise StoreError(
                f"runs.head_hash {str(row['head_hash'])[:12]}… does not match the "
                f"replayed chain head {expected_head[:12]}…"
            )
        return state

    def iter_events(self, run_id: str, after_index: int = -1) -> list[CanonicalEvent]:
        """Return events with index > after_index, in order."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT event_json FROM events WHERE run_id = ? AND event_index > ? ORDER BY event_index",
                (run_id, after_index),
            ).fetchall()
        return [self._decode_event(r["event_json"]) for r in rows]

    def event_count(self, run_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM events WHERE run_id = ?", (run_id,)
            ).fetchone()
        return row["n"]

    @property
    def _db(self):
        """Connection handle for integrity tests that bypass the store API."""
        return self._conn


def _state_update_from_event(event: CanonicalEvent) -> StateUpdate:
    """Parse the event's transaction into a contract StateUpdate.

    Binds the update to the event itself so a transaction cannot claim a
    different event_id/index or a different hash chain than the event carries.
    """
    tx = event.transaction
    if not isinstance(tx, dict) or tx.get("kind") != "state_update":
        raise StoreError(f"event {event.event_id} transaction is not a state_update")
    try:
        update = StateUpdate.from_dict(tx)
    except ContractError as exc:
        raise StoreError(f"event {event.event_id} has an invalid state_update: {exc}") from exc
    if update.event_id != event.event_id or update.event_index != event.event_index:
        raise StoreError(f"event {event.event_id} transaction binds to a different event")
    if update.previous_head != event.previous_head:
        raise StoreError(f"event {event.event_id} transaction previous_head disagrees")
    return update
