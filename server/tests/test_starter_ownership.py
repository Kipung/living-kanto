"""A trainer's first starter remains the same individual after ownership changes."""
import copy
import pytest
from test_gameplay import game,state,locate,scenario,act
from living_kanto.simulation.engine import EngineError, SimulationEngine


def choose_then_transfer_fixture(game):
    locate(game,'human-001','PalletTown_ProfessorOaksLab',(6,12))
    act(game,'human-001','choose_starter',{'species':'Bulbasaur'})
    s=state(game);pid='pokemon-human-001-starter'
    scenario(game,[{'op':'set','path':'humans.human-001.party','value':[]},
                   {'op':'set','path':'humans.human-002.party','value':s.humans['human-002']['party']+[pid]},
                   {'op':'set','path':f'pokemon.{pid}.owner_id','value':'human-002'}])
    return pid


def test_previously_chosen_traded_starter_cannot_be_recreated(game):
    e,_=game;pid=choose_then_transfer_fixture(game);before=state(game);mon=copy.deepcopy(before.pokemon[pid])
    assert not any(a.action=='choose_starter' for a in e.legal_actions(before,'human-001'))
    with pytest.raises(EngineError):act(game,'human-001','choose_starter',{'species':'Charmander'})
    after=state(game)
    assert after.state_hash==before.state_hash
    assert after.pokemon[pid]==mon
    assert pid in after.humans['human-002']['party']


def test_previous_starter_does_not_label_lab_journey_as_new_starter(game):
    e,_=game;choose_then_transfer_fixture(game)
    locate(game,'human-001','PalletTown',(10,10))
    actions=SimulationEngine.legal_actions(e,state(game),'human-001')
    lab=next(a for a in actions if a.action=='journey_to' and a.arguments['map_id']=='PalletTown_ProfessorOaksLab')
    assert lab.known_consequences.get('destination_kind')!='starter'
    assert 'purpose' not in lab.known_consequences


def test_never_claimed_starter_still_available_and_once_after_claim(game):
    e,_=game;locate(game,'human-001','PalletTown_ProfessorOaksLab',(6,12))
    assert len([a for a in e.legal_actions(state(game),'human-001') if a.action=='choose_starter'])==3
    scenario(game,[{'op':'set','path':'humans.human-001.pokedex','value':['EEVEE']}])
    act(game,'human-001','choose_starter',{'species':'Squirtle'})
    assert 'EEVEE' in state(game).humans['human-001']['pokedex']
    pid='pokemon-human-001-starter';s=state(game)
    scenario(game,[{'op':'set','path':'humans.human-001.party','value':[]},
                   {'op':'set','path':'humans.human-001.box','value':[pid]}])
    assert not any(a.action=='choose_starter' for a in e.legal_actions(state(game),'human-001'))
    with pytest.raises(EngineError):act(game,'human-001','choose_starter',{'species':'Bulbasaur'})
