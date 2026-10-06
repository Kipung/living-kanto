# Storage version 2

No world reset is required. Simulation contracts and portable exports remain version1; this is a versioned SQLite physical layout. Existing saves upgrade only after a complete genesis-based replay verifies their canonical history and current state. New API-created worlds and imported runs are automatically optimized. Direct library callers may choose `optimize_storage(run_id)` explicitly.

## Atomic writes and preserved history

Each accepted event and resulting changed records commit in one SQLite transaction. Events use tagged zlib blobs; their decoded canonical JSON and hashes are unchanged. `storage_records` holds individual current entities. `storage_archive` holds each person's individual memory entries and individual battle records, including active battles. A small current-state header retains scalars and other world facts. One new memory writes one archive row; moving a person never rewrites their memories or everyone else's state. Empty dictionaries, sparse slots, deletions and existing identities remain distinguishable. Current engine and profile/API representations remain complete and unchanged.

Archive separation is physical, not a new forgetting policy. Engine state still materializes the complete archive and uses the existing full-world content hash. This phase reduces database write amplification and warm deserialization but does not bound simulation RAM or eliminate the cost of full-world hashes. StateUpdate now hashes the exact prior once instead of redundantly hashing it twice; the post-state and event hash checks remain complete.

## Checkpoint integrity and recovery

Migration records a compressed checkpoint at its fully verified head. Every256 committed events a new checkpoint is recorded atomically with the event and state. Two recent checkpoints are retained; the full immutable event history remains. Each checkpoint carries run identity, version, full-world state hash, event head and a digest of the exact verified event prefix.

A cold normal load reads a consistent SQLite snapshot and validates genesis, metadata, EVERY decoded event's canonical content hash, contiguous index, event/update identities, previous-head and previous-world-hash bindings, and prefix digest. It verifies checkpoint content against its event anchor, then applies only subsequent events, validating resulting state/counters and comparing the result with current records and runs-row bindings. Any mismatch fails closed. Explicit `replay(run_id)` always rebuilds all state transitions from genesis; the replay UI keeps that audit behavior. This is not constant-time startup: event content scanning still grows with history, but applying and rehashing a growing whole world for every historical event is avoided.

A private verified-object cache returns independent copies. Raw writes through this connection, external commits and changed row bindings invalidate it. Unexpected writes never turn into trusted status-only updates.

## Operations and rollback

`tools/optimize_run_storage.py` requires paused status (or explicit isolated `--snapshot`). Run against a consistent SQLite backup first. It full-audits, atomically migrates, checkpoints, compacts the closed database with VACUUM, runs SQLite integrity_check, reopens cold, and reports unchanged version/state/head/history digest and retained population/memories. Migration itself adds no game event or simulated time. Stop the service while migrating the live DB, preserve a matching original source+database backup, install guarded source, and resume the same run through the normal API.

Version2 `runs.state_json` is a compact STORAGE HEADER, not a standalone current world snapshot. Operator tooling must use `RunStore.load_run` or the normal observer API. SQL-only size/hash/index queries remain valid. Older binaries do not understand v2 archives and must never open this save; rollback restores both the original DB and matching source, rather than swapping only code. Standard SQLite backup copies the complete database and WAL consistently. Portable export/import remain decoded and version1-compatible.

`GET /runs/{run_id}/storage` reports physical version, head/checkpoint versions, interval, compressed event payload bytes and most recent recovery counts. It does not mutate storage or advance the world.

Backups use `tools/manage_storage_backups.py`: inventory by default, verified per-file lossless archives on explicit application, with at least one recent original retained. Original removal only follows complete archive verification; unique archived history is never expired. See STORAGE_BACKUPS.md. No recurring cleanup schedule is installed.

## On-demand person history

The existing person profile now fetches50 matching events at a time through `GET /runs/{run_id}/history`, with an exclusive event-index cursor, person/owned-Pokémon/NPC references, category filter and text/display-name search. Its initial version bounds the pages, and new selections or filters discard stale request results. Older pages remain reachable through the existing Load More control; nothing is erased. A separate read-only SQLite connection scans compressed history incrementally and releases the writer lock before scanning. There is no additional huge inverted index in this phase. Sparse searches can still scan substantial history, but one profile no longer transfers and retains the entire global event log. Legacy full event export remains available.
