"""Offered movement contracts and inference-time collision regressions."""
import pytest
from test_gameplay import game, state, locate, scenario
from test_shared_clock_engine import activate, choose
from living_kanto.simulation.engine import StaleActionError, EngineError, SimulationEngine
from living_kanto.simulation.routeplanner import public_destinations
from living_kanto.simulation.maps import GameMap


def test_offered_destination_occupied_during_inference_is_stale(game):
    e,store=game
    locate(game,'human-001','PalletTown',(10,10))
    locate(game,'human-002','PalletTown',(12,11))
    activate(game)
    obs,token=e.capture_decision_boundary(state(game),'human-001')
    offered=next(a for a in obs.legal_actions if a.action=='walk_to' and a.arguments=={'direction':'east'})
    locate(game,'human-002','PalletTown',(11,10))
    before=state(game)
    with pytest.raises(StaleActionError,match='movement route changed'):
        choose(game,'human-001',offered.action,offered.arguments,token=token,version=obs.state_version)
    assert state(game).state_hash==before.state_hash


def test_invalid_unoffered_move_is_not_excused_by_other_movement(game):
    e,_=game
    locate(game,'human-001','PalletTown',(10,10))
    activate(game)
    obs,token=e.capture_decision_boundary(state(game),'human-001')
    locate(game,'human-002','PalletTown',(11,10))
    with pytest.raises(EngineError) as failure:
        choose(game,'human-001','travel_to',{'x':-100,'y':-100},token=token,version=obs.state_version)
    assert not isinstance(failure.value,StaleActionError)


def test_valid_move_survives_unrelated_occupant_movement(game):
    e,_=game
    locate(game,'human-001','PalletTown',(10,10))
    activate(game)
    obs,token=e.capture_decision_boundary(state(game),'human-001')
    locate(game,'human-002','CeladonCity',(28,3))
    after=choose(game,'human-001','walk_to',{'direction':'south'},token=token,version=obs.state_version)
    assert after.humans['human-001']['movement_intent']


def test_local_travel_names_exit_without_claiming_map_transfer(game):
    e,_=game
    locate(game,'human-001','PalletTown',(10,10))
    actions=SimulationEngine.legal_actions(e,state(game),'human-001')
    exits=[a for a in actions if a.action=='travel_to' and a.known_consequences['destination_kind']=='exit']
    assert exits
    for a in exits:
        assert a.known_consequences['changes_map'] is False
        assert a.known_consequences['next_action']=='enter_map'
        assert a.known_consequences['exit_target'] in e.maps


def test_adjacent_route_offered_beside_nearby_service_destinations():
    maps={'City':GameMap('City',1,1,['1'],{(0,0):'Route1'}),'Route1':GameMap('Route1',1,1,['1'],{})}
    assert 'Route1' in public_destinations(maps,'City')


def test_no_party_actor_can_choose_lawful_journey_to_starter_lab(game):
    e,_=game
    locate(game,'human-001','ViridianCity',(25,39))
    s=state(game)
    actions=SimulationEngine.legal_actions(e,s,'human-001')
    a=next(a for a in actions if a.action=='journey_to' and a.arguments['map_id']=='PalletTown_ProfessorOaksLab')
    assert a.known_consequences['changes_map']
    assert 'separate legal action' in a.known_consequences['purpose']
    assert a.known_consequences['maps_crossed']>=3


def test_local_person_approaches_do_not_reveal_distant_coordinates(tmp_path):
    from test_simulation_m0 import write_fixture_map
    from living_kanto.store import RunStore
    write_fixture_map(tmp_path, width=30, height=30)
    e=SimulationEngine.from_content(tmp_path)
    with __import__('contextlib').closing(RunStore(tmp_path/'privacy.db')) as store:
        e.create_run(store,run_id='privacy',humans=[('alice','Alice'),('bob','Bob')])
        s=store.load_run('privacy')[1]
        s=s.with_advanced_version([{'op':'set','path':f'humans.{hid}.{key}','value':value}
            for hid,position in [('alice',(10,10)),('bob',(22,22))]
            for key,value in zip(('x','y'),position)])
        gm=e.maps[s.humans['alice']['map_id']];gm.source_revision='explicit-test-only'
        actions=e.legal_actions(s,'alice')
        targets={(a.arguments['x'],a.arguments['y']) for a in actions if a.action=='travel_to'}
        assert not targets & {(21,22),(23,22),(22,21),(22,23)}
        assert 'bob' not in {h['human_id'] for h in e.observation_for(s,'alice').visible_actors}


def test_starter_route_survives_menu_cap_and_names_prerequisite(game, monkeypatch):
    e,_=game
    locate(game,'human-001','ViridianCity',(25,39))
    from living_kanto.contracts import LegalAction
    monkeypatch.setattr(e,'entity_inventory_actions',lambda state,hid:[LegalAction(action='pc_rename_box',arguments={'box':1,'text':'<message, <=200 chars>'},known_consequences={}) for _ in range(200)])
    actions=e.legal_actions(state(game),'human-001')
    assert 0<len(actions)<=128
    routes=[a for a in actions if a.action=='journey_to' and a.arguments.get('map_id')=='PalletTown_ProfessorOaksLab']
    assert routes
    assert routes[0].known_consequences['destination_kind']=='starter'
