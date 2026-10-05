"""Actual simulator integration; Creative fixtures are test scenarios, never AI evidence."""
import copy
import random
from pathlib import Path

import pytest

from living_kanto.mechanics import create_pokemon
from living_kanto.simulation.world import WorldEngine
from living_kanto.store import RunStore

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def game(tmp_path):
    engine = WorldEngine(ROOT / 'content')
    store = RunStore(tmp_path / 'game.sqlite')
    engine.initialize(store, 'gameplay-test', seed=27, mode='creative')
    yield engine, store
    store.close()


def state(game):
    return game[1].load_run('gameplay-test')[1]


def scenario(game, changes):
    engine, store = game
    return engine.commit_changes(store, 'gameplay-test', changes, kind='intervention.applied', actor='test',
        explanation='Explicit Creative test scenario, not autonomous evidence', provenance={'kind':'creative','author':'test'},
        expected_version=state(game).state_version)[1]


def act(game, human, action, arguments=None):
    engine, store = game
    current = state(game)
    event, after = engine.build_action_event(store, 'gameplay-test', human, action=action, arguments=arguments or {},
        observation_version=current.state_version, expected_state_version=current.state_version,
        decision_explanation='Explicit scripted integration-test input', decision_provenance={'kind':'user','author':'test'})
    engine.commit(store, event)
    return after


def locate(game, human, map_id, position=None):
    engine, store = game
    x,y = position or engine.maps[map_id].first_open_cell((5,5))
    return scenario(game, [{'op':'set','path':f'humans.{human}.{key}','value':value}
                          for key,value in {'map_id':map_id,'x':x,'y':y}.items()])


def starter_and_encounter(game):
    locate(game,'human-001','PalletTown_ProfessorOaksLab')
    act(game,'human-001','choose_starter',{'species':'Bulbasaur'})
    engine,store=game
    grass = next((c['x'],c['y']) for c in __import__('json').loads((ROOT/'content/maps/Route1.json').read_text())['cells'] if c.get('encounter_type')==1)
    locate(game,'human-001','Route1',grass)
    return act(game,'human-001','train')


def test_starter_wild_real_turn_pp_and_replay(game):
    before=starter_and_encounter(game)
    engine,store=game
    hid='human-001';pid=before.humans[hid]['party'][0]
    battle=engine.active_battle(before,hid)
    wild_id=battle['session']['teams'][1]['party'][0]['pokemon_id']
    assert before.pokemon[wild_id]['owner_id'] is None
    assert before.pokemon[pid]['owner_id']==hid
    choice=next(a for a in engine.battle_actions(before,hid) if a.action=='battle_move')
    after=act(game,hid,choice.action,choice.arguments)
    assert after.pokemon[pid]['moves'][choice.arguments['slot']-1]['pp'] == before.pokemon[pid]['moves'][choice.arguments['slot']-1]['pp']-1
    assert after.world_facts['battles'][battle['battle_id']]['turn']==1
    assert after.pokemon[wild_id]['hp'] < before.pokemon[wild_id]['hp'] or after.pokemon[pid]['hp'] < before.pokemon[pid]['hp']
    assert store.replay('gameplay-test').state_hash==after.state_hash


def test_catch_consumes_ball_and_preserves_individual(game):
    before=starter_and_encounter(game)
    engine,store=game;hid='human-001'
    battle=engine.active_battle(before,hid);pid=battle['session']['teams'][1]['party'][0]['pokemon_id']
    balls=before.humans[hid]['inventory']['poke_ball']['quantity']
    after=act(game,hid,'catch',{'ball':'poke_ball'})
    assert after.humans[hid]['inventory']['poke_ball']['quantity']==balls-1
    record=after.world_facts['battles'][battle['battle_id']]
    if record.get('outcome')=='caught':
        assert after.pokemon[pid]['owner_id']==hid
        assert pid in after.humans[hid]['party']+after.humans[hid]['box']
        assert after.humans[hid].get('battle_id') is None
    else:
        assert record['turn']==1
        assert not record.get('catch_turn_pending')
    assert store.replay('gameplay-test').state_hash==after.state_hash


