"""Actual offered workplace choices refresh when local duty changes."""
import copy
import pytest
from test_gameplay import game, state, scenario, locate
from test_shared_clock_engine import activate, choose
from living_kanto.simulation import workplaces
from living_kanto.simulation.engine import StaleActionError


def relief_pair(game):
    e, _ = game
    h = next(h for h in state(game).humans.values() if h.get('service_assignment',{}).get('kind')=='shop' and not workplaces.coverage(state(game), h['human_id']))
    hid, other, mid = h['human_id'], 'human-064', h['map_id']
    scenario(game, [{'op':'set','path':f'humans.{other}.service_assignment','value':h['service_assignment']},
                    {'op':'set','path':f'humans.{other}.workplace','value':h['workplace']}])
    locate(game, other, mid)
    activate(game)
    return hid, other, mid


def test_offered_work_relief_becomes_busy_refreshes_without_retrying_obsolete_menu(game):
    e, store = game; hid, other, mid = relief_pair(game)
    before = state(game); obs, token = e.capture_decision_boundary(before, hid)
    assert any(a.action == 'work' for a in obs.legal_actions)
    choose(game, other, 'rest', {})
    changed = state(game); count = store.event_count(changed.run_id)
    assert not any(a.action == 'work' for a in e.legal_actions(changed, hid))
    with pytest.raises(StaleActionError, match='workplace duty or relief'):
        choose(game, hid, 'work', {}, token=token, version=obs.state_version)
    assert store.event_count(changed.run_id) == count
    assert state(game).state_hash == changed.state_hash
    assert store.replay(changed.run_id).state_hash == changed.state_hash


def test_office_shift_change_refreshes_offered_departure(game):
    e, store = game; hid = 'human-044';mid=state(game).humans[hid]['map_id']
    exit_cell, target = next(iter(e.maps[mid].exits.items()))
    locate(game, hid, mid, exit_cell)
    scenario(game, [{'op':'advance_clock','seconds':43199}]);activate(game)
    obs, token = e.capture_decision_boundary(state(game), hid)
    assert any(a.action == 'enter_map' for a in obs.legal_actions)
    e.tick_shared_time(store, 'gameplay-test', 43200)
    with pytest.raises(StaleActionError, match='workplace duty or relief'):
        choose(game, hid, 'enter_map', {'map_id':target}, token=token, version=obs.state_version)


def test_local_relief_change_does_not_invalidate_unrestricted_personal_reflection(game):
    e, _ = game;hid, other, _ = relief_pair(game)
    obs, token = e.capture_decision_boundary(state(game), hid)
    choose(game, other, 'rest', {})
    result = choose(game, hid, 'remember', {'text':'Own reflection'}, token=token, version=obs.state_version)
    assert result.humans[hid]['last_decision']['action'] == 'remember'


def test_offsite_private_relief_changes_do_not_enter_workplace_dependency(game):
    e, _ = game;hid, other, mid = relief_pair(game)
    locate(game, hid, 'PalletTown')
    before = state(game); dependency = e._workplace_dependency(before, hid)
    locate(game, other, 'ViridianCity')
    assert e._workplace_dependency(state(game), hid) == dependency


def test_unrelated_clock_progress_keeps_work_authorization_valid(game):
    e, store = game;hid, _, _ = relief_pair(game)
    before = state(game); obs, token = e.capture_decision_boundary(before, hid)
    e.tick_shared_time(store, 'gameplay-test', before.simulated_time + 5)
    after = choose(game, hid, 'work', {}, token=token, version=obs.state_version)
    assert after.humans[hid]['activity']['kind'] == 'work'
