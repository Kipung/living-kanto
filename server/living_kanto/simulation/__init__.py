"""Living Kanto simulation core.

The engine owns every mechanic the game requires: canonical state transitions,
map collision, private observation projection, and legal-action construction.
AI humans only *choose* from the legal actions the engine offers; the engine
validates and applies them. This module never calls an inference provider.
"""
from .engine import (
    ENGINE_VERSION,
    EngineError,
    SimulationEngine,
    StaleActionError,
    default_map_paths,
)
from .maps import GameMap, MapLoadError

__all__ = [
    "ENGINE_VERSION",
    "EngineError",
    "GameMap",
    "MapLoadError",
    "SimulationEngine",
    "StaleActionError",
    "default_map_paths",
]
