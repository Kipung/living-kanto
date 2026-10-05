"""Shared test helpers for constructing valid contract objects.

All hashes are computed from actual content:
- world state hash = WorldState.compute_state_hash() over the full snapshot
- event chain head = CanonicalEvent.event_hash (SHA-256 of canonical event dict)
- event chain seed = 64 zeros for the first event, distinct from the genesis
  world content hash which is stored separately in the runs row
"""

from __future__ import annotations

from living_kanto.contracts import (
    CanonicalEvent,
    RunMetadata,
    StateUpdate,
    WorldState,
)

RUN_ID = "test-run-001"
WORLD_ID = "kanto"
WORLD_REVISION = "037335f4c725d7c9aecdac87066f2002b4bd7e14"
ENGINE_VERSION = "0.1.0"
CONTRACTS_VERSION = "1"
CODE_REVISION = "037335f4c725d7c9aecdac87066f2002b4bd7e14"
MODE = "observer"
POPULATION_TARGET = 100
POPULATION_ACTUAL = 0
DATA_DIR = "/tmp/living-kanto-test"
CONTENT_MANIFEST_HASH = "a" * 64
MODEL_USAGE = ()  # empty tuple: no model usage records for M0
NOTES = "test run"


def make_run_metadata(
    run_id: str = RUN_ID,
    initial_state: "WorldState | None" = None,
) -> RunMetadata:
    """Build valid RunMetadata.

    RunMetadata (shared contract) carries no initial_state field; the genesis
    state is handed to RunStore.create_run separately. When callers pass
    initial_state we bind content_manifest_hash to that state's real hash so
    the metadata is tied to the actual genesis snapshot.
    """
    manifest_hash = initial_state.state_hash if initial_state is not None else CONTENT_MANIFEST_HASH
    return RunMetadata(
        schema_version=1,
        run_id=run_id,
        world_id=WORLD_ID,
        world_revision=WORLD_REVISION,
        engine_version=ENGINE_VERSION,
        contracts_version=CONTRACTS_VERSION,
        code_revision=CODE_REVISION,
        mode=MODE,
        created_at="2026-10-04T00:00:00Z",
        population_target=POPULATION_TARGET,
        population_actual=POPULATION_ACTUAL,
        data_directory=DATA_DIR,
        content_manifest_hash=manifest_hash,
        model_usage=MODEL_USAGE,
        notes=NOTES,
    )


def make_world_state(
    run_id: str = RUN_ID,
    state_version: int = 0,
    tick: int = 0,
    simulated_time: int = 0,
) -> WorldState:
    """Build a WorldState whose state_hash is the real content hash."""
    state = WorldState(
        schema_version=1,
        run_id=run_id,
        state_version=state_version,
        state_hash="",
        tick=tick,
        simulated_time=simulated_time,
        mode=MODE,
        phase="created",
        clock={},
        humans={},
        pokemon={},
        npcs={},
        maps={},
        items={},
        economies={},
        factions={},
        public_events=[],
        world_facts={},
    )
    state.state_hash = state.compute_state_hash()
    return state