def setup_brock(game,level=100):
    engine,store=game;current=state(game)
    brock=next(h for h in current.humans.values() if h['name']=='Brock')
    mon=create_pokemon('VENUSAUR',level,'human-001',random.Random(11),identifier='pokemon-test-venusaur')
    mon['moves']=[{'move':'RAZOR_LEAF','pp':25,'max_pp':25}]
    scenario(game,[{'op':'set','path':'pokemon.pokemon-test-venusaur','value':mon},
                   {'op':'set','path':'humans.human-001.party','value':[mon['pokemon_id']]}])
    locate(game,'human-001',brock['map_id'],(brock['x'],brock['y']))
    act(game,'human-001','start_battle',{'human_id':brock['human_id']})
    return brock['human_id'],mon['pokemon_id']


def test_gym_delayed_choice_privacy_victory_and_cleanup(game):
    brock,pid=setup_brock(game);engine,store=game;hid='human-001'
    before=state(game);obs=engine.observation_for(before,brock).revealed_battle_info
    assert before.humans[hid]['badges']==[]
    first=act(game,hid,'battle_move',{'slot':1})
    after_obs=engine.observation_for(first,brock).revealed_battle_info
    assert after_obs==obs
    assert not engine.battle_actions(first,hid)
    assert first.simulated_time==before.simulated_time
    assert first.pokemon[pid]['moves'][0]['pp']==25
    assert first.humans[hid]['badges']==[]
    for _ in range(12):
        current=state(game)
        for actor in (brock,hid):
            options=engine.battle_actions(current,actor)
            if options:
                choice=next((a for a in options if a.action=='battle_move'),options[0])
                current=act(game,actor,choice.action,choice.arguments)
            if current.humans[hid].get('battle_id') is None:break
        if current.humans[hid].get('battle_id') is None:break
    final=state(game)
    assert 'boulder' in final.humans[hid]['badges']
    assert final.humans[brock]['badges']==[]
    assert final.humans[hid].get('battle_id') is None
    assert final.humans[brock].get('battle_id') is None
    assert final.pokemon[pid]['experience']>=before.pokemon[pid]['experience']
    assert store.replay('gameplay-test').state_hash==final.state_hash

def test_failed_throw_advances_real_opponent_turn(game, monkeypatch):
    before=starter_and_encounter(game)
    engine,store=game;hid='human-001'
    battle=engine.active_battle(before,hid);pid=battle['session']['teams'][1]['party'][0]['pokemon_id']
    # Fix catch randomness only; the actual opponent response still uses Gen III simulator.
    monkeypatch.setattr('living_kanto.simulation.gameplay.catch_attempt',lambda *args,**kwargs:{'caught':False,'shakes':0})
    after=act(game,hid,'catch',{'ball':'poke_ball'})
    record=after.world_facts['battles'][battle['battle_id']]
    assert record['turn']==1
    assert not record.get('catch_turn_pending')
    assert sum(m['pp'] for m in after.pokemon[pid]['moves'])==sum(m['pp'] for m in before.pokemon[pid]['moves'])-1
    assert store.replay('gameplay-test').state_hash==after.state_hash


def test_official_challenge_starts_with_fresh_health(game):
    engine,store=game;current=state(game)
    brock=next(h for h in current.humans.values() if h['name']=='Brock')
    changes=[]
    for pid in brock['official_challenge_team']:
        changes.append({'op':'set','path':f'pokemon.{pid}.hp','value':0})
    scenario(game,changes)
    setup_brock(game)
    battle=engine.active_battle(state(game),'human-001')
    official=battle['session']['teams'][1]['party']
    assert all(mon['hp']==mon['stats']['hp'] for mon in official)
    assert all(all(move['pp']==move['max_pp'] for move in mon['moves']) for mon in official)

def test_each_knockout_rewarded_once_before_battle_end(game):
    # Source Gen3 does not award XP or EVs at level100.
    brock,pid=setup_brock(game,level=80);engine,store=game
    act(game,'human-001','battle_move',{'slot':1})
    defender=next(a for a in engine.battle_actions(state(game),brock) if a.action=='battle_move')
    after=act(game,brock,defender.action,defender.arguments)
    record=engine.active_battle(after,'human-001')
    assert record and not record.get('ended')
    assert len(record.get('rewarded_defeats',[]))==1
    assert sum(after.pokemon[pid]['evs'].values())>0
    assert after.humans['human-001']['badges']==[]
    evs=copy.deepcopy(after.pokemon[pid]['evs'])
    forced=next(a for a in engine.battle_actions(after,brock) if a.action=='battle_switch')
    switched=act(game,brock,forced.action,forced.arguments)
    assert switched.pokemon[pid]['evs']==evs
    assert store.replay('gameplay-test').state_hash==switched.state_hash

