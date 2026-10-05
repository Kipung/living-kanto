"""CanonicalEvent: the only way anything becomes world truth.

Every committed event carries: deterministic inputs, prior state hash,
state version, event kind, affected entities, before/after deltas, and
transaction metadata (PROJECT_GUIDE section 3). Events are append-only;
replay recomputes state from genesis and must reproduce every state hash.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .base import (
    CONTRACTS_VERSION,
    Contract,
    ContractError,
    as_versioned_dict,
    content_hash,
    require_hash,
    require_id,
    require_int,
    require_list,
    require_mapping,
    require_string,
)

# Event kinds are versioned names. New kinds require a contracts_version bump
# only when they change existing semantics; additive kinds are recorded in the
# world definition's content manifest.
EVENT_KINDS = frozenset(
    {
        "run.created",
        "run.mode_changed",
        "run.paused",
        "run.resumed",
        "run.ended",
        "time.advanced",
        "human.created",
        "human.moved",
        "human.field_move",
        "activity.batch_started",
        "human.entered_map",
        "human.used_exit",
        "human.talked",
        "human.inspected",
        "human.used_item",
        "human.healed",
        "human.traded",
        "human.shopped",
        "human.stored",
        "human.goal_set",
        "human.goal_abandoned",
        "human.memory_written",
        "human.relationship_changed",
        "human.reputation_changed",
        "human.party_changed",
        "human.inventory_changed",
        "human.money_changed",
        "human.badge_awarded",
        "human.caught_pokemon",
        "human.fainted",
        "human.box_changed",
        "battle.started",
        "battle.turn",
        "battle.action",
        "battle.switch",
        "battle.item_used",
        "battle.attempted_catch",
        "battle.caught",
        "battle.fled",
        "battle.fainted",
        "battle.ended",
        "battle.rewards",
        "encounter.triggered",
        "npc.state_changed",
        "world.weather_changed",
        "world.time_of_day_changed",
        "world.public_event",
        "intervention.applied",
        "state.repaired",
        "population.changed",
        "league.result",
    }
)

MAX_DELTA_BYTES = 262_144


@dataclass(slots=True)
class CanonicalEvent(Contract):
    run_id: str = ""
    event_id: str = ""
    event_index: int = 0
    state_version: int = 0
    previous_head: str = ""
    event_kind: str = ""
    tick: int = 0
    simulated_time: int = 0
    real_wall_time: str = ""
    causation: dict[str, Any] = field(default_factory=dict)
    affected: tuple[dict[str, Any], ...] = ()
    before: dict[str, Any] = field(default_factory=dict)
    after: dict[str, Any] = field(default_factory=dict)
    deterministic_inputs: dict[str, Any] = field(default_factory=dict)
    transaction: dict[str, Any] = field(default_factory=dict)
    visibility: dict[str, Any] = field(default_factory=dict)
    schema_version: int = CONTRACTS_VERSION

    def validate(self) -> "CanonicalEvent":
        self.run_id = require_id(self.run_id, "canonical_event.run_id")
        self.event_id = require_id(self.event_id, "canonical_event.event_id")
        self.check_version()
        self.event_index = require_int(self.event_index, "canonical_event.event_index", minimum=0, maximum=2**63 - 1)
        self.state_version = require_int(self.state_version, "canonical_event.state_version", minimum=0, maximum=2**63 - 1)
        self.previous_head = require_hash(self.previous_head, "canonical_event.previous_head")
        self.event_kind = require_string(self.event_kind, "canonical_event.event_kind", max_len=64)
        if self.event_kind not in EVENT_KINDS:
            raise ContractError(
                f"canonical_event.event_kind {self.event_kind!r} is not a versioned event kind"
            )
        self.tick = require_int(self.tick, "canonical_event.tick", minimum=0, maximum=2**63 - 1)
        self.simulated_time = require_int(self.simulated_time, "canonical_event.simulated_time", minimum=0, maximum=2**63 - 1)
        self.real_wall_time = require_string(self.real_wall_time, "canonical_event.real_wall_time", max_len=64)
        self.causation = require_mapping(self.causation, "canonical_event.causation")
        self.before = require_mapping(self.before, "canonical_event.before")
        self.after = require_mapping(self.after, "canonical_event.after")
        self.deterministic_inputs = require_mapping(
            self.deterministic_inputs, "canonical_event.deterministic_inputs"
        )
        self.transaction = require_mapping(self.transaction, "canonical_event.transaction")
        self.visibility = require_mapping(self.visibility, "canonical_event.visibility")
        self.affected = tuple(
            require_mapping(a, "canonical_event.affected[]")
            for a in require_list(self.affected, "canonical_event.affected", max_items=4096)
        )
        return self

    def check_size(self) -> None:
        """Reject oversized deltas; large content belongs in content-addressed storage."""
        from .base import canonical_json

        payload_bytes = len(canonical_json({"before": self.before, "after": self.after}).encode("utf-8"))
        if payload_bytes > MAX_DELTA_BYTES:
            raise ContractError(
                f"canonical_event delta is {payload_bytes} bytes; limit {MAX_DELTA_BYTES} "
                "— store large content in content-addressed storage and reference its hash"
            )

    @property
    def event_hash(self) -> str:
        return content_hash(self.to_dict())

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CanonicalEvent":
        payload = as_versioned_dict(data, kind="canonical_event")
        return cls(
            run_id=str(payload.get("run_id") or ""),
            event_id=str(payload.get("event_id") or ""),
            event_index=payload.get("event_index", 0),
            state_version=payload.get("state_version", 0),
            previous_head=str(payload.get("previous_head") or ""),
            event_kind=str(payload.get("event_kind") or ""),
            tick=payload.get("tick", 0),
            simulated_time=payload.get("simulated_time", 0),
            real_wall_time=str(payload.get("real_wall_time") or ""),
            causation=require_mapping(payload.get("causation"), "canonical_event.causation"),
            affected=tuple(
                require_mapping(a, "canonical_event.affected[]")
                for a in require_list(payload.get("affected"), "canonical_event.affected", max_items=4096)
            ),
            before=require_mapping(payload.get("before"), "canonical_event.before"),
            after=require_mapping(payload.get("after"), "canonical_event.after"),
            deterministic_inputs=require_mapping(
                payload.get("deterministic_inputs"), "canonical_event.deterministic_inputs"
            ),
            transaction=require_mapping(payload.get("transaction"), "canonical_event.transaction"),
            visibility=require_mapping(payload.get("visibility"), "canonical_event.visibility"),
            schema_version=require_int(
                payload.get("schema_version", CONTRACTS_VERSION),
                "canonical_event.schema_version",
                minimum=1,
                maximum=CONTRACTS_VERSION,
            ),
        ).validate()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "canonical_event",
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "event_id": self.event_id,
            "event_index": self.event_index,
            "state_version": self.state_version,
            "previous_head": self.previous_head,
            "event_kind": self.event_kind,
            "tick": self.tick,
            "simulated_time": self.simulated_time,
            "real_wall_time": self.real_wall_time,
            "causation": dict(self.causation),
            "affected": [dict(a) for a in self.affected],
            "before": dict(self.before),
            "after": dict(self.after),
            "deterministic_inputs": dict(self.deterministic_inputs),
            "transaction": dict(self.transaction),
            "visibility": dict(self.visibility),
        }
