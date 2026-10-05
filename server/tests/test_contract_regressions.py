"""Narrow contract regressions for m0-contract-repair-003.

Two defects fixed in contracts/state.py:

1. _set_nested silently replaced an existing non-dict intermediate with {}
   (via setdefault), so a path like ``world_facts.geography.region`` clobbered
   a scalar ``geography`` value into ``{"region": ...}`` instead of raising.
   A *present null* intermediate is likewise an existing non-dict value and
   must be rejected, while a genuinely *absent* key may still create a new
   dict branch. The entity-path traversal used the same get()-based rule and
   converted present nulls into dicts too; both traversals now distinguish
   absence from a present null with ``part not in target``.

2. advance_clock accepted float/bool/string seconds via int() coercion, so
   2.5 lost half a second and 10.0/"30"/True were admitted as if they were ints.
   It now uses require_exact_int (JSON integer only), preserving minimum=0 and
   maximum=2**63-1.

These live in a NEW file to avoid colliding with the builder's concurrent
edits to test_contracts.py.
"""
from __future__ import annotations

import pytest

from living_kanto.contracts import CanonicalEvent, ContractError, WorldState


def make_verified_state(version=1, tick=0, **kw) -> WorldState:
    state = WorldState(
        run_id="run_x",
        state_version=version,
        tick=tick,
        simulated_time=tick,
        clock={"seconds": tick},
        **kw,
    )
    state.state_hash = state.compute_state_hash()
    return state


# --- defect 1: world_facts scalar-path clobber -----------------------------

def test_set_through_scalar_world_facts_intermediate_is_rejected():
    base = make_verified_state(world_facts={"geography": 5})
    with pytest.raises(ContractError, match="cannot traverse non-dict"):
        base.with_advanced_version([
            {"op": "set", "path": "world_facts.geography.region", "value": "Kanto"}
        ])
    # the rejected change must not have reached the source state either
    assert base.world_facts == {"geography": 5}
    base.validate()


def test_remove_through_scalar_world_facts_intermediate_is_rejected():
    # remove never creates branches: _remove_nested treats a non-dict
    # intermediate (scalar OR present null) as a dead end, so the path
    # simply "does not exist" and nothing is mutated.
    base = make_verified_state(world_facts={"geography": 5})
    with pytest.raises(ContractError, match="does not exist"):
        base.with_advanced_version([{"op": "remove", "path": "world_facts.geography.region"}])
    assert base.world_facts == {"geography": 5}
    base.validate()


def test_legitimate_new_world_facts_branch_still_created():
    base = make_verified_state(world_facts={"geography": {}})
    advanced = base.with_advanced_version([
        {"op": "set", "path": "world_facts.geography.region", "value": "Kanto"}
    ])
    assert advanced.world_facts["geography"]["region"] == "Kanto"
    advanced.validate()


def test_absent_world_facts_intermediate_creates_branch():
    # key genuinely missing -> legitimate new branch
    base = make_verified_state(world_facts={})
    advanced = base.with_advanced_version([
        {"op": "set", "path": "world_facts.geography.region", "value": "Kanto"}
    ])
    assert advanced.world_facts == {"geography": {"region": "Kanto"}}
    advanced.validate()


def test_present_null_world_facts_intermediate_is_rejected():
    # key PRESENT with value null is an existing non-dict value, not absence
    base = make_verified_state(world_facts={"existing": None})
    with pytest.raises(ContractError, match="cannot traverse non-dict"):
        base.with_advanced_version([
            {"op": "set", "path": "world_facts.existing.child", "value": 3}
        ])
    assert base.world_facts == {"existing": None}
    base.validate()


def test_present_null_entity_intermediate_is_rejected():
    base = make_verified_state(humans={"h_001": {"position": None}})
    with pytest.raises(ContractError, match="cannot traverse non-dict"):
        base.with_advanced_version([
            {"op": "set", "path": "humans.h_001.position.x", "value": 3}
        ])
    assert base.humans["h_001"]["position"] is None
    base.validate()


def test_absent_entity_intermediate_creates_branch():
    base = make_verified_state(humans={"h_001": {}})
    advanced = base.with_advanced_version([
        {"op": "set", "path": "humans.h_001.position.x", "value": 3}
    ])
    assert advanced.humans["h_001"]["position"] == {"x": 3}
    advanced.validate()


# --- defect 2: strict elapsed-second input ---------------------------------

@pytest.mark.parametrize("bad", [2.5, 10.0, 0.0, True, False, "30"])
def test_advance_clock_rejects_non_integer_seconds(bad):
    base = make_verified_state(tick=10)
    with pytest.raises(ContractError):
        base.with_advanced_version([{"op": "advance_clock", "seconds": bad}])
    base.validate()


def test_advance_clock_accepts_exact_int_seconds():
    base = make_verified_state(tick=10)
    advanced = base.with_advanced_version([{"op": "advance_clock", "seconds": 30}])
    assert advanced.tick == 40 and advanced.simulated_time == 40
    assert advanced.clock["seconds"] == 40
    advanced.validate()


def test_advance_clock_enforces_bounds():
    base = make_verified_state(tick=10)
    with pytest.raises(ContractError):
        base.with_advanced_version([{"op": "advance_clock", "seconds": -1}])
    with pytest.raises(ContractError):
        base.with_advanced_version([{"op": "advance_clock", "seconds": 2**63}])
    base.validate()


# --- event contract still round-trips --------------------------------------

def test_event_round_trip_unchanged():
    ev = CanonicalEvent(
        run_id="run_x",
        event_id="event-000000",
        event_index=0,
        state_version=1,
        previous_head="0" * 64,
        event_kind="human.moved",
        tick=0,
        simulated_time=0,
        real_wall_time="2026-10-04T10:00:00+00:00",
    )
    ev.validate()
    assert CanonicalEvent.from_dict(ev.to_dict()).event_hash == ev.event_hash