def test_later_champion_defense_uses_recorded_eligible_team(game):
    engine,store=game;champion='human-001';challenger='human-002'
    saved=create_pokemon('VENUSAUR',50,champion,random.Random(12),identifier='pokemon-new-champion')
    contender=create_pokemon('CHARIZARD',50,challenger,random.Random(13),identifier='pokemon-new-contender')
    scenario(game,[{'op':'set','path':f'pokemon.{saved["pokemon_id"]}','value':saved},
                   {'op':'set','path':f'pokemon.{contender["pokemon_id"]}','value':contender},
                   {'op':'set','path':f'humans.{champion}.party','value':[saved['pokemon_id']]},
                   {'op':'set','path':f'humans.{challenger}.party','value':[contender['pokemon_id']]},
                   {'op':'set','path':f'humans.{challenger}.league','value':{'active':True,'stage':4,'battle_ids':['test-e4-1','test-e4-2','test-e4-3','test-e4-4']}},
                   {'op':'set','path':'world_facts.championship.current_champion','value':champion},
                   {'op':'set','path':'world_facts.championship.challenge_team','value':[saved]}])
    current=state(game)
    assert not current.humans[champion].get('official_challenge_team')
    champion_h=current.humans[champion]
    locate(game,challenger,champion_h['map_id'],(champion_h['x'],champion_h['y']))
    after=act(game,challenger,'start_battle',{'human_id':champion})
    record=engine.active_battle(after,challenger)
    assert record['session']['challenge']=={'kind':'league','opponent':'Champion'}
    assert record['session']['teams'][1]['party'][0]['pokemon_id']==saved['pokemon_id']
    assert engine.observation_for(after,champion).self_state['challenge_team_active']
    bid=record['battle_id']
    for _ in range(30):
        for actor in (challenger,champion):
            choices=engine.battle_actions(state(game),actor)
            if choices:
                moves=[a for a in choices if a.action=='battle_move']
                choice=max(moves,key=lambda a: a.known_consequences.get('move')=='Flamethrower') if moves else choices[0]
                act(game,actor,choice.action,choice.arguments)
            if not state(game).humans[challenger].get('battle_id'):break
        if not state(game).humans[challenger].get('battle_id'):break
    final=state(game);title=final.world_facts['championship']
    assert title['current_champion']==challenger
    assert title['tenures'][-1]['defeated_champion']==champion
    assert title['tenures'][-1]['battle_id']==bid
    assert title['hall_of_fame'][-1]['battle_ids'][-1]==bid
    assert title['challenge_team'][0]['pokemon_id']==contender['pokemon_id']
    assert not final.humans[challenger]['league']['active']
    assert final.humans[champion]['battle_id'] is None
    assert store.replay('gameplay-test').state_hash==final.state_hash

