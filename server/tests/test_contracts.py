"""Contract-layer tests: canonical hashing, round-trips, privacy, and rejection."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from living_kanto.contracts import (  # noqa: E402
    BattleAction,
    BattleObservation,
    CanonicalEvent,
    ContractError,
    HumanAction,
    HumanObservation,
    Intervention,
    ModelUsageRecord,
    RunMetadata,
    StateUpdate,
    ContentSource,
    LegalAction,
    LegalBattleAction,
    WorldDefinition,
    WorldState,
    canonical_json,
    content_hash,
)


def test_canonical_json_is_order_independent_and_hash_is_stable():
    a = {"b": 1, "a": [1, {"z": 1, "y": 2}]}
    b = {"a": [1, {"y": 2, "z": 1}], "b": 1}
    assert canonical_json(a) == canonical_json(b)
    assert content_hash(a) == content_hash(b)
    assert len(content_hash(a)) == 64
    assert content_hash(a) != content_hash({"x": 2})


def test_canonical_json_rejects_non_finite_floats():
    with pytest.raises(ContractError):
        canonical_json({"x": float("nan")})


def test_world_definition_round_trip_and_rejects_empty_sources():
    definition = WorldDefinition(
        world_id="kanto-mainland",
        name="Kanto",
        seed=1,
        population_size=100,
        sources=(
            ContentSource(
                source_id="pret-pokefirered",
                repository="https://github.com/pret/pokefirered",
                revision="037335f4c725d7c9aecdac87066f2002b4bd7e14",
                paths=("data/maps/PalletTown.json",),
                usage_terms="original FRLG data via pret/pokefirered; local research build",
            ),
        ),
    )
    definition.validate()
    payload = definition.to_dict()
    assert WorldDefinition.from_dict(payload).sources[0].source_id == "pret-pokefirered"

    with pytest.raises(ContractError, match="duplicate source_id"):
        WorldDefinition(
            world_id="kanto",
            name="Kanto",
            sources=(definition.sources[0], definition.sources[0]),
        ).validate()


def test_human_observation_round_trip_and_privacy_enforcement():
    observation = HumanObservation(
        run_id="run-1",
        human_id="human-0001",
        state_version=7,
        observation_version=3,
        simulated_time=120,
        self_state={"hp": 100},
        location={"map_id": "PalletTown", "x": 5, "y": 6},
        legal_actions=(
            LegalAction(action="walk_to", arguments={"x": 6, "y": 6}),
        ),
    )
    observation.validate()
    assert HumanObservation.from_dict(observation.to_dict()).observation_hash() == observation.observation_hash()

    smuggled = HumanObservation(
        run_id="run-1",
        human_id="human-0001",
        visible_actors=({"name": "Gary", "hidden_moves": ["Thunderbolt"]},),
    )
    with pytest.raises(ContractError, match="forbidden private key"):
        smuggled.validate()


def test_human_action_rejects_goal_shaped_outcomes():
    for outcome in ("win_battle", "get_badge", "become_champion"):
        with pytest.raises(ContractError, match="not executable"):
            HumanAction(run_id="run-1", human_id="human-0001", action=outcome).validate()

    action = HumanAction(
        run_id="run-1",
        human_id="human-0001",
        action="walk_to",
        arguments={"x": 7, "y": 6},
        observation_version=3,
        expected_state_version=7,
        decision_explanation="heading to Route 1",
    )
    assert HumanAction.from_dict(action.to_dict()).action_hash() == action.action_hash()


def test_battle_observation_hides_opponent_hidden_information():
    observation = BattleObservation(
        run_id="run-1",
        battle_id="battle-1",
        human_id="human-0001",
        own_active={"species": "charmander", "hp": 29},
        opponent_active={"species": "pidgey", "hp": 10},
        legal_actions=(
            LegalBattleAction(action="use_move", arguments={"move_id": "ember"}),
        ),
    )
    observation.validate()
    assert BattleObservation.from_dict(observation.to_dict()).turn == 0

    smuggled = BattleObservation(
        run_id="run-1",
        battle_id="battle-1",
        human_id="human-0001",
        opponent_visible_info={"hidden_moves": ["Gust"]},
    )
    with pytest.raises(ContractError, match="forbidden hidden key"):
        smuggled.validate()

    with pytest.raises(ContractError, match="not legal in battle"):
        BattleAction(
            run_id="run-1", battle_id="battle-1", human_id="human-0001", action="auto_win"
        ).validate()


def make_event(index: int = 0, version: int = 1, prior: str = "0" * 64) -> CanonicalEvent:
    return CanonicalEvent(
        run_id="run-1",
        event_id=f"event-{index:06d}",
        event_index=index,
        state_version=version,
        previous_head=prior,
        event_kind="human.moved",
        tick=index,
        simulated_time=index * 10,
        real_wall_time="2026-10-04T10:00:00+00:00",
        causation={"human_action": "act-1"},
        affected=({"entity": "human-0001", "kind": "human"},),
        before={"position": {"x": 5, "y": 6}},
        after={"position": {"x": 6, "y": 6}},
        deterministic_inputs={"rng_draw": "sha256:abc"},
        transaction={"commit_id": "commit-1"},
        visibility={"observer": True, "humans": ["human-0001"]},
    )


def test_canonical_event_round_trip_and_kind_gate():
    event = make_event()
    assert CanonicalEvent.from_dict(event.to_dict()).event_hash == event.event_hash
    with pytest.raises(ContractError, match="not a versioned event kind"):
        CanonicalEvent.from_dict({**event.to_dict(), "event_kind": "teleport_soul"})


def test_canonical_event_rejects_oversized_delta():
    event = make_event()
    event.after = {"blob": "x" * 300_000}
    with pytest.raises(ContractError, match="limit"):
        event.check_size()


def test_state_update_rejects_version_skip_and_bad_hash():
    with pytest.raises(ContractError, match="skips versions"):
        StateUpdate(
            run_id="run-1",
            event_id="event-000000",
            prior_state_version=1,
            prior_state_hash="a" * 64,
            previous_head="0" * 64,
            state_version=3,
            state_hash="0" * 64,
        ).validate()

    with pytest.raises(ContractError, match="state_hash"):
        StateUpdate(
            run_id="run-1",
            event_id="event-000000",
            prior_state_version=1,
            prior_state_hash="a" * 64,
            previous_head="0" * 64,
            state_version=2,
            state_hash="not-a-hash",
        ).validate()

    # prior_state_hash is a required world-content hash, not optional filler.
    with pytest.raises(ContractError, match="prior_state_hash"):
        StateUpdate(
            run_id="run-1",
            event_id="event-000000",
            prior_state_version=1,
            prior_state_hash="",
            previous_head="0" * 64,
            state_version=2,
            state_hash="0" * 64,
        ).validate()


def test_world_state_hash_recomputes_and_detects_tampering():
    state = WorldState(
        run_id="run-1",
        state_version=0,
        mode="survival",
        phase="created",
        humans={"human-0001": {"name": "Ada"}},
    )
    state.state_hash = state.compute_state_hash()
    state.verify()

    state.humans["human-0001"]["name"] = "Eve"
    with pytest.raises(ContractError, match="does not recompute"):
        state.verify()


def test_intervention_kind_and_reputation_cost_gates():
    Intervention(run_id="run-1", intervention_id="int-1", actor="operator", kind="pause").validate()

    with pytest.raises(ContractError, match="not a supported intervention"):
        Intervention(
            run_id="run-1",
            intervention_id="int-1",
            actor="operator",
            kind="fabricate_victory",
        ).validate()

    with pytest.raises(ContractError, match="positive reputation_cost"):
        Intervention(
            run_id="run-1",
            intervention_id="int-1",
            actor="operator",
            kind="grant_item",
            requires_reputation_cost=True,
            reputation_cost=0,
        ).validate()


def test_run_metadata_round_trip_and_population_cap():
    metadata = RunMetadata(
        run_id="run-1",
        world_id="kanto-mainland",
        world_revision="037335f",
        engine_version="0.1.0",
        code_revision="116a8a7",
        created_at="2026-10-04T10:00:00+00:00",
        data_directory="var/runs/run-1",
        content_manifest_hash=content_hash({"pret-pokefirered": "037335f"}),
        notes="M0 contract test run",
        model_usage=(
            ModelUsageRecord(
                model_id="qwen2.5-coder-27b",
                model_revision="local",
                quantization="q4_k_m",
                runtime="llama.cpp",
                hardware="jetson-agx",
                context_tokens=32768,
                max_new_tokens=4096,
                calls=10,
                failures=1,
                fallbacks=0,
            ),
        ),
    )
    metadata.validate()
    assert RunMetadata.from_dict(metadata.to_dict()).model_usage[0].calls == 10

    with pytest.raises(ContractError, match="population_target"):
        RunMetadata(
            run_id="run-1",
            world_id="kanto",
            engine_version="0.1.0",
            code_revision="116a8a7",
            world_revision="1",
            created_at="x",
            data_directory="var/runs/run-1",
            content_manifest_hash="abc",
            notes="test",
            population_target=101,
        ).validate()

    with pytest.raises(ContractError, match="cannot exceed calls"):
        RunMetadata(
            run_id="run-1",
            world_id="kanto",
            engine_version="0.1.0",
            code_revision="116a8a7",
            world_revision="1",
            created_at="x",
            data_directory="var/runs/run-1",
            content_manifest_hash="abc",
            notes="test",
            model_usage=(
                ModelUsageRecord(
                    model_id="m",
                    model_revision="r",
                    quantization="q",
                    runtime="rt",
                    hardware="hw",
                    calls=3,
                    failures=5,
                ),
            ),
        ).validate()


def test_world_state_apply_changes_and_version_advance():
    ws = WorldState(run_id="run_x", state_version=1, tick=0, simulated_time=0, clock={"seconds": 0})
    advanced = ws.with_advanced_version([
        {"op": "set", "path": "humans.h_001.position.x", "value": 7},
        {"op": "set", "path": "humans.h_001.inventory", "value": [{"item_id": "potion", "qty": 2}]},
        {"op": "advance_clock", "seconds": 5},
    ])
    advanced.validate()
    assert advanced.state_version == 2
    assert advanced.humans["h_001"]["position"]["x"] == 7
    # advance_clock increments BOTH authoritative counters and mirrors the
    # resulting elapsed seconds into the descriptive clock.seconds.
    assert advanced.tick == 5
    assert advanced.simulated_time == 5
    assert advanced.clock == {"seconds": 5}
    assert advanced.state_hash == advanced.compute_state_hash()
    # original untouched
    assert ws.humans == {} and ws.state_version == 1
    # remove op
    removed = advanced.with_advanced_version([{"op": "remove", "path": "humans.h_001"}])
    assert removed.humans == {}
    # bad path and bad op rejected
    with pytest.raises(ContractError, match="unsupported path"):
        advanced.with_advanced_version([{"op": "set", "path": "bogus.a.b", "value": 1}])
    with pytest.raises(ContractError, match="unsupported op"):
        advanced.with_advanced_version([{"op": "explode", "path": "humans.h_001"}])
    # public event append
    appended = advanced.with_advanced_version([
        {"op": "append_public_event", "event": {"kind": "gym.result", "map_id": "1"}}
    ])
    assert len(appended.public_events) == 1


def test_applier_preserves_source_version_hash_and_deep_state():
    # Operator regression 3: apply_changes([]) preserves version/hash fields.
    base = WorldState(
        run_id="run_x",
        state_version=3,
        tick=7,
        clock={"seconds": 7},
        humans={"h_001": {"position": {"x": 1, "y": 2}}},
    )
    base.state_hash = base.compute_state_hash()
    base.validate()
    same = base.apply_changes([])
    assert same.state_version == 3
    assert same.state_hash == base.state_hash
    assert same.to_dict() == base.to_dict()

    # Operator regression 1: with_advanced_version must not mutate the source.
    before = base.to_dict()
    advanced = base.with_advanced_version([
        {"op": "set", "path": "humans.h_001.position.x", "value": 9}
    ])
    assert advanced.humans["h_001"]["position"]["x"] == 9
    assert advanced.state_version == 4
    assert base.to_dict() == before
    base.validate()  # source hash still valid

    # Operator regression 2: world_facts accepts documented 2-part paths.
    facted = base.with_advanced_version([{"op": "set", "path": "world_facts.foo", "value": 1}])
    assert facted.world_facts["foo"] == 1
    facted2 = facted.with_advanced_version([{"op": "remove", "path": "world_facts.foo"}])
    assert "foo" not in facted2.world_facts


def test_applier_failed_second_change_leaves_source_untouched():
    # Operator regression: a change failing midway must not touch the source.
    base = WorldState(
        run_id="run_x",
        state_version=5,
        tick=1,
        clock={"seconds": 1},
        humans={"h_001": {"position": {"x": 1}}},
    )
    base.state_hash = base.compute_state_hash()
    base.validate()
    before = base.to_dict()
    with pytest.raises(ContractError):
        base.with_advanced_version([
            {"op": "set", "path": "humans.h_001.position.x", "value": 9},
            {"op": "explode", "path": "whatever"},
        ])
    assert base.to_dict() == before
    base.validate()
    with pytest.raises(ContractError):
        base.with_advanced_version([
            {"op": "set", "path": "humans.h_001.position.x", "value": 9},
            {"op": "set", "path": "bogus.a.b", "value": 1},
        ])
    assert base.to_dict() == before
    base.validate()


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
    state.validate()
    return state


def test_advance_clock_increments_both_counters_and_clock():
    base = make_verified_state(tick=10)
    advanced = base.with_advanced_version([{"op": "advance_clock", "seconds": 30}])
    assert advanced.tick == 40
    assert advanced.simulated_time == 40
    assert advanced.clock["seconds"] == 40
    # a clock without a 'seconds' key stays descriptive, never fabricated
    plain = WorldState(run_id="run_x", state_version=1, clock={"label": "day"})
    plain.state_hash = plain.compute_state_hash()
    moved = plain.with_advanced_version([{"op": "advance_clock", "seconds": 3}])
    assert moved.tick == 3 and moved.simulated_time == 3
    assert moved.clock == {"label": "day"}


def test_zero_time_change_advances_version_without_time():
    base = make_verified_state(tick=10)
    advanced = base.with_advanced_version([
        {"op": "set", "path": "humans.h_001.position.x", "value": 9}
    ])
    assert advanced.state_version == base.state_version + 1
    assert advanced.tick == 10 and advanced.simulated_time == 10
    assert advanced.clock == {"seconds": 10}


def test_applier_rejects_non_dict_traversal_and_missing_removals():
    base = make_verified_state(humans={"h_001": {"position": 5}})
    with pytest.raises(ContractError, match="cannot traverse non-dict"):
        base.with_advanced_version([{"op": "set", "path": "humans.h_001.position.x", "value": 1}])
    with pytest.raises(ContractError, match="does not exist"):
        base.with_advanced_version([{"op": "remove", "path": "humans.h_001.nope"}])
    with pytest.raises(ContractError, match="does not exist"):
        base.with_advanced_version([{"op": "remove", "path": "humans.h_missing"}])
    with pytest.raises(ContractError, match="does not exist"):
        base.with_advanced_version([{"op": "remove", "path": "world_facts.nope"}])
    base.validate()


def test_with_advanced_version_rejects_stale_or_tampered_source():
    base = make_verified_state()
    tampered = WorldState.from_dict(base.to_dict())
    tampered.humans["intruder"] = {"name": "ghost"}
    with pytest.raises(ContractError, match="does not recompute"):
        tampered.with_advanced_version([{"op": "advance_clock", "seconds": 1}])
    base.validate()


def test_state_update_binds_prior_world_hash_and_applies():
    genesis = make_verified_state(version=0, humans={"h_001": {"position": {"x": 1, "y": 2}}})
    changes = [
        {"op": "set", "path": "humans.h_001.position.x", "value": 7},
        {"op": "advance_clock", "seconds": 5},
    ]
    advanced = genesis.with_advanced_version(changes)
    update = StateUpdate(
        run_id="run_x",
        event_id="event-000000",
        event_index=0,
        prior_state_version=0,
        prior_state_hash=genesis.state_hash,
        previous_head="0" * 64,
        state_version=1,
        state_hash=advanced.state_hash,
        changes=changes,
    ).validate()
    assert StateUpdate.from_dict(update.to_dict()).prior_state_hash == genesis.state_hash
    result = update.apply_to(genesis)
    assert result.to_dict() == advanced.to_dict()

    # wrong prior world content at the right version number: rejected
    diverged = WorldState.from_dict(genesis.to_dict())
    diverged.humans["h_001"]["position"]["x"] = 42
    diverged.state_hash = diverged.compute_state_hash()
    with pytest.raises(ContractError, match="stale or forked"):
        update.apply_to(diverged)

    # right content, wrong version: rejected
    with pytest.raises(ContractError, match="prior version"):
        update.apply_to(advanced)

    # declared result hash not honoured: apply_to verifies the hashed
    # source first, then recomputes; a lying result hash never survives
    lying = StateUpdate.from_dict({**update.to_dict(), "state_hash": "b" * 64})
    with pytest.raises(ContractError, match="state_hash"):
        lying.apply_to(genesis)
