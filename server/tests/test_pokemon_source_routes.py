"""Public gift approaches preserve source eligibility and actual ownership."""
import copy
from test_gameplay import game, state, locate, scenario
from living_kanto.simulation.pokemon_sources import route_actions
from living_kanto.mechanics.source_gifts import gift_templates
from living_kanto.contracts import LegalAction


def test_gift_approach_is_movement_and_does_not_grant_a_pokemon(game):
    e,_=game;gift=gift_templates()['eevee']
    locate(game,'human-001',gift['map_id'],(7,6))
    s=state(game);before=copy.deepcopy(s.to_dict())
    routes=route_actions(e,s,'human-001',[])
    assert routes and routes[0].action=='travel_to'
    assert routes[0].known_consequences['separate_action_required']=='receive_source_gift'
    assert s.to_dict()==before and not s.humans['human-001']['party']
    steps=e._plan_movement(s,'human-001',routes[0].action,routes[0].arguments)
    assert steps


def test_claimed_gift_and_owned_party_do_not_create_new_gift_approaches(game):
    e,_=game;gift=gift_templates()['eevee']
    locate(game,'human-001',gift['map_id'],(7,6))
    scenario(game,[{'op':'set','path':'humans.human-001.source_gifts','value':['eevee','lapras','dojo_hitmon']}])
    assert not route_actions(e,state(game),'human-001',[])
    s=state(game);s.humans['human-001']['party']=['existing-owned-test-pokemon']
    assert not route_actions(e,s,'human-001',[])


def test_existing_starter_route_keeps_additional_gift_search_bounded(game):
    e,_=game;s=state(game)
    starter=LegalAction(action='journey_to',arguments={'map_id':'PalletTown_ProfessorOaksLab'},known_consequences={'destination_kind':'starter'})
    assert not route_actions(e,s,'human-001',[starter])
    assert not route_actions(e,s,'human-001',[],include_routes=False)
