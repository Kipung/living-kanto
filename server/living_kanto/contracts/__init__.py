"""Living Kanto versioned contracts.

Import surface for the shared contract layer. Anything that crosses a boundary
(engine <-> world model, engine <-> mind, server <-> browser, evidence export)
uses these types and their canonical JSON form.
"""

from .base import (
    CONTRACTS_VERSION,
    SUPPORTED_CONTRACT_VERSIONS,
    Contract,
    ContractError,
    canonical_json,
    content_hash,
)
from .battle import (
    BATTLE_KINDS,
    BATTLE_PHASES,
    LEGAL_BATTLE_ACTIONS,
    BattleAction,
    BattleObservation,
    LegalBattleAction,
)
from .events import EVENT_KINDS, CanonicalEvent
from .human import (
    LEGAL_HUMAN_ACTIONS,
    HumanAction,
    HumanObservation,
    LegalAction,
)
from .run import (
    INTERVENTION_KINDS,
    Intervention,
    ModelUsageRecord,
    RunMetadata,
)
from .state import (
    RUN_MODES,
    RUN_PHASES,
    StateUpdate,
    WorldState,
)
from .world import ContentSource, MapRef, WorldDefinition

__all__ = [
    "BATTLE_KINDS",
    "BATTLE_PHASES",
    "BattleAction",
    "BattleObservation",
    "CONTRACTS_VERSION",
    "CanonicalEvent",
    "ContentSource",
    "Contract",
    "ContractError",
    "EVENT_KINDS",
    "HumanAction",
    "HumanObservation",
    "INTERVENTION_KINDS",
    "Intervention",
    "LEGAL_BATTLE_ACTIONS",
    "LEGAL_HUMAN_ACTIONS",
    "LegalAction",
    "LegalBattleAction",
    "MapRef",
    "ModelUsageRecord",
    "RUN_MODES",
    "RUN_PHASES",
    "RunMetadata",
    "StateUpdate",
    "SUPPORTED_CONTRACT_VERSIONS",
    "WorldDefinition",
    "WorldState",
    "canonical_json",
    "content_hash",
]
