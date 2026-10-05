"""BattleObservation / BattleAction: revealed information and legal battle choices.

A battle is a state machine with a turn queue, switches, escape, items,
fainting, capture, and rewards. The observation only carries information the
participant could legitimately see at that point (PROJECT_GUIDE section 5).
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
    require_bool,
    require_id,
    require_int,
    require_list,
    require_mapping,
    require_number,
    require_string,
)

LEGAL_BATTLE_ACTIONS = frozenset(
    {"use_move", "use_item", "switch", "run", "catch", "send_first", "pass_turn"}
)

BATTLE_PHASES = frozenset(
    {
        "intro",
        "await_action",
        "resolve_turn",
        "forced_switch",
        "over",
    }
)

BATTLE_KINDS = frozenset({"wild", "trainer", "gym", "league"})


@dataclass(slots=True)
class LegalBattleAction:
    action: str
    arguments: dict[str, Any] = field(default_factory=dict)
    known_consequences: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalBattleAction":
        payload = as_versioned_dict(data, kind="legal_battle_action")
        action = require_string(payload.get("action"), "legal_battle_action.action", max_len=32)
        if action not in LEGAL_BATTLE_ACTIONS:
            raise ContractError(f"legal_battle_action.action {action!r} is not legal in battle")
        return cls(
            action=action,
            arguments=require_mapping(payload.get("arguments"), "legal_battle_action.arguments"),
            known_consequences=require_mapping(
                payload.get("known_consequences"), "legal_battle_action.known_consequences"
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "legal_battle_action",
            "action": self.action,
            "arguments": dict(self.arguments),
            "known_consequences": dict(self.known_consequences),
        }


@dataclass(slots=True)
class BattleObservation(Contract):
    """What one participant can see right now in one battle."""

    run_id: str = ""
    battle_id: str = ""
    human_id: str = ""
    state_version: int = 0
    observation_version: int = 0
    turn: int = 0
    phase: str = "await_action"
    battle_kind: str = "wild"
    side: str = "player"
    own_active: dict[str, Any] = field(default_factory=dict)
    own_party: tuple[dict[str, Any], ...] = ()
    opponent_active: dict[str, Any] = field(default_factory=dict)
    opponent_visible_info: dict[str, Any] = field(default_factory=dict)
    field_effects: tuple[dict[str, Any], ...] = ()
    message_log: tuple[str, ...] = ()
    legal_actions: tuple[LegalBattleAction, ...] = ()
    capture_opportunity: dict[str, Any] | None = None
    schema_version: int = CONTRACTS_VERSION

    def validate(self) -> "BattleObservation":
        self.run_id = require_id(self.run_id, "battle_observation.run_id")
        self.battle_id = require_id(self.battle_id, "battle_observation.battle_id")
        self.human_id = require_id(self.human_id, "battle_observation.human_id")
        self.check_version()
        self.state_version = require_int(self.state_version, "battle_observation.state_version", minimum=0, maximum=2**63 - 1)
        self.observation_version = require_int(
            self.observation_version, "battle_observation.observation_version", minimum=0, maximum=2**63 - 1
        )
        self.turn = require_int(self.turn, "battle_observation.turn", minimum=0, maximum=100_000)
        self.phase = require_string(self.phase, "battle_observation.phase", max_len=32)
        if self.phase not in BATTLE_PHASES:
            raise ContractError(f"battle_observation.phase {self.phase!r} is unknown")
        self.battle_kind = require_string(self.battle_kind, "battle_observation.battle_kind", max_len=16)
        if self.battle_kind not in BATTLE_KINDS:
            raise ContractError(f"battle_observation.battle_kind {self.battle_kind!r} is unknown")
        self.side = require_string(self.side, "battle_observation.side", max_len=16)
        self.own_active = require_mapping(self.own_active, "battle_observation.own_active")
        self.opponent_active = require_mapping(self.opponent_active, "battle_observation.opponent_active")
        self.opponent_visible_info = require_mapping(
            self.opponent_visible_info, "battle_observation.opponent_visible_info"
        )
        if len(self.own_party) > 6:
            raise ContractError("battle_observation.own_party may not exceed 6 members")
        self._assert_no_hidden_leaks()
        return self

    def observation_hash(self) -> str:
        return content_hash(self.to_dict())

    def _assert_no_hidden_leaks(self) -> None:
        """Opponent hidden moves/stats and RNG must never be in an observation."""
        banned = {
            "hidden_move",
            "hidden_moves",
            "opponent_move_choice",
            "enemy_hidden_move",
            "iv",
            "ivs",
            "ev",
            "evs",
            "hidden_stat",
            "rng",
            "random_seed",
            "seed",
            "next_turn_result",
            "catch_forecast",
        }

        def walk(node: Any, path: str) -> None:
            if isinstance(node, Mapping):
                for key, value in node.items():
                    if str(key).lower() in banned:
                        raise ContractError(
                            f"battle_observation.{path} contains forbidden hidden key {key!r}"
                        )
                    walk(value, f"{path}.{key}")
            elif isinstance(node, (list, tuple)):
                for index, value in enumerate(node):
                    walk(value, f"{path}[{index}]")

        for field_name in ("opponent_active", "opponent_visible_info", "field_effects"):
            walk(getattr(self, field_name), field_name)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BattleObservation":
        payload = as_versioned_dict(data, kind="battle_observation")
        capture = payload.get("capture_opportunity")
        return cls(
            run_id=str(payload.get("run_id") or ""),
            battle_id=str(payload.get("battle_id") or ""),
            human_id=str(payload.get("human_id") or ""),
            state_version=payload.get("state_version", 0),
            observation_version=payload.get("observation_version", 0),
            turn=payload.get("turn", 0),
            phase=str(payload.get("phase") or "await_action"),
            battle_kind=str(payload.get("battle_kind") or "wild"),
            side=str(payload.get("side") or "player"),
            own_active=require_mapping(payload.get("own_active"), "battle_observation.own_active"),
            own_party=tuple(
                require_mapping(p, "battle_observation.own_party[]")
                for p in require_list(payload.get("own_party"), "battle_observation.own_party", max_items=6)
            ),
            opponent_active=require_mapping(payload.get("opponent_active"), "battle_observation.opponent_active"),
            opponent_visible_info=require_mapping(
                payload.get("opponent_visible_info"), "battle_observation.opponent_visible_info"
            ),
            field_effects=tuple(
                require_mapping(f, "battle_observation.field_effects[]")
                for f in require_list(payload.get("field_effects"), "battle_observation.field_effects", max_items=64)
            ),
            message_log=tuple(
                require_string(m, "battle_observation.message_log[]", max_len=500)
                for m in require_list(payload.get("message_log"), "battle_observation.message_log", max_items=256)
            ),
            legal_actions=tuple(
                LegalBattleAction.from_dict(a)
                for a in require_list(payload.get("legal_actions"), "battle_observation.legal_actions", max_items=64)
            ),
            capture_opportunity=None if capture is None else require_mapping(capture, "battle_observation.capture_opportunity"),
            schema_version=require_int(
                payload.get("schema_version", CONTRACTS_VERSION),
                "battle_observation.schema_version",
                minimum=1,
                maximum=CONTRACTS_VERSION,
            ),
        ).validate()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "battle_observation",
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "battle_id": self.battle_id,
            "human_id": self.human_id,
            "state_version": self.state_version,
            "observation_version": self.observation_version,
            "turn": self.turn,
            "phase": self.phase,
            "battle_kind": self.battle_kind,
            "side": self.side,
            "own_active": dict(self.own_active),
            "own_party": [dict(p) for p in self.own_party],
            "opponent_active": dict(self.opponent_active),
            "opponent_visible_info": dict(self.opponent_visible_info),
            "field_effects": [dict(f) for f in self.field_effects],
            "message_log": list(self.message_log),
            "legal_actions": [a.to_dict() for a in self.legal_actions],
            "capture_opportunity": dict(self.capture_opportunity) if self.capture_opportunity else None,
        }


@dataclass(slots=True)
class BattleAction(Contract):
    """One legal battle choice, bound to the observation it was made from."""

    run_id: str = ""
    battle_id: str = ""
    human_id: str = ""
    action: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    observation_version: int = 0
    expected_state_version: int = 0
    decision_explanation: str = ""
    decision_provenance: dict[str, Any] = field(default_factory=dict)
    scripted_test_mind: bool = False
    schema_version: int = CONTRACTS_VERSION

    def validate(self) -> "BattleAction":
        self.run_id = require_id(self.run_id, "battle_action.run_id")
        self.battle_id = require_id(self.battle_id, "battle_action.battle_id")
        self.human_id = require_id(self.human_id, "battle_action.human_id")
        self.action = require_string(self.action, "battle_action.action", max_len=32)
        if self.action not in LEGAL_BATTLE_ACTIONS:
            raise ContractError(f"battle_action.action {self.action!r} is not legal in battle")
        self.check_version()
        self.arguments = require_mapping(self.arguments, "battle_action.arguments")
        self.observation_version = require_int(
            self.observation_version, "battle_action.observation_version", minimum=0, maximum=2**63 - 1
        )
        self.expected_state_version = require_int(
            self.expected_state_version, "battle_action.expected_state_version", minimum=0, maximum=2**63 - 1
        )
        self.decision_explanation = require_string(
            self.decision_explanation or "(none given)", "battle_action.decision_explanation", max_len=2000
        )
        self.decision_provenance = require_mapping(self.decision_provenance, "battle_action.decision_provenance")
        return self

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BattleAction":
        payload = as_versioned_dict(data, kind="battle_action")
        return cls(
            run_id=str(payload.get("run_id") or ""),
            battle_id=str(payload.get("battle_id") or ""),
            human_id=str(payload.get("human_id") or ""),
            action=str(payload.get("action") or ""),
            arguments=require_mapping(payload.get("arguments"), "battle_action.arguments"),
            observation_version=payload.get("observation_version", 0),
            expected_state_version=payload.get("expected_state_version", 0),
            decision_explanation=str(payload.get("decision_explanation") or ""),
            decision_provenance=require_mapping(payload.get("decision_provenance"), "battle_action.decision_provenance"),
            scripted_test_mind=require_bool(payload.get("scripted_test_mind", False), "battle_action.scripted_test_mind"),
            schema_version=require_int(
                payload.get("schema_version", CONTRACTS_VERSION),
                "battle_action.schema_version",
                minimum=1,
                maximum=CONTRACTS_VERSION,
            ),
        ).validate()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "battle_action",
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "battle_id": self.battle_id,
            "human_id": self.human_id,
            "action": self.action,
            "arguments": dict(self.arguments),
            "observation_version": self.observation_version,
            "expected_state_version": self.expected_state_version,
            "decision_explanation": self.decision_explanation,
            "decision_provenance": dict(self.decision_provenance),
            "scripted_test_mind": self.scripted_test_mind,
        }
