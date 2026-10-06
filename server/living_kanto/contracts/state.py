"""WorldState / StateUpdate: canonical snapshot plus the delta that produced it.

State is versioned and hashable. A StateUpdate is the unit the engine applies
inside one transaction: it names the event that caused it, the prior hash and
version, and the changed entity slices.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .base import (
    CONTRACTS_VERSION,
    Contract,
    ContractError,
    as_plain_dict,
    as_versioned_dict,
    content_hash,
    require_exact_int,
    require_hash,
    require_id,
    require_int,
    require_list,
    require_mapping,
    require_string,
)

RUN_MODES = frozenset({"observer", "survival", "creative"})
RUN_PHASES = frozenset({"created", "running", "paused", "ended"})


@dataclass(slots=True)
class WorldState(Contract):
    """Canonical world snapshot at one state version.

    Time semantics (binding for engine, store, UI, and benchmarks):
    - ``tick`` and ``simulated_time`` are BOTH integer elapsed simulated
      seconds, bootstrapped equal. ``advance_clock`` increments BOTH by the
      given seconds. They advance only with explicit ``advance_clock``
      changes: an event with zero simulated time may still increment
      ``state_version`` without advancing time, and wall-clock downtime
      never advances either counter.
    - ``clock`` is descriptive display metadata (day cycle, label, etc.).
      When ``clock['seconds']`` is used it is set to the resulting elapsed
      simulated seconds by ``advance_clock``; it is advisory and nothing may
      use it as a substitute for ``tick``/``simulated_time``.
    """

    run_id: str = ""
    state_version: int = 0
    state_hash: str = ""
    tick: int = 0
    simulated_time: int = 0
    mode: str = "survival"
    phase: str = "created"
    clock: dict[str, Any] = field(default_factory=dict)
    humans: dict[str, dict[str, Any]] = field(default_factory=dict)
    pokemon: dict[str, dict[str, Any]] = field(default_factory=dict)
    npcs: dict[str, dict[str, Any]] = field(default_factory=dict)
    maps: dict[str, dict[str, Any]] = field(default_factory=dict)
    items: dict[str, dict[str, Any]] = field(default_factory=dict)
    economies: dict[str, dict[str, Any]] = field(default_factory=dict)
    factions: dict[str, dict[str, Any]] = field(default_factory=dict)
    public_events: tuple[dict[str, Any], ...] = ()
    world_facts: dict[str, Any] = field(default_factory=dict)
    schema_version: int = CONTRACTS_VERSION

    def validate(self) -> "WorldState":
        self.run_id = require_id(self.run_id, "world_state.run_id")
        self.check_version()
        self.state_version = require_int(self.state_version, "world_state.state_version", minimum=0, maximum=2**63 - 1)
        self.tick = require_int(self.tick, "world_state.tick", minimum=0, maximum=2**63 - 1)
        self.simulated_time = require_int(self.simulated_time, "world_state.simulated_time", minimum=0, maximum=2**63 - 1)
        self.mode = require_string(self.mode, "world_state.mode", max_len=16)
        if self.mode not in RUN_MODES:
            raise ContractError(f"world_state.mode {self.mode!r} is unknown")
        self.phase = require_string(self.phase, "world_state.phase", max_len=16)
        if self.phase not in RUN_PHASES:
            raise ContractError(f"world_state.phase {self.phase!r} is unknown")
        self.clock = require_mapping(self.clock, "world_state.clock")
        self.world_facts = require_mapping(self.world_facts, "world_state.world_facts")
        for name in ("humans", "pokemon", "npcs", "maps", "items", "economies", "factions"):
            value = require_mapping(getattr(self, name), f"world_state.{name}")
            for key, entity in value.items():
                require_id(key, f"world_state.{name} key")
                require_mapping(entity, f"world_state.{name}[{key}]")
        self.public_events = tuple(
            require_mapping(e, "world_state.public_events[]")
            for e in require_list(self.public_events, "world_state.public_events", max_items=100_000)
        )
        return self

    def compute_state_hash(self) -> str:
        """Hash excludes the stored state_hash field so it can be filled in."""
        payload = self.to_dict()
        payload.pop("state_hash", None)
        return content_hash(payload)

    def verify(self) -> "WorldState":
        """Verify the stored hash, tolerating an empty (legacy) one.

        A non-empty stored hash must recompute from canonical content; an
        empty one is tolerated by validation but cannot be trusted as a
        prior-state binding - callers must recompute it explicitly.
        """
        self.validate()
        if self.state_hash and self.state_hash != self.compute_state_hash():
            raise ContractError(
                f"world_state.state_hash mismatch at version {self.state_version}: "
                "stored hash does not recompute from canonical content"
            )
        return self

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WorldState":
        payload = as_versioned_dict(data, kind="world_state")
        return cls(
            run_id=str(payload.get("run_id") or ""),
            state_version=payload.get("state_version", 0),
            state_hash=str(payload.get("state_hash") or ""),
            tick=payload.get("tick", 0),
            simulated_time=payload.get("simulated_time", 0),
            mode=str(payload.get("mode") or "survival"),
            phase=str(payload.get("phase") or "created"),
            clock=require_mapping(payload.get("clock"), "world_state.clock"),
            humans={
                str(k): require_mapping(v, f"world_state.humans[{k}]")
                for k, v in require_mapping(payload.get("humans"), "world_state.humans").items()
            },
            pokemon={
                str(k): require_mapping(v, f"world_state.pokemon[{k}]")
                for k, v in require_mapping(payload.get("pokemon"), "world_state.pokemon").items()
            },
            npcs={
                str(k): require_mapping(v, f"world_state.npcs[{k}]")
                for k, v in require_mapping(payload.get("npcs"), "world_state.npcs").items()
            },
            maps={
                str(k): require_mapping(v, f"world_state.maps[{k}]")
                for k, v in require_mapping(payload.get("maps"), "world_state.maps").items()
            },
            items={
                str(k): require_mapping(v, f"world_state.items[{k}]")
                for k, v in require_mapping(payload.get("items"), "world_state.items").items()
            },
            economies={
                str(k): require_mapping(v, f"world_state.economies[{k}]")
                for k, v in require_mapping(payload.get("economies"), "world_state.economies").items()
            },
            factions={
                str(k): require_mapping(v, f"world_state.factions[{k}]")
                for k, v in require_mapping(payload.get("factions"), "world_state.factions").items()
            },
            public_events=tuple(
                require_mapping(e, "world_state.public_events[]")
                for e in require_list(payload.get("public_events"), "world_state.public_events", max_items=100_000)
            ),
            world_facts=require_mapping(payload.get("world_facts"), "world_state.world_facts"),
            schema_version=require_int(
                payload.get("schema_version", CONTRACTS_VERSION),
                "world_state.schema_version",
                minimum=1,
                maximum=CONTRACTS_VERSION,
            ),
        ).validate()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "world_state",
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "state_version": self.state_version,
            "state_hash": self.state_hash,
            "tick": self.tick,
            "simulated_time": self.simulated_time,
            "mode": self.mode,
            "phase": self.phase,
            "clock": dict(self.clock),
            "humans": {k: dict(v) for k, v in self.humans.items()},
            "pokemon": {k: dict(v) for k, v in self.pokemon.items()},
            "npcs": {k: dict(v) for k, v in self.npcs.items()},
            "maps": {k: dict(v) for k, v in self.maps.items()},
            "items": {k: dict(v) for k, v in self.items.items()},
            "economies": {k: dict(v) for k, v in self.economies.items()},
            "factions": {k: dict(v) for k, v in self.factions.items()},
            "public_events": [dict(e) for e in self.public_events],
            "world_facts": dict(self.world_facts),
        }

    def apply_changes(self, changes: Iterable[Mapping[str, Any]]) -> "WorldState":
        """Apply StateUpdate deltas to a copy and return the resulting state.

        Entity keys are dotted paths into the entity dict, e.g.
        'humans.h_001.position.x'. Entity keys: humans, pokemon, npcs, maps,
        items, economies, factions. Collection keys: public_events (append,
        max 1000), world_facts (set, 2-part paths). 'advance_clock' adds
        integer seconds to BOTH authoritative counters 'tick' and
        'simulated_time', and sets 'clock.seconds' to the resulting elapsed
        seconds only when that key already exists ('clock' is descriptive
        display metadata; see the class docstring). Zero-time changes are
        allowed and never advance time. Overwriting a non-dict intermediate
        path component with a dict is rejected. state_version and state_hash
        are preserved from the source; the caller advances the version and
        recomputes the hash via compute_state_hash(). The source state is
        never mutated: the work is done on a deep copy, so a failure partway
        through leaves the source (and its stored hash) untouched.
        """
        candidate = as_plain_dict(self)
        candidate["state_hash"] = self.state_hash
        candidate["state_version"] = self.state_version
        for change in changes:
            op = str(change.get("op") or "")
            if op == "set":
                path = str(change.get("path") or "")
                parts = path.split(".")
                if len(parts) < 2 or parts[0] not in {
                    "humans", "pokemon", "npcs", "maps", "items",
                    "economies", "factions", "world_facts",
                }:
                    raise ContractError(f"world_state.apply_changes: unsupported path {path!r}")
                if parts[0] != "world_facts" and len(parts) < 3:
                    raise ContractError(f"world_state.apply_changes: leaf path required for {path!r}")
                domain, key = parts[0], parts[1]
                if domain == "world_facts":
                    _set_nested(candidate["world_facts"], parts[1:], change.get("value"))
                    continue
                entity = candidate[domain].setdefault(key, {})
                target = entity
                for part in parts[2:-1]:
                    if part not in target:
                        target[part] = {}
                    elif not isinstance(target[part], dict):
                        raise ContractError(
                            f"world_state.apply_changes: cannot traverse non-dict at {part!r} in {path!r}"
                        )
                    target = target[part]
                target[parts[-1]] = change.get("value")
            elif op == "remove":
                path = str(change.get("path") or "")
                parts = path.split(".")
                if len(parts) < 2 or parts[0] not in {
                    "humans", "pokemon", "npcs", "maps", "items",
                    "economies", "factions", "world_facts",
                }:
                    raise ContractError(f"world_state.apply_changes: unsupported path {path!r}")
                domain, key = parts[0], parts[1]
                if domain == "world_facts":
                    if len(parts) == 2:
                        if key not in candidate["world_facts"]:
                            raise ContractError(
                                f"world_state.apply_changes: remove path {path!r} does not exist"
                            )
                        candidate["world_facts"].pop(key, None)
                    elif not _remove_nested(candidate["world_facts"], parts[1:]):
                        raise ContractError(
                            f"world_state.apply_changes: remove path {path!r} does not exist"
                        )
                    continue
                if len(parts) == 2:
                    if key not in candidate[domain]:
                        raise ContractError(
                            f"world_state.apply_changes: remove path {path!r} does not exist"
                        )
                    candidate[domain].pop(key, None)
                    continue
                entity = candidate[domain].get(key)
                if not isinstance(entity, dict) or not _remove_nested(entity, parts[2:]):
                    raise ContractError(
                        f"world_state.apply_changes: remove path {path!r} does not exist"
                    )
            elif op == "append_public_event":
                event = require_mapping(change.get("event"), "state_update.event")
                events = list(candidate["public_events"])
                events.append(dict(event))
                if len(events) > 1000:
                    raise ContractError("world_state.apply_changes: public_events exceeds 1000")
                candidate["public_events"] = events
            elif op == "advance_clock":
                seconds = require_exact_int(
                    change.get("seconds"), "state_update.seconds", minimum=0, maximum=2**63 - 1
                )
                candidate["tick"] = int(candidate["tick"]) + seconds
                candidate["simulated_time"] = int(candidate["simulated_time"]) + seconds
                clock = dict(candidate["clock"])
                if "seconds" in clock:
                    clock["seconds"] = int(clock["seconds"]) + seconds
                candidate["clock"] = clock
            else:
                raise ContractError(f"world_state.apply_changes: unsupported op {op!r}")
        return WorldState.from_dict(candidate)

    def with_advanced_version(self, changes: Iterable[Mapping[str, Any]]) -> "WorldState":
        """Apply changes, advance state_version by exactly 1, recompute state_hash.

        The source state is not modified even if the changes fail midway.
        The source must verify(): its stored state_hash must recompute from
        its canonical content, so a stale or tampered snapshot can never be
        the base of an advance (the F1 half of the stale-action gate).
        """
        self.verify()
        candidate = self.apply_changes(changes)
        # apply_changes already returns an independent validated world. Advance
        # that copy directly instead of encoding/decoding the full world again.
        candidate.state_hash = ""
        candidate.state_version = self.state_version + 1
        candidate.validate()
        candidate.state_hash = candidate.compute_state_hash()
        return candidate


def _deep(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _deep(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_deep(v) for v in value]
    return value


def _set_nested(target: dict, parts: list[str], value: Any) -> None:
    # Missing intermediates may be created as new dict branches; a *present*
    # non-dict (including a present null) is an existing value and is never
    # silently converted or overwritten.
    for part in parts[:-1]:
        if part not in target:
            target[part] = {}
        elif not isinstance(target[part], dict):
            raise ContractError(
                f"world_state.apply_changes: cannot traverse non-dict at {part!r} in {'.'.join(parts)!r}"
            )
        target = target[part]
    target[parts[-1]] = value


def _remove_nested(target: dict, parts: list[str]) -> bool:
    """Remove parts[-1] if the full path exists; return whether it did."""
    for part in parts[:-1]:
        nxt = target.get(part)
        if not isinstance(nxt, dict):
            return False
        target = nxt
    if parts[-1] not in target:
        return False
    target.pop(parts[-1])
    return True


@dataclass(slots=True)
class StateUpdate(Contract):
    """The transactional delta one event produces, with its hash chains.

    Two chains are bound here and they are distinct:
    - previous_head links the event log (the event_hash of the preceding
      event): an ordering/integrity chain.
    - prior_state_hash is the WORLD content hash (WorldState.state_hash) of
      the snapshot this update was computed against. Together with
      prior_state_version it lets a receiver reject a stale or forked engine
      action that names the right version number but was derived from
      different world content.
    """

    run_id: str = ""
    event_id: str = ""
    event_index: int = 0
    prior_state_version: int = 0
    prior_state_hash: str = ""
    previous_head: str = ""
    state_version: int = 0
    state_hash: str = ""
    changes: tuple[dict[str, Any], ...] = ()
    schema_version: int = CONTRACTS_VERSION

    def validate(self) -> "StateUpdate":
        self.run_id = require_id(self.run_id, "state_update.run_id")
        self.event_id = require_id(self.event_id, "state_update.event_id")
        self.check_version()
        self.event_index = require_int(self.event_index, "state_update.event_index", minimum=0, maximum=2**63 - 1)
        self.prior_state_version = require_int(
            self.prior_state_version, "state_update.prior_state_version", minimum=0, maximum=2**63 - 1
        )
        self.prior_state_hash = require_hash(self.prior_state_hash, "state_update.prior_state_hash")
        self.previous_head = require_hash(self.previous_head, "state_update.previous_head")
        self.state_version = require_int(self.state_version, "state_update.state_version", minimum=1, maximum=2**63 - 1)
        self.state_hash = require_hash(self.state_hash, "state_update.state_hash")
        if self.state_version != self.prior_state_version + 1:
            raise ContractError(
                f"state_update skips versions: {self.prior_state_version} -> {self.state_version}"
            )
        self.changes = tuple(
            require_mapping(c, "state_update.changes[]")
            for c in require_list(self.changes, "state_update.changes", max_items=100_000)
        )
        return self

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StateUpdate":
        payload = as_versioned_dict(data, kind="state_update")
        return cls(
            run_id=str(payload.get("run_id") or ""),
            event_id=str(payload.get("event_id") or ""),
            event_index=payload.get("event_index", 0),
            prior_state_version=payload.get("prior_state_version", 0),
            prior_state_hash=str(payload.get("prior_state_hash") or ""),
            previous_head=str(payload.get("previous_head") or ""),
            state_version=payload.get("state_version", 0),
            state_hash=str(payload.get("state_hash") or ""),
            changes=tuple(
                require_mapping(c, "state_update.changes[]")
                for c in require_list(payload.get("changes"), "state_update.changes", max_items=100_000)
            ),
            schema_version=require_int(
                payload.get("schema_version", CONTRACTS_VERSION),
                "state_update.schema_version",
                minimum=1,
                maximum=CONTRACTS_VERSION,
            ),
        ).validate()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "state_update",
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "event_id": self.event_id,
            "event_index": self.event_index,
            "prior_state_version": self.prior_state_version,
            "prior_state_hash": self.prior_state_hash,
            "previous_head": self.previous_head,
            "state_version": self.state_version,
            "state_hash": self.state_hash,
            "changes": [dict(c) for c in self.changes],
        }

    def apply_to(self, state: WorldState) -> WorldState:
        """Apply this update to a world state, enforcing the prior binding.

        Rejects (a) a state whose stored hash does not recompute, (b) a state
        at the wrong version, and (c) a state whose content hash differs from
        prior_state_hash — the stale/forked engine-action gate. Returns the
        advanced state and verifies its own declared state_version/state_hash
        match the applied result.
        """
        state.verify()
        if state.state_version != self.prior_state_version:
            raise ContractError(
                f"state_update {self.event_id}: expects prior version "
                f"{self.prior_state_version}, got {state.state_version}"
            )
        if state.state_hash != self.prior_state_hash:
            raise ContractError(
                f"state_update {self.event_id}: expects prior state hash "
                f"{self.prior_state_hash}, got {state.state_hash} — stale or forked action"
            )
        # The exact prior was verified above. with_advanced_version would hash
        # that same unchanged prior a second time. Build the independent result
        # directly, retaining the complete prior and post content-hash checks.
        advanced = state.apply_changes(self.changes)
        advanced.state_hash = ""
        advanced.state_version = state.state_version + 1
        advanced.validate()
        advanced.state_hash = advanced.compute_state_hash()
        if advanced.state_hash != self.state_hash or advanced.state_version != self.state_version:
            raise ContractError(
                f"state_update {self.event_id}: resulting state does not match "
                "declared state_version/state_hash"
            )
        return advanced
