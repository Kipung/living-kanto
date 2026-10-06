"""Spawn-safe private observation preparation, without providers or stores.

Each child loads immutable content once. Requests contain only a detached
canonical snapshot and one actor ID; results contain that actor's observation
and the engine's dependency token. Children cannot commit simulation events.
"""
from __future__ import annotations

import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor

from ..simulation.world import WorldEngine

_child_engine = None


def preparation_mode():
    mode = os.environ.get('LK_PREPARATION_MODE', 'thread')
    if mode not in {'thread', 'process'}:
        raise ValueError('LK_PREPARATION_MODE must be thread or process')
    return mode


def initialize_preparation_worker(content_root):
    global _child_engine
    _child_engine = WorldEngine(content_root)


def prepare_in_process(snapshot, actor):
    if _child_engine is None:
        raise RuntimeError('Observation preparation worker is not initialized')
    return _child_engine.capture_decision_boundary(snapshot, actor)


def process_preparation_pool(content_root, max_workers):
    # Spawn never inherits SQLite connections, locks, provider clients, or live
    # controller objects from the backend. Content is passed once at startup.
    return ProcessPoolExecutor(max_workers=max_workers,
        mp_context=multiprocessing.get_context('spawn'),
        initializer=initialize_preparation_worker,
        initargs=(str(content_root),))
