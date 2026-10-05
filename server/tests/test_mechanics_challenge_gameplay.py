"""Explicit Creative setup; accepted personal duels use actual simulator turns."""
import random
import pytest
from test_gameplay import game,act,locate,scenario,state
from living_kanto.mechanics import create_pokemon
from living_kanto.simulation.engine import EngineError


def setup(game,doubles=True):
    changes=[]
    for hid,species,level in [('human-001','BLASTOISE',60),('human-002','CHARMANDER',5)]:
        ids=[]
        for index in range(2 if doubles else 1):
            p=create_pokemon(species,level,hid,random.Random(index),identifier=f'pokemon-duel-{hid}-{index}')
            p['moves']=[{'move':'SURF' if hid=='human-001' else 'SCRATCH','pp':15 if hid=='human-001' else 35,'max_pp':15 if hid=='human-001' else 35}]
            changes.append({'op':'set','path':f'pokemon.{p["pokemon_id"]}','value':p});ids.append(p['pokemon_id'])
        changes.append({'op':'set','path':f'humans.{hid}.party','value':ids})
    scenario(game,changes)
    locate(game,'human-001','PalletTown',(10,10));locate(game,'human-002','PalletTown',(11,10))
    return act(game,'human-001','challenge_trainer',{'human_id':'human-002','doubles':doubles})

def test_personal_challenge_requires_acceptance_and_real_owned_parties(game):
    proposed=setup(game,False)
    assert not proposed.humans['human-001'].get('battle_id')
    cid=next(iter(proposed.world_facts['trainer_challenges']))
    accepted=act(game,'human-002','accept_challenge',{'challenge_id':cid})
    record=game[0].active_battle(accepted,'human-001')
    assert record['personal_duel'] and not record['session']['doubles']
    assert record['session']['teams'][1]['party'][0]['pokemon_id']==accepted.humans['human-002']['party'][0]
    assert record['session']['challenge']['economy']=='source-link-like-no-rewards'
    assert game[1].replay('gameplay-test').state_hash==accepted.state_hash

def test_double_private_choices_real_result_no_exp_money_or_blackout(game):
    proposed=setup(game);cid=next(iter(proposed.world_facts['trainer_challenges']))
    accepted=act(game,'human-002','accept_challenge',{'challenge_id':cid})
    engine,store=game;before={h:accepted.humans[h]['money'] for h in ('human-001','human-002')}
    exp={pid:accepted.pokemon[pid]['experience'] for h in before for pid in accepted.humans[h]['party']}
    a=engine.battle_actions(accepted,'human-001')[0]
    assert a.action=='battle_turn' and len(a.known_consequences['active_slot_options'])==2
    first=act(game,'human-001','battle_turn',a.arguments)
    assert first.clock==accepted.clock
    b=engine.battle_actions(first,'human-002')[0]
    after=act(game,'human-002','battle_turn',b.arguments)
    assert not after.humans['human-001']['battle_id'] and not after.humans['human-002']['battle_id']
    assert all(after.pokemon[pid]['experience']==value for pid,value in exp.items())
    assert all(after.humans[hid]['money']==money for hid,money in before.items())
    assert all(after.pokemon[pid]['hp']==0 for pid in after.humans['human-002']['party'])
    assert store.replay('gameplay-test').state_hash==after.state_hash

def test_invalid_double_choice_does_not_store_pending_and_offer_stales_safely(game):
    proposed=setup(game);cid=next(iter(proposed.world_facts['trainer_challenges']))
    accepted=act(game,'human-002','accept_challenge',{'challenge_id':cid})
    with pytest.raises((EngineError,ValueError)):
        act(game,'human-001','battle_turn',{'choices':[{'type':'move','slot':4,'target':1},{'type':'move','slot':1,'target':2}]})
    assert state(game).state_hash==accepted.state_hash
