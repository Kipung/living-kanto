"""M0 simulation engine tests.

Covers: genesis integrity, real content parsing, observation privacy,
legal-action correctness, stale/invalid rejection, atomic commit effects,
cross-store determinism with inference-free replay, and reconnect against a
fresh engine/store instance.

Fixture maps are built to the REAL extracted content schema (root
width/height/map_name, cells with integer collision, events dict with
connections/warp_events) so the engine is tested without depending on
shared content/ working-tree state.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from living_kanto.contracts.events import CanonicalEvent
from living_kanto.simulation import (
    EngineError,
    GameMap,
    SimulationEngine,
    StaleActionError,
)
from living_kanto.store.run_store import RunStore

CONTENT_ROOT = Path(__file__).resolve().parents[2] / "content"
REAL_PALLET_TOWN = CONTENT_ROOT / "maps" / "PalletTown.json"
PROV = {"kind": "model", "model_id": "test-local-model"}


def write_fixture_map(root: Path, width: int = 9, height: int = 9) -> Path:
    """A map in the real extracted schema: open field, a wall stub, one warp
    door, one north edge connection."""
    maps_dir = root / "maps"
    maps_dir.mkdir(parents=True, exist_ok=True)
    cells = []
    for y in range(height):
        for x in range(width):
            blocked = (x == 7 and y in (5, 6, 7))  # wall stub, not on edges
            cells.append({
                "x": x, "y": y, "collision": 1 if blocked else 0,
                "elevation": 0, "behavior": 0, "encounter_type": "none",
                "layer_type": "ground", "metatile_id": 0,
            })
    data = {
        "map_id": "PALLET_TOWN", "map_name": "PalletTown(Fixture)",
        "width": width, "height": height, "cells": cells,
        "events": {
            "connections": [{"direction": "up", "map": "MAP_ROUTE1",
                             "map_name": "Route1", "offset": 0}],
            "warp_events": [{"x": 2, "y": 1, "dest_map": "MAP_HOUSE",
                             "dest_warp_id": 0, "index": 0}],
        },
    }
    path = maps_dir / "PalletTown.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


FIXED_WALL_TIME = "2026-10-04T22:00:00+00:00"


@pytest.fixture()
def engine(tmp_path):
    write_fixture_map(tmp_path)
    return SimulationEngine.from_content(
        tmp_path, wall_time_fn=lambda: FIXED_WALL_TIME)


@pytest.fixture()
def store(tmp_path):
    st = RunStore(tmp_path / "m0.db")
    yield st
    st.close()


def roster(n: int = 100):
    return [(f"human-{i:03d}", f"Human {i:03d}") for i in range(1, n + 1)]


def act(engine, store, run_id, human_id, action, arguments, obs,
        explanation="testing"):
    event, _new = engine.build_action_event(
        store, run_id, human_id, action=action, arguments=dict(arguments),
        observation_version=obs.state_version,
        expected_state_version=obs.state_version,
        decision_explanation=explanation, decision_provenance=PROV)
    return engine.commit(store, event)


# --------------------------------------------------------------- genesis

def test_genesis_integrity(engine, store):
    state = engine.create_run(store, run_id="run-g", humans=roster(100))
    assert state.state_version == 0
    assert len(state.humans) == 100
    state.verify()
    meta, loaded, head = store.load_run("run-g")
    assert loaded.state_hash == state.state_hash
    assert head == "0" * 64 == store.load_head("run-g")
    assert len(loaded.humans) == 100
    gm = engine.maps["pallet-town"]
    for hid, h in loaded.humans.items():
        assert gm.in_bounds(h["x"], h["y"])
        assert gm.is_walkable(h["x"], h["y"])
    assert meta.population_actual == 100


# ------------------------------------------------------------ real content

@pytest.mark.skipif(not REAL_PALLET_TOWN.exists(), reason="real content absent")
def test_real_pallet_town_parses_with_real_schema():
    gm = GameMap.from_content("pallet-town", REAL_PALLET_TOWN)
    raw = json.loads(REAL_PALLET_TOWN.read_text(encoding="utf-8"))
    assert (gm.width, gm.height) == (raw["width"], raw["height"])
    assert gm.display_name == raw["map_name"]
    walkable = sum(gm.is_walkable(x, y) for x in range(gm.width) for y in range(gm.height))
    assert 0 < walkable < gm.width * gm.height  # mix of blocked/open, real data
    assert isinstance(gm.is_walkable(1, 1), bool)
    for (x, y), target in gm.exit_target_cells().items():
        assert gm.in_bounds(x, y) and isinstance(target, str) and target
    # the real events dict contains warp doors and edge connections
    events = raw["events"]
    assert isinstance(events, dict) and "connections" in events and "warp_events" in events


# ------------------------------------------------------------- observation

def test_observation_privacy_and_shape(engine, store):
    engine.create_run(store, run_id="run-o", humans=roster(100))
    _meta, state, _ = store.load_run("run-o")
    obs = engine.get_observation(store, "run-o", "human-001")
    me = state.humans["human-001"]
    expected_visible = {
        oid for oid, o in state.humans.items()
        if oid != "human-001" and o["map_id"] == me["map_id"]
        and abs(o["x"] - me["x"]) <= 6 and abs(o["y"] - me["y"]) <= 6
    }
    seen = {a["human_id"] for a in obs.visible_actors}
    assert seen == set(sorted(expected_visible)[:64])
    assert len(obs.visible_actors) <= 64
    for actor in obs.visible_actors:
        assert set(actor) <= {"human_id", "name", "x", "y", "facing"}
    # hidden humans must not appear anywhere in the serialized observation
    blob = json.dumps(obs.to_dict(), default=str)
    for hid in set(state.humans) - expected_visible - {"human-001"}:
        assert hid not in blob
    assert obs.state_version == obs.observation_version == 0
    assert isinstance(obs.inventory, tuple) and isinstance(obs.memories, tuple)


def test_legal_actions_match_map(engine, store):
    engine.create_run(store, run_id="run-l", humans=roster(100))
    obs = engine.get_observation(store, "run-l", "human-050")
    gm = engine.maps["pallet-town"]
    me = obs.location
    names = [a.action for a in obs.legal_actions]
    assert "wait" in names and "set_goal" in names and "remember" in names
    assert "enter_map" not in names  # connection/warp targets are not loaded maps
    deltas = {"north": (0, -1), "south": (0, 1), "west": (-1, 0), "east": (1, 0)}
    for la in obs.legal_actions:
        if la.action == "walk_to":
            dx, dy = deltas[la.arguments["direction"]]
            tx, ty = me["x"] + dx, me["y"] + dy
            assert gm.in_bounds(tx, ty) and gm.is_walkable(tx, ty)
    assert len({(a.action, json.dumps(a.arguments, sort_keys=True))
                for a in obs.legal_actions}) == len(obs.legal_actions)


# ------------------------------------------------------------- validation

def test_stale_and_invalid_decisions_rejected(engine, store):
    engine.create_run(store, run_id="run-v", humans=roster(100))
    obs = engine.get_observation(store, "run-v", "human-001")
    gm = engine.maps["pallet-town"]
    x, y = obs.location["x"], obs.location["y"]
    walk_north = next((a for a in obs.legal_actions
                       if a.action == "walk_to"
                       and a.arguments["direction"] == "north"), None)
    if walk_north is None:  # north blocked in fixture? pick any legal walk
        walk_north = next(a for a in obs.legal_actions if a.action == "walk_to")

    def build(action, arguments, ov=None, ev=None, prov=PROV, mind=False, why="why"):
        return engine.build_action_event(
            store, "run-v", "human-001", action=action, arguments=dict(arguments),
            observation_version=obs.state_version if ov is None else ov,
            expected_state_version=obs.state_version if ev is None else ev,
            decision_explanation=why, decision_provenance=prov, scripted_test_mind=mind)

    with pytest.raises(StaleActionError):
        build("walk_to", walk_north.arguments, ov=99)
    with pytest.raises(StaleActionError):
        build("walk_to", walk_north.arguments, ev=99)
    with pytest.raises(EngineError):
        build("walk_to", {"direction": "north", "x": 0, "y": 0})  # malformed args
    with pytest.raises(EngineError):
        build("enter_map", {"target_map_id": "MAP_ROUTE1"})  # not a loaded map
    with pytest.raises(EngineError):
        build("walk_to", walk_north.arguments, prov={"kind": "script"})
    with pytest.raises(EngineError):
        build("walk_to", walk_north.arguments, mind=True)
    with pytest.raises(EngineError):
        build("walk_to", walk_north.arguments, why="   ")
    with pytest.raises(EngineError):
        build("cheat", {})


def test_commit_moves_bumps_version_and_persists(engine, store):
    engine.create_run(store, run_id="run-c", humans=roster(100))
    obs = engine.get_observation(store, "run-c", "human-001")
    walk = next(a for a in obs.legal_actions if a.action == "walk_to")
    act(engine, store, "run-c", "human-001", walk.action, walk.arguments, obs)
    _meta, state, head = store.load_run("run-c")
    moved = state.humans["human-001"]
    deltas = {"north": (0, -1), "south": (0, 1), "west": (-1, 0), "east": (1, 0)}
    dx, dy = deltas[walk.arguments["direction"]]
    assert (moved["x"], moved["y"]) == (obs.location["x"] + dx, obs.location["y"] + dy)
    assert state.state_version == 1 and state.simulated_time >= 1
    state.verify()
    ev = store.iter_events("run-c")[0]
    assert ev.event_index == 0 and ev.state_version == 1
    assert ev.previous_head == "0" * 64 and head == ev.event_hash
    assert store.load_head("run-c") == ev.event_hash
    assert store.replay("run-c").state_hash == state.state_hash
    # a second human can still act on the new state
    obs2 = engine.get_observation(store, "run-c", "human-002")
    assert obs2.state_version == 1
    a2 = obs2.legal_actions[0]
    act(engine, store, "run-c", "human-002", a2.action, a2.arguments, obs2)
    assert store.load_run("run-c")[1].state_version == 2
    assert store.load_run("run-c")[1].humans["human-001"]["x"] == moved["x"]


# ------------------------------------------------------------ determinism

def _scripted_rounds(engine, store, run_id, rounds=6):
    for r in range(rounds):
        hid = f"human-{(r % 5) + 1:03d}"
        obs = engine.get_observation(store, run_id, hid)
        a = next((la for la in obs.legal_actions if la.action == "walk_to"),
                 next(la for la in obs.legal_actions if la.action == "wait"))
        act(engine, store, run_id, hid, a.action, a.arguments, obs, explanation=f"round {r}")


def test_two_stores_same_script_are_identical(engine, tmp_path):
    states = []
    for k in ("a", "b"):
        st = RunStore(tmp_path / f"{k}.db")
        engine.create_run(st, run_id="run-d", humans=roster(100))
        _scripted_rounds(engine, st, "run-d")
        live = st.load_run("run-d")[1]
        replayed = st.replay("run-d")
        assert replayed.state_hash == live.state_hash  # inference-free replay
        seq = [(e.event_index, e.event_kind, e.state_version,
                json.dumps(e.transaction, sort_keys=True))
               for e in store_events(st, "run-d")]
        states.append((live, seq))
        st.close()
    (la, sa), (lb, sb) = states
    assert la.state_hash == lb.state_hash and sa == sb


def store_events(store, run_id):
    return store.iter_events(run_id)


# --------------------------------------------------------------- reconnect

def test_reconnect_with_fresh_engine_instance(engine, store, tmp_path):
    engine.create_run(store, run_id="run-r", humans=roster(100))
    obs = engine.get_observation(store, "run-r", "human-003")
    walk = next(a for a in obs.legal_actions if a.action == "walk_to")
    act(engine, store, "run-r", "human-003", walk.action, walk.arguments, obs)
    store.close()
    # client reconnects: brand-new engine and store objects over the same file
    engine2 = SimulationEngine.from_content(
        tmp_path, wall_time_fn=lambda: FIXED_WALL_TIME)
    store2 = RunStore(tmp_path / "m0.db")
    _meta, state, head = store2.load_run("run-r")
    assert state.state_version == 1 and state.verify()
    obs2 = engine2.get_observation(store2, "run-r", "human-003")
    deltas = {"north": (0, -1), "south": (0, 1), "west": (-1, 0), "east": (1, 0)}
    dx, dy = deltas[walk.arguments["direction"]]
    assert (obs2.location["x"], obs2.location["y"]) == (
        obs.location["x"] + dx, obs.location["y"] + dy)
    # the stale pre-disconnect observation is rejected
    with pytest.raises(StaleActionError):
        act(engine2, store2, "run-r", "human-003", walk.action, walk.arguments, obs)
    # and a fresh action commits
    a = obs2.legal_actions[0]
    act(engine2, store2, "run-r", "human-003", a.action, a.arguments, obs2)
    assert store2.load_run("run-r")[1].state_version == 2
    store2.close()


# ------------------------------------------------- private goal & memories

def test_goal_and_two_memories_nested_and_visible_to_self(engine, store):
    """Positive regression for the slash-path defect: goal/memories must land
    in real nested structures (no orphan 'goal/text' keys), sequential
    remembers must not overwrite slot 0, and own observation must show all."""
    engine.create_run(store, run_id="run-m", humans=roster(100))
    obs = engine.get_observation(store, "run-m", "human-001")
    act(engine, store, "run-m", "human-001", "set_goal", {"text": "find the north gate"}, obs)
    obs = engine.get_observation(store, "run-m", "human-001")
    act(engine, store, "run-m", "human-001", "remember", {"text": "memory one"}, obs)
    obs = engine.get_observation(store, "run-m", "human-001")
    act(engine, store, "run-m", "human-001", "remember", {"text": "memory two"}, obs)
    _meta, state, _ = store.load_run("run-m")
    me = state.humans["human-001"]
    # real nested dicts, not orphan literal-slash keys
    assert me["goal"] == {"text": "find the north gate"}
    assert me["memories"] == {"0": {"text": "memory one"}, "1": {"text": "memory two"}}
    assert not any("/" in k for k in me), f"orphan slash-path keys present: {list(me)}"
    # own observation sees goal and BOTH memories, in order
    obs = engine.get_observation(store, "run-m", "human-001")
    assert obs.self_state["goal"] == {"text": "find the north gate"}
    assert obs.memories == ({"text": "memory one"}, {"text": "memory two"})


def test_private_goal_memories_invisible_to_other_humans(engine, store):
    engine.create_run(store, run_id="run-p", humans=roster(100))
    obs = engine.get_observation(store, "run-p", "human-001")
    act(engine, store, "run-p", "human-001", "set_goal", {"text": "SECRET-GOAL-XYZ"}, obs)
    obs = engine.get_observation(store, "run-p", "human-001")
    act(engine, store, "run-p", "human-001", "remember", {"text": "SECRET-MEM-ABC"}, obs)
    # a nearby human on the same map sees only public actor fields
    near = next(oid for oid in store.load_run("run-p")[1].humans
                if oid != "human-001")
    other = engine.get_observation(store, "run-p", near)
    blob = json.dumps(other.to_dict(), default=str)
    assert "SECRET-GOAL-XYZ" not in blob and "SECRET-MEM-ABC" not in blob
    if near in {a["human_id"] for a in other.visible_actors}:
        vis = next(a for a in other.visible_actors if a["human_id"] == near)
        assert set(vis) <= {"human_id", "name", "x", "y", "facing"}


def test_goal_memories_survive_restart_and_replay_inference_free(engine, store, tmp_path):
    engine.create_run(store, run_id="run-s", humans=roster(100))
    obs = engine.get_observation(store, "run-s", "human-002")
    act(engine, store, "run-s", "human-002", "set_goal", {"text": "reach the shop"}, obs)
    obs = engine.get_observation(store, "run-s", "human-002")
    act(engine, store, "run-s", "human-002", "remember", {"text": "first errand"}, obs)
    obs = engine.get_observation(store, "run-s", "human-002")
    act(engine, store, "run-s", "human-002", "remember", {"text": "second errand"}, obs)
    live = store.load_run("run-s")[1]
    # inference-free replay reproduces the same nested private state
    replayed = store.replay("run-s")
    assert replayed.state_hash == live.state_hash
    store.close()
    engine2 = SimulationEngine.from_content(
        tmp_path, wall_time_fn=lambda: FIXED_WALL_TIME)
    store2 = RunStore(tmp_path / "m0.db")
    _meta, state, _ = store2.load_run("run-s")
    me = state.humans["human-002"]
    assert me["goal"] == {"text": "reach the shop"}
    assert me["memories"] == {"0": {"text": "first errand"}, "1": {"text": "second errand"}}
    obs2 = engine2.get_observation(store2, "run-s", "human-002")
    assert obs2.self_state["goal"] == {"text": "reach the shop"}
    assert obs2.memories == ({"text": "first errand"}, {"text": "second errand"})
    store2.close()