@pytest.mark.parametrize('checkpoint',[False,True])
def test_actual_official_loss_heals_respawns_and_replays(game,checkpoint):
    engine,store=game;hid='human-001'
    locate(game,hid,'PalletTown_ProfessorOaksLab')
    act(game,hid,'choose_starter',{'species':'Bulbasaur'})
    pid=state(game).humans[hid]['party'][0]
    station=None
    if checkpoint:
        mid='ViridianCity_PokemonCenter_1F';locate(game,hid,mid)
        act(game,hid,'heal_party')
        staff=next(h['human_id'] for h in state(game).humans.values() if h['role']=='service_staff' and h['map_id']==mid)
        offer=engine.service_actions(state(game),staff)[0]
        act(game,staff,offer.action,offer.arguments)
        station=state(game).humans[hid]['last_heal_station']
        # Shopping later must not overwrite the healing checkpoint.
        locate(game,hid,'ViridianCity_Mart');act(game,hid,'shop_buy',{'item':'potion','quantity':1})
        shop=next(h['human_id'] for h in state(game).humans.values() if h.get('service_assignment',{}).get('kind')=='shop' and h['map_id']=='ViridianCity_Mart')
        offer=engine.service_actions(state(game),shop)[0];act(game,shop,offer.action,offer.arguments)
        assert state(game).humans[hid]['last_heal_station']==station
    brock=next(h for h in state(game).humans.values() if h['name']=='Brock')
    locate(game,hid,brock['map_id'],(brock['x'],brock['y']))
    act(game,hid,'start_battle',{'human_id':brock['human_id']})
    before=state(game);bid=before.humans[hid]['battle_id'];money=before.humans[hid]['money']
    for _ in range(50):
        current=state(game)
        if not current.humans[hid].get('battle_id'):break
        for actor in (hid,brock['human_id']):
            choices=engine.battle_actions(state(game),actor)
            if choices:
                # Deliberately losing fixture: trainer chooses Growl,
                # source Brock chooses the offered damaging Tackle move.
                move=next(a for a in choices if a.action=='battle_move' and a.arguments['slot']==(2 if actor==hid else 1))
                act(game,actor,move.action,move.arguments)
    after=state(game);battle=after.world_facts['battles'][bid]
    assert battle['ended'] and battle['outcome']==brock['human_id']
    assert after.humans[hid]['battle_id'] is None and after.humans[brock['human_id']]['battle_id'] is None
    assert not after.humans[hid]['badges']
    assert after.humans[hid]['money']==money-battle['whiteout_money_loss']
    expected='ViridianCity_PokemonCenter_1F' if checkpoint else 'PalletTown_PlayersHouse_1F'
    assert after.humans[hid]['map_id']==expected
    assert (after.humans[hid]['x'],after.humans[hid]['y'])==((7,4) if checkpoint else (8,5))
    mon=after.pokemon[pid]
    assert mon['hp']==mon['stats']['hp'] and mon['status']==''
    assert all(m['pp']==m['max_pp'] for m in mon['moves'])
    assert after.humans[hid]['last_whiteout']['checkpoint_request_id']==(station['request_id'] if checkpoint else None)
    assert store.replay('gameplay-test').state_hash==after.state_hash


def test_world_source_turn_then_statue_toggle_no_movement(game):
    engine,store=game;hid='human-001'
    statue=engine.maps['PokemonMansion_1F'].events['mansion_switch']['statues'][0]
    locate(game,hid,'PokemonMansion_1F',(statue['x'],statue['y']+1))
    # Position is explicit Creative setup; both interactions are production actions.
    scenario(game,[{'op':'set','path':f'humans.{hid}.facing','value':'south'}])
    before=state(game);turned=act(game,hid,'turn_to',{'direction':'north'})
    assert turned.simulated_time==before.simulated_time+1
    assert (turned.humans[hid]['x'],turned.humans[hid]['y'])==(before.humans[hid]['x'],before.humans[hid]['y'])
    assert turned.humans[hid]['facing']=='north'
    switched=act(game,hid,'toggle_mansion_switch',{})
    assert switched.humans[hid]['field']['mansion_switch'] is True
    assert store.replay('gameplay-test').state_hash==switched.state_hash


def test_source_pc_storage_requires_physical_facing_and_legal_turn(game):
    engine,store=game;hid='human-001';mid='ViridianCity_PokemonCenter_1F';gm=engine.maps[mid]
    px,py=next((x,y) for (x,y),cell in gm.cells.items() if cell.get('behavior')==0x83 and gm.is_walkable(x,y+1))
    locate(game,hid,mid,(px,py+1))
    mon=create_pokemon('PIDGEY',5,hid,random.Random(7),identifier='pokemon-pc-facing-test')
    scenario(game,[{'op':'set','path':f'pokemon.{mon["pokemon_id"]}','value':mon},
        {'op':'set','path':f'humans.{hid}.box','value':[mon['pokemon_id']]},
        {'op':'set','path':f'humans.{hid}.facing','value':'south'}])
    assert not any(a.action=='store_withdraw' for a in engine.legal_actions(state(game),hid))
    act(game,hid,'turn_to',{'direction':'north'})
    assert any(a.action=='store_withdraw' for a in engine.legal_actions(state(game),hid))
    after=act(game,hid,'store_withdraw',{'pokemon_id':mon['pokemon_id']})
    assert after.humans[hid]['party']==[mon['pokemon_id']] and not after.humans[hid]['box']
    assert store.replay('gameplay-test').state_hash==after.state_hash
