"""Intervention and RunMetadata: human authority records and run provenance.

Interventions are the only way a human changes a Survival run, and every one is
recorded as a canonical event. RunMetadata pins the exact code, content and
model revisions a run used, so evidence stays reproducible (PROJECT_GUIDE
sections 2 and 10).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .base import (
    CONTRACTS_VERSION,
    Contract,
    ContractError,
    as_versioned_dict,
    require_bool,
    require_id,
    require_int,
    require_list,
    require_mapping,
    require_string,
)

INTERVENTION_KINDS = frozenset(
    {
        "pause",
        "resume",
        "end_run",
        "mode_change",
        "grant_item",
        "revoke_item",
        "heal",
        "teleport",
        "stat_adjust",
        "money_adjust",
        "spawn_npc",
        "remove_npc",
        "force_event",
        "cancel_event",
        "edit_npc",
        "edit_world_fact",
        "edit_rules",
        "edit_memory",
        "edit_goal",
        "edit_relationship",
        "edit_reputation",
        "edit_faction",
        "edit_economy",
        "add_human",
        "remove_human",
        "restore_snapshot",
    }
)


@dataclass(slots=True)
class Intervention(Contract):
    run_id: str = ""
    intervention_id: str = ""
    actor: str = ""
    kind: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    expected_state_version: int = 0
    requires_reputation_cost: bool = False
    reputation_cost: int = 0
    schema_version: int = CONTRACTS_VERSION

    def validate(self) -> "Intervention":
        self.run_id = require_id(self.run_id, "intervention.run_id")
        self.intervention_id = require_id(self.intervention_id, "intervention.intervention_id")
        self.check_version()
        self.actor = require_string(self.actor, "intervention.actor", max_len=128)
        self.kind = require_string(self.kind, "intervention.kind", max_len=32)
        if self.kind not in INTERVENTION_KINDS:
            raise ContractError(f"intervention.kind {self.kind!r} is not a supported intervention")
        self.arguments = require_mapping(self.arguments, "intervention.arguments")
        self.reason = require_string(self.reason or "(no reason given)", "intervention.reason", max_len=1000)
        self.expected_state_version = require_int(
            self.expected_state_version, "intervention.expected_state_version", minimum=0, maximum=2**63 - 1
        )
        self.requires_reputation_cost = require_bool(
            self.requires_reputation_cost, "intervention.requires_reputation_cost"
        )
        self.reputation_cost = require_int(self.reputation_cost, "intervention.reputation_cost", minimum=0, maximum=1_000_000)
        if self.requires_reputation_cost and self.reputation_cost <= 0:
            raise ContractError("intervention requires a positive reputation_cost")
        return self

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Intervention":
        payload = as_versioned_dict(data, kind="intervention")
        return cls(
            run_id=str(payload.get("run_id") or ""),
            intervention_id=str(payload.get("intervention_id") or ""),
            actor=str(payload.get("actor") or ""),
            kind=str(payload.get("kind") or ""),
            arguments=require_mapping(payload.get("arguments"), "intervention.arguments"),
            reason=str(payload.get("reason") or ""),
            expected_state_version=payload.get("expected_state_version", 0),
            requires_reputation_cost=require_bool(
                payload.get("requires_reputation_cost", False), "intervention.requires_reputation_cost"
            ),
            reputation_cost=payload.get("reputation_cost", 0),
            schema_version=require_int(
                payload.get("schema_version", CONTRACTS_VERSION),
                "intervention.schema_version",
                minimum=1,
                maximum=CONTRACTS_VERSION,
            ),
        ).validate()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "intervention",
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "intervention_id": self.intervention_id,
            "actor": self.actor,
            "kind": self.kind,
            "arguments": dict(self.arguments),
            "reason": self.reason,
            "expected_state_version": self.expected_state_version,
            "requires_reputation_cost": self.requires_reputation_cost,
            "reputation_cost": self.reputation_cost,
        }


@dataclass(slots=True)
class ModelUsageRecord(Contract):
    """Evidence that a real local model made a real decision (no simulation of minds)."""

    model_id: str = ""
    model_revision: str = ""
    quantization: str = ""
    runtime: str = ""
    hardware: str = ""
    context_tokens: int = 0
    max_new_tokens: int = 0
    calls: int = 0
    failures: int = 0
    fallbacks: int = 0
    schema_version: int = CONTRACTS_VERSION

    def validate(self) -> "ModelUsageRecord":
        self.check_version()
        self.model_id = require_string(self.model_id, "model_usage.model_id", max_len=256)
        self.model_revision = require_string(self.model_revision, "model_usage.model_revision", max_len=256)
        self.quantization = require_string(self.quantization, "model_usage.quantization", max_len=128)
        self.runtime = require_string(self.runtime, "model_usage.runtime", max_len=128)
        self.hardware = require_string(self.hardware, "model_usage.hardware", max_len=128)
        self.context_tokens = require_int(self.context_tokens, "model_usage.context_tokens", minimum=0, maximum=2**31 - 1)
        self.max_new_tokens = require_int(self.max_new_tokens, "model_usage.max_new_tokens", minimum=0, maximum=2**31 - 1)
        self.calls = require_int(self.calls, "model_usage.calls", minimum=0, maximum=2**63 - 1)
        self.failures = require_int(self.failures, "model_usage.failures", minimum=0, maximum=2**63 - 1)
        self.fallbacks = require_int(self.fallbacks, "model_usage.fallbacks", minimum=0, maximum=2**63 - 1)
        if self.failures > self.calls or self.fallbacks > self.calls:
            raise ContractError("model_usage failures/fallbacks cannot exceed calls")
        return self

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ModelUsageRecord":
        payload = as_versioned_dict(data, kind="model_usage")
        return cls(
            model_id=str(payload.get("model_id") or ""),
            model_revision=str(payload.get("model_revision") or ""),
            quantization=str(payload.get("quantization") or ""),
            runtime=str(payload.get("runtime") or ""),
            hardware=str(payload.get("hardware") or ""),
            context_tokens=payload.get("context_tokens", 0),
            max_new_tokens=payload.get("max_new_tokens", 0),
            calls=payload.get("calls", 0),
            failures=payload.get("failures", 0),
            fallbacks=payload.get("fallbacks", 0),
            schema_version=require_int(
                payload.get("schema_version", CONTRACTS_VERSION),
                "model_usage.schema_version",
                minimum=1,
                maximum=CONTRACTS_VERSION,
            ),
        ).validate()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "model_usage",
            "schema_version": self.schema_version,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "quantization": self.quantization,
            "runtime": self.runtime,
            "hardware": self.hardware,
            "context_tokens": self.context_tokens,
            "max_new_tokens": self.max_new_tokens,
            "calls": self.calls,
            "failures": self.failures,
            "fallbacks": self.fallbacks,
        }


@dataclass(slots=True)
class RunMetadata(Contract):
    run_id: str = ""
    world_id: str = ""
    world_revision: str = ""
    engine_version: str = ""
    contracts_version: int = CONTRACTS_VERSION
    code_revision: str = ""
    mode: str = "survival"
    created_at: str = ""
    population_target: int = 100
    population_actual: int = 0
    data_directory: str = ""
    content_manifest_hash: str = ""
    model_usage: tuple[ModelUsageRecord, ...] = ()
    notes: str = ""
    schema_version: int = CONTRACTS_VERSION

    def validate(self) -> "RunMetadata":
        self.run_id = require_id(self.run_id, "run_metadata.run_id")
        self.world_id = require_id(self.world_id, "run_metadata.world_id")
        self.check_version()
        self.world_revision = require_string(self.world_revision, "run_metadata.world_revision", max_len=128)
        self.engine_version = require_string(self.engine_version, "run_metadata.engine_version", max_len=64)
        self.contracts_version = require_int(
            self.contracts_version, "run_metadata.contracts_version", minimum=1, maximum=CONTRACTS_VERSION
        )
        self.code_revision = require_string(self.code_revision, "run_metadata.code_revision", max_len=128)
        self.mode = require_string(self.mode, "run_metadata.mode", max_len=16)
        if self.mode not in {"observer", "survival", "creative"}:
            raise ContractError(f"run_metadata.mode {self.mode!r} is unknown")
        self.created_at = require_string(self.created_at, "run_metadata.created_at", max_len=64)
        self.population_target = require_int(self.population_target, "run_metadata.population_target", minimum=0, maximum=100)
        self.population_actual = require_int(self.population_actual, "run_metadata.population_actual", minimum=0, maximum=100)
        self.data_directory = require_string(self.data_directory, "run_metadata.data_directory", max_len=1024)
        self.content_manifest_hash = require_string(
            self.content_manifest_hash, "run_metadata.content_manifest_hash", max_len=128
        )
        self.model_usage = tuple(
            ModelUsageRecord.from_dict(m) if isinstance(m, Mapping) else m
            for m in self.model_usage
        )
        for i, record in enumerate(self.model_usage):
            if not isinstance(record, ModelUsageRecord):
                raise ContractError(f"run_metadata.model_usage[{i}] must be a ModelUsageRecord")
            record.validate()
        self.notes = require_string(self.notes or "", "run_metadata.notes", max_len=4000)
        return self

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RunMetadata":
        payload = as_versioned_dict(data, kind="run_metadata")
        return cls(
            run_id=str(payload.get("run_id") or ""),
            world_id=str(payload.get("world_id") or ""),
            world_revision=str(payload.get("world_revision") or ""),
            engine_version=str(payload.get("engine_version") or ""),
            contracts_version=payload.get("contracts_version", CONTRACTS_VERSION),
            code_revision=str(payload.get("code_revision") or ""),
            mode=str(payload.get("mode") or "survival"),
            created_at=str(payload.get("created_at") or ""),
            population_target=payload.get("population_target", 100),
            population_actual=payload.get("population_actual", 0),
            data_directory=str(payload.get("data_directory") or ""),
            content_manifest_hash=str(payload.get("content_manifest_hash") or ""),
            model_usage=tuple(
                ModelUsageRecord.from_dict(m)
                for m in require_list(payload.get("model_usage"), "run_metadata.model_usage", max_items=64)
            ),
            notes=str(payload.get("notes") or ""),
            schema_version=require_int(
                payload.get("schema_version", CONTRACTS_VERSION),
                "run_metadata.schema_version",
                minimum=1,
                maximum=CONTRACTS_VERSION,
            ),
        ).validate()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "run_metadata",
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "world_id": self.world_id,
            "world_revision": self.world_revision,
            "engine_version": self.engine_version,
            "contracts_version": self.contracts_version,
            "code_revision": self.code_revision,
            "mode": self.mode,
            "created_at": self.created_at,
            "population_target": self.population_target,
            "population_actual": self.population_actual,
            "data_directory": self.data_directory,
            "content_manifest_hash": self.content_manifest_hash,
            "model_usage": [m.to_dict() for m in self.model_usage],
            "notes": self.notes,
        }