def make_event(
    run_id: str = RUN_ID,
    event_index: int = 0,
    previous_head: str | None = None,
    tick: int = 0,
    simulated_time: int | None = None,
    event_kind: str = "time.advanced",
    changes: list[dict] | None = None,
    prior_state: WorldState | None = None,
    event_id: str | None = None,
    default_change: bool = True,
) -> CanonicalEvent:
    """Build a CanonicalEvent whose transaction is a real StateUpdate.

    Semantics (documented per operator directive):
    - event.previous_head: the event chain head before this event. For index 0
      this is the 64-zero seed; otherwise the prior event's event_hash. This
      chains events, independent of world content hashes.
    - transaction.prior_state_hash: the world content hash of the snapshot the
      update was computed against (stale/forked-action gate).
    - transaction.prior_state_version: world state version BEFORE this event.
    - transaction.state_version: world state version AFTER this event
      (must equal prior + 1).
    - transaction.state_hash: the REAL WorldState.compute_state_hash() of the
      post-event snapshot, computed here by applying `changes` to `prior_state`
      via the canonical applier. Never arbitrary caller text.
    """
    if prior_state is None:
        prior_state = make_world_state(run_id)
    # tick and simulated_time are BOTH elapsed simulated seconds and advance
    # together, so the default mirrors tick. Callers may still pass an explicit
    # simulated_time to exercise the store's counter-mismatch rejection.
    if simulated_time is None:
        simulated_time = tick
    if event_id is None:
        event_id = f"evt-{run_id}-{event_index:06d}"
    # real_wall_time is part of the hashed event payload; keep it deterministic
    # so tests are reproducible. Distinct events vary by index/event_id anyway.
    real_wall_time = f"2026-10-04T00:00:{event_index % 60:02d}Z"
    if changes is None and default_change:
        # A real, content-changing update (op/path/value) so the recomputed
        # hash differs from the prior state's hash (empty changes = no-op).
        # Entity keys must be NEW: the canonical applier refuses to create an
        # existing entity via set, and the store re-verifies by replaying from
        # genesis, so keys must not collide across events.
        # advance_clock carries the elapsed time: the contract applies it to
        # BOTH authoritative counters, so the event's tick/simulated_time
        # equal the resulting state counters (deltas, not absolute mutation).
        elapsed = tick - prior_state.tick
        changes = [
            {"op": "set", "path": f"pokemon.p{tick}_{event_index + 1}.species", "value": "pikachu"},
            {"op": "set", "path": f"pokemon.p{tick}_{event_index + 1}.location", "value": "viridian_forest"},
            {"op": "set", "path": f"world_facts.tick_{tick}", "value": tick},
            {"op": "advance_clock", "seconds": elapsed},
        ]

    # The event chains from the stored head. For event_index 0, the chain
    # head is the 64-zero seed; the store keeps runs.head_hash on the event
    # chain, never on a world hash. For later events, the caller must pass
    # previous_head = prior event's event_hash.
    if previous_head is None:
        # Event chain seed: 64 zeros for the first event. This is distinct
        # from the world content hash (see genesis_head docstring).
        previous_head = genesis_head()

    # Apply changes to the EXACT prior state via the canonical applier to get
    # the post-event world state (version + 1, real content hash). Elapsed
    # time is carried by the advance_clock delta above, so post counters equal
    # the event's tick/simulated_time without any post-hoc hash rewriting.
    post = prior_state.with_advanced_version(changes or [])
    state_after_hash = post.state_hash

    transaction = StateUpdate(
        schema_version=1,
        run_id=run_id,
        event_id=event_id,
        event_index=event_index,
        prior_state_version=prior_state.state_version,
        prior_state_hash=prior_state.state_hash,
        state_version=post.state_version,
        previous_head=previous_head,
        state_hash=state_after_hash,
        changes=tuple(changes or []),
    )

    return CanonicalEvent(
        schema_version=1,
        run_id=run_id,
        event_id=event_id,
        event_index=event_index,
        state_version=post.state_version,  # post-event world state version
        previous_head=previous_head,
        event_kind=event_kind,
        tick=tick,
        simulated_time=simulated_time,
        real_wall_time=real_wall_time,
        causation={"kind": "system", "actor_id": "engine", "action_id": f"evt-{run_id}-{event_index}"},
        affected=[],
        before={},
        after={},
        deterministic_inputs={},
        transaction=transaction.to_dict(),
        visibility={"public": True, "private": {}},
    )


def genesis_head() -> str:
    """Event chain seed: 64 zeros (selected consistent convention).

    Distinct from the genesis WORLD state hash, which is real content.
    """
    return "0" * 64


def append_chain_event(
    store,
    run_id: str,
    *,
    tick: int,
    prior_state: WorldState,
    event_id: str | None = None,
    previous_head: str | None = None,
) -> CanonicalEvent:
    """Append one event through the store and return it.

    Derives the event's previous_head from the store's ACTUAL event-chain head
    (load_head), not the world content hash. The store's append_event returns
    the new world state hash, so callers that chain several events must read
    the chain head back from the store rather than feeding the returned state
    hash forward as a chain link.

    Usage in tests:
        e1 = append_chain_event(store, run_id, tick=1, prior_state=state)
        _, state, _ = store.load_run(run_id)
        e2 = append_chain_event(store, run_id, tick=2, prior_state=state)
    """
    if previous_head is None:
        previous_head = store.load_head(run_id)
    # Derive the logical position from the store so chained events get the
    # correct event_index (and a unique derived event_id) instead of all
    # colliding at index 0.
    event = make_event(
        run_id,
        tick=tick,
        prior_state=prior_state,
        event_id=event_id,
        previous_head=previous_head,
        event_index=store.event_count(run_id),
    )
    store.append_event(event, event.transaction["state_hash"])
    return event
