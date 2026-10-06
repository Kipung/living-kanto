"""Workplace policy integration with explicit user test decisions."""
import copy
import pytest
from test_gameplay import game, state, scenario, act, locate
from living_kanto.simulation import workplaces, scheduling
from living_kanto.simulation.engine import EngineError


def test_initial_offices_and_staff_inside_assigned_buildings(game):
    engine, _ = game
    current = state(game)
    for h in current.humans.values():
        if h.get('workplace'):
            assert h['map_id'] == h['workplace']['map_id']
            assert engine.maps[h['map_id']].can_stand(h['x'], h['y'])
    assert current.humans['human-044']['map_id'] == 'PalletTown_ProfessorOaksLab'
    assert sum(bool(h.get('workplace')) for h in current.humans.values()) == 45


def test_sole_staff_cannot_leave_or_start_hour_of_unavailable_work(game):
    engine, _ = game
    h = next(h for h in state(game).humans.values() if h.get('service_assignment',{}).get('kind')=='shop' and not workplaces.coverage(state(game), h['human_id']))
    hid, mid = h['human_id'], h['map_id']
    exit_cell, target = next(iter(engine.maps[mid].exits.items()))
    locate(game, hid, mid, exit_cell)
    assert not any(a.action in {'enter_map','journey_to','fly_to','work'} for a in engine.legal_actions(state(game), hid))
    with pytest.raises(EngineError): act(game, hid, 'enter_map', {'map_id':target})
    assert any(a.action == 'rest' for a in engine.legal_actions(state(game), hid))


def test_relief_allows_departure_but_busy_relief_does_not(game):
    engine, _ = game
    h = next(h for h in state(game).humans.values() if h.get('service_assignment',{}).get('kind')=='shop' and not workplaces.coverage(state(game), h['human_id']))
    hid = h['human_id']; other = 'human-064'; mid = h['map_id']
    scenario(game, [{'op':'set','path':f'humans.{other}.service_assignment','value':h['service_assignment']},
                    {'op':'set','path':f'humans.{other}.workplace','value':h['workplace']}])
    locate(game, other, mid)
    exit_cell, target = next(iter(engine.maps[mid].exits.items()))
    locate(game, hid, mid, exit_cell)
    assert workplaces.coverage(state(game), hid) == [other]
    assert any(a.action == 'enter_map' for a in engine.legal_actions(state(game), hid))
    act(game, other, 'rest')
    assert not workplaces.coverage(state(game), hid)
    assert not any(a.action == 'enter_map' for a in engine.legal_actions(state(game), hid))


def test_return_route_and_no_remote_wages(game):
    engine, _ = game
    h = next(h for h in state(game).humans.values() if h.get('service_assignment', {}).get('map_id') == 'ViridianCity_Mart')
    hid = h['human_id']; locate(game, hid, 'ViridianCity')
    current = state(game)
    assert any(a.action == 'journey_to' and a.arguments['map_id'] == 'ViridianCity_Mart' for a in engine.legal_actions(current, hid))
    assert not any(a.action == 'work' for a in engine.legal_actions(current, hid))
    with pytest.raises(scheduling.ScheduleError): scheduling.start_activity(current, hid, 'work', {}, {'kind':'user'}, 'Test remote wages')
    duty = engine.observation_for(current, hid).self_state['workplace_duty']
    assert duty['on_duty'] and not duty['at_workplace']


def test_migration_preserves_people_history_busy_actions_and_replay(game):
    engine, store = game
    locate(game, 'human-044', 'PalletTown')
    nurse = next(h for h in state(game).humans.values() if h.get('service_assignment'))
    locate(game, nurse['human_id'], 'PalletTown')
    act(game, nurse['human_id'], 'rest')
    before = state(game); previous_count = store.event_count(before.run_id)
    _, _, head = store.load_run(before.run_id)
    event, after = workplaces.build_migration_event(engine, before, head)
    engine.commit(store, event)
    assert after.world_facts['creative_modified'] is True
    assert event.before['humans.human-044.map_id'] == 'PalletTown'
    assert event.after['humans.human-044.map_id'] == 'PalletTown_ProfessorOaksLab'
    assert {'human_id':'human-044'} in event.affected
    assert event.causation['provenance']['author'] == 'workplace-update'
    assert after.humans['human-044']['map_id'] == 'PalletTown_ProfessorOaksLab'
    assert after.humans[nurse['human_id']]['map_id'] == 'PalletTown'
    for hid, h in before.humans.items():
        for key in ('memories','relationships','party','box','inventory','badges','activity','movement_intent','individual_life'):
            assert after.humans[hid].get(key) == h.get(key)
    assert after.pokemon == before.pokemon
    assert store.event_count(before.run_id) == previous_count + 1
    assert store.replay(before.run_id).state_hash == after.state_hash


def test_office_shift_allows_outings_after_duty(game):
    engine, _ = game
    hid = 'human-044';mid = state(game).humans[hid]['map_id']
    exit_cell, _ = next(iter(engine.maps[mid].exits.items()))
    locate(game, hid, mid, exit_cell)
    assert not any(a.action == 'enter_map' for a in engine.legal_actions(state(game), hid))
    scenario(game, [{'op':'advance_clock','seconds':28800}])
    assert any(a.action == 'enter_map' for a in engine.legal_actions(state(game), hid))


def test_shared_departure_cannot_use_relief_that_has_started_leaving(game):
    engine, store = game
    h = next(h for h in state(game).humans.values() if h.get('service_assignment',{}).get('kind')=='shop' and not workplaces.coverage(state(game), h['human_id']))
    hid = h['human_id']; other = 'human-064'; mid = h['map_id']
    scenario(game, [{'op':'set','path':f'humans.{other}.service_assignment','value':h['service_assignment']},
                    {'op':'set','path':f'humans.{other}.workplace','value':h['workplace']}])
    exit_cell, target = next(iter(engine.maps[mid].exits.items()))
    locate(game, hid, mid, exit_cell); locate(game, other, mid, exit_cell)
    engine.activate_shared_clock(store, 'gameplay-test')
    current = state(game)
    obs, token = engine.capture_decision_boundary(current, hid)
    other_obs, other_token = engine.capture_decision_boundary(current, other)
    choice = {'action':'enter_map','arguments':{'map_id':target},'decision_explanation':'Explicit test departure with relief'}
    event, _ = engine.build_revalidated_action_event(store, 'gameplay-test', hid, choice, obs.state_version, token, {'kind':'user','author':'test'})
    engine.commit(store,event)
    with pytest.raises(EngineError):
        engine.build_revalidated_action_event(store, 'gameplay-test', other, choice, other_obs.state_version, other_token, {'kind':'user','author':'test'})


def test_offsite_duty_does_not_reveal_remote_relief(game):
    engine, _ = game
    h = next(h for h in state(game).humans.values() if h.get('service_assignment'))
    hid = h['human_id']; mid = h['workplace']['map_id']
    other = 'human-064' if hid != 'human-064' else 'human-063'
    scenario(game, [{'op':'set','path':f'humans.{other}.service_assignment','value':h['service_assignment']}])
    locate(game, hid, 'PalletTown');locate(game, other, mid)
    before = workplaces.duty_info(state(game), hid)
    assert before['covering_staff'] == [] and before['on_duty']
    locate(game, other, 'ViridianCity')
    assert workplaces.duty_info(state(game), hid) == before
    locate(game, other, mid);act(game, other, 'rest')
    assert workplaces.duty_info(state(game), hid) == before
