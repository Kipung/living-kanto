"""HumanObservation / HumanAction: private information and validated intentions.

Privacy is a contract property, not a UI convention: an observation is a
separately-constructed object that simply does not contain hidden state
(PROJECT_GUIDE section 4). Actions are semantic intentions validated by the
engine; a model is never given database, shell, or world-edit capability.
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

# Semantic intentions only. "win_battle", "get_badge" and "become_champion" are
# goals and are deliberately absent: they are not executable outcomes.
LEGAL_HUMAN_ACTIONS = frozenset(
    {
        "walk_to",
        "travel_to",
        "journey_to",
        "fly_to", "flash", "ride_bicycle", "dismount_bicycle",
        "surf",
        "ride_elevator",
        "use_scenario",
        "pick_up_item",
        "stop_surf",
        "cut",
        "push_boulder",
        "work",
        "battle_move",
        "battle_switch",
        "evolve",
        "learn_move",
        "league_enter",
        "choose_starter",
        "enter_map",
        "use_exit",
        "wait",
        "talk_to",
        "inspect",
        "use_item",
        "use_field_item",
        "use_field_move",
        "teach_machine",
        "trade_offer",
        "trade_accept",
        "trade_decline",
        "heal_party",
        "serve_customer",
        "cancel_service",
        "wait_until_ready",
        "cancel_activity",
        "cancel_movement",
        "shop_buy",
        "shop_sell",
        "store_withdraw",
        "store_deposit",
        "release_pokemon",
        "give_held_item",
        "take_held_item",
        "receive_source_gift",
        "start_battle",
        "flee_battle",
        "catch",
        "train",
        "fish",
        "safari_enter",
        "safari_action",
        "learn_from_tutor",
        "challenge_trainer",
        "accept_challenge",
        "decline_challenge",
        "battle_turn",
        "start_ghost_battle",
        "start_static_battle",
        "start_snorlax_battle",
        "start_electrode_battle",
        "rest",
        "set_goal",
        "abandon_goal",
        "remember",
    }
)

MAX_VISIBLE_ACTORS = 64
MAX_LEGAL_ACTIONS = 128


@dataclass(slots=True)
class LegalAction:
    """A validated option with its known consequences, offered to a mind."""

    action: str
    arguments: dict[str, Any] = field(default_factory=dict)
    known_consequences: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalAction":
        payload = as_versioned_dict(data, kind="legal_action")
        action = require_string(payload.get("action"), "legal_action.action", max_len=64)
        if action not in LEGAL_HUMAN_ACTIONS:
            raise ContractError(f"legal_action.action {action!r} is not a legal human action")
        return cls(
            action=action,
            arguments=require_mapping(payload.get("arguments"), "legal_action.arguments"),
            known_consequences=require_mapping(
                payload.get("known_consequences"), "legal_action.known_consequences"
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "legal_action",
            "action": self.action,
            "arguments": dict(self.arguments),
            "known_consequences": dict(self.known_consequences),
        }


@dataclass(slots=True)
class HumanObservation(Contract):
    """Private information available to one human at one decision point.

    Contains only: own state/party/inventory/goals/memories, visible
    surroundings, learned public information, and battle information revealed
    through normal play. Never: hidden opponent moves, unrevealed stats, global
    memories, private relationships, or future random outcomes.
    """

    run_id: str = ""
    human_id: str = ""
    state_version: int = 0
    observation_version: int = 0
    simulated_time: int = 0
    schema_version: int = CONTRACTS_VERSION
    self_state: dict[str, Any] = field(default_factory=dict)
    party: tuple[dict[str, Any], ...] = ()
    inventory: tuple[dict[str, Any], ...] = ()
    money: int = 0
    badges: tuple[str, ...] = ()
    goals: tuple[dict[str, Any], ...] = ()
    memories: tuple[dict[str, Any], ...] = ()
    location: dict[str, Any] = field(default_factory=dict)
    visible_actors: tuple[dict[str, Any], ...] = ()
    visible_interactions: tuple[dict[str, Any], ...] = ()
    public_knowledge: tuple[dict[str, Any], ...] = ()
    revealed_battle_info: dict[str, Any] = field(default_factory=dict)
    legal_actions: tuple[LegalAction, ...] = ()
    pending_interruption: dict[str, Any] | None = None

    def validate(self) -> "HumanObservation":
        self.run_id = require_id(self.run_id, "human_observation.run_id")
        self.human_id = require_id(self.human_id, "human_observation.human_id")
        self.check_version()
        self.state_version = require_int(
            self.state_version, "human_observation.state_version", minimum=0, maximum=2**63 - 1
        )
        self.observation_version = require_int(
            self.observation_version, "human_observation.observation_version", minimum=0, maximum=2**63 - 1
        )
        self.simulated_time = require_int(
            self.simulated_time, "human_observation.simulated_time", minimum=0, maximum=2**63 - 1
        )
        self.money = require_int(self.money, "human_observation.money", minimum=0, maximum=999_999_999)
        self.badges = tuple(require_id(b, "human_observation.badges[]") for b in self.badges)
        self.self_state = require_mapping(self.self_state, "human_observation.self_state")
        self.location = require_mapping(self.location, "human_observation.location")
        self.revealed_battle_info = require_mapping(
            self.revealed_battle_info, "human_observation.revealed_battle_info"
        )
        if len(self.party) > 6:
            raise ContractError("human_observation.party may not exceed 6 members")
        if len(self.visible_actors) > MAX_VISIBLE_ACTORS:
            raise ContractError(f"human_observation.visible_actors may not exceed {MAX_VISIBLE_ACTORS}")
        if len(self.legal_actions) > MAX_LEGAL_ACTIONS:
            raise ContractError(f"human_observation.legal_actions may not exceed {MAX_LEGAL_ACTIONS}")
        self._assert_no_hidden_leaks()
        return self

    def observation_hash(self) -> str:
        """Content hash of the observation; viewers/agents can anchor to it."""
        return content_hash(self.to_dict())

    def _assert_no_hidden_leaks(self) -> None:
        """Defense in depth: reject keys that must never reach a private mind."""
        banned = {
            "hidden_move",
            "hidden_moves",
            "opponent_move_choice",
            "opponent_hidden_move",
            "enemy_hidden_move",
            "global_memories",
            "private_relationships",
            "rng",
            "random_seed",
            "seed",
            "future_outcomes",
            "encounter_forecast",
            "all_humans",
            "world_state",
        }

        def walk(node: Any, path: str) -> None:
            if isinstance(node, Mapping):
                for key, value in node.items():
                    if str(key).lower() in banned:
                        raise ContractError(
                            f"human_observation.{path} contains forbidden private key {key!r}"
                        )
                    walk(value, f"{path}.{key}")
            elif isinstance(node, (list, tuple)):
                for index, value in enumerate(node):
                    walk(value, f"{path}[{index}]")

        for field_name in ("self_state", "location", "revealed_battle_info"):
            walk(getattr(self, field_name), field_name)
        for index, actor in enumerate(self.visible_actors):
            walk(actor, f"visible_actors[{index}]")
        for index, item in enumerate(self.inventory):
            walk(item, f"inventory[{index}]")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HumanObservation":
        payload = as_versioned_dict(data, kind="human_observation")
        pending = payload.get("pending_interruption")
        return cls(
            run_id=str(payload.get("run_id") or ""),
            human_id=str(payload.get("human_id") or ""),
            state_version=payload.get("state_version", 0),
            observation_version=payload.get("observation_version", 0),
            simulated_time=payload.get("simulated_time", 0),
            schema_version=require_int(
                payload.get("schema_version", CONTRACTS_VERSION),
                "human_observation.schema_version",
                minimum=1,
                maximum=CONTRACTS_VERSION,
            ),
            self_state=require_mapping(payload.get("self_state"), "human_observation.self_state"),
            party=tuple(
                require_mapping(p, "human_observation.party[]")
                for p in require_list(payload.get("party"), "human_observation.party", max_items=6)
            ),
            inventory=tuple(
                require_mapping(i, "human_observation.inventory[]")
                for i in require_list(payload.get("inventory"), "human_observation.inventory", max_items=512)
            ),
            money=payload.get("money", 0),
            badges=tuple(require_list(payload.get("badges"), "human_observation.badges", max_items=16)),
            goals=tuple(
                require_mapping(g, "human_observation.goals[]")
                for g in require_list(payload.get("goals"), "human_observation.goals", max_items=64)
            ),
            memories=tuple(
                require_mapping(m, "human_observation.memories[]")
                for m in require_list(payload.get("memories"), "human_observation.memories", max_items=256)
            ),
            location=require_mapping(payload.get("location"), "human_observation.location"),
            visible_actors=tuple(
                require_mapping(a, "human_observation.visible_actors[]")
                for a in require_list(payload.get("visible_actors"), "human_observation.visible_actors", max_items=MAX_VISIBLE_ACTORS)
            ),
            visible_interactions=tuple(
                require_mapping(i, "human_observation.visible_interactions[]")
                for i in require_list(
                    payload.get("visible_interactions"), "human_observation.visible_interactions", max_items=128
                )
            ),
            public_knowledge=tuple(
                require_mapping(k, "human_observation.public_knowledge[]")
                for k in require_list(payload.get("public_knowledge"), "human_observation.public_knowledge", max_items=256)
            ),
            revealed_battle_info=require_mapping(
                payload.get("revealed_battle_info"), "human_observation.revealed_battle_info"
            ),
            legal_actions=tuple(
                LegalAction.from_dict(a)
                for a in require_list(payload.get("legal_actions"), "human_observation.legal_actions", max_items=MAX_LEGAL_ACTIONS)
            ),
            pending_interruption=None if pending is None else require_mapping(pending, "human_observation.pending_interruption"),
        ).validate()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "human_observation",
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "human_id": self.human_id,
            "state_version": self.state_version,
            "observation_version": self.observation_version,
            "simulated_time": self.simulated_time,
            "self_state": dict(self.self_state),
            "party": [dict(p) for p in self.party],
            "inventory": [dict(i) for i in self.inventory],
            "money": self.money,
            "badges": list(self.badges),
            "goals": [dict(g) for g in self.goals],
            "memories": [dict(m) for m in self.memories],
            "location": dict(self.location),
            "visible_actors": [dict(a) for a in self.visible_actors],
            "visible_interactions": [dict(i) for i in self.visible_interactions],
            "public_knowledge": [dict(k) for k in self.public_knowledge],
            "revealed_battle_info": dict(self.revealed_battle_info),
            "legal_actions": [a.to_dict() for a in self.legal_actions],
            "pending_interruption": dict(self.pending_interruption) if self.pending_interruption else None,
        }


@dataclass(slots=True)
class HumanAction(Contract):
    """A validated semantic intention from one human.

    `decision_explanation` is a recorded statement, not proof of the actor's
    actual knowledge or correctness (PROJECT_GUIDE section 4).
    """

    run_id: str = ""
    human_id: str = ""
    action: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    observation_version: int = 0
    expected_state_version: int = 0
    decision_explanation: str = ""
    goal_update: dict[str, Any] | None = None
    plan_update: dict[str, Any] | None = None
    decision_provenance: dict[str, Any] = field(default_factory=dict)
    schema_version: int = CONTRACTS_VERSION
    scripted_test_mind: bool = False

    def validate(self) -> "HumanAction":
        self.run_id = require_id(self.run_id, "human_action.run_id")
        self.human_id = require_id(self.human_id, "human_action.human_id")
        self.action = require_string(self.action, "human_action.action", max_len=64)
        if self.action not in LEGAL_HUMAN_ACTIONS:
            raise ContractError(
                f"human_action.action {self.action!r} is not executable; goals such as "
                "win_battle, get_badge and become_champion are not actions"
            )
        self.check_version()
        self.arguments = require_mapping(self.arguments, "human_action.arguments")
        self.observation_version = require_int(
            self.observation_version, "human_action.observation_version", minimum=0, maximum=2**63 - 1
        )
        self.expected_state_version = require_int(
            self.expected_state_version, "human_action.expected_state_version", minimum=0, maximum=2**63 - 1
        )
        self.decision_explanation = require_string(
            self.decision_explanation or "(none given)", "human_action.decision_explanation", max_len=2000
        )
        if self.goal_update is not None:
            self.goal_update = require_mapping(self.goal_update, "human_action.goal_update")
        if self.plan_update is not None:
            self.plan_update = require_mapping(self.plan_update, "human_action.plan_update")
        self.decision_provenance = require_mapping(
            self.decision_provenance, "human_action.decision_provenance"
        )
        return self

    def action_hash(self) -> str:
        return content_hash(self.to_dict())

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HumanAction":
        payload = as_versioned_dict(data, kind="human_action")
        return cls(
            run_id=str(payload.get("run_id") or ""),
            human_id=str(payload.get("human_id") or ""),
            action=str(payload.get("action") or ""),
            arguments=require_mapping(payload.get("arguments"), "human_action.arguments"),
            observation_version=payload.get("observation_version", 0),
            expected_state_version=payload.get("expected_state_version", 0),
            decision_explanation=str(payload.get("decision_explanation") or ""),
            goal_update=(
                None
                if payload.get("goal_update") is None
                else require_mapping(payload.get("goal_update"), "human_action.goal_update")
            ),
            plan_update=(
                None
                if payload.get("plan_update") is None
                else require_mapping(payload.get("plan_update"), "human_action.plan_update")
            ),
            decision_provenance=require_mapping(
                payload.get("decision_provenance"), "human_action.decision_provenance"
            ),
            schema_version=require_int(
                payload.get("schema_version", CONTRACTS_VERSION),
                "human_action.schema_version",
                minimum=1,
                maximum=CONTRACTS_VERSION,
            ),
            scripted_test_mind=require_bool(payload.get("scripted_test_mind", False), "human_action.scripted_test_mind"),
        ).validate()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "human_action",
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "human_id": self.human_id,
            "action": self.action,
            "arguments": dict(self.arguments),
            "observation_version": self.observation_version,
            "expected_state_version": self.expected_state_version,
            "decision_explanation": self.decision_explanation,
            "goal_update": dict(self.goal_update) if self.goal_update else None,
            "plan_update": dict(self.plan_update) if self.plan_update else None,
            "decision_provenance": dict(self.decision_provenance),
            "scripted_test_mind": self.scripted_test_mind,
        }
