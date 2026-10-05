import copy
import json
import random
import pytest
from living_kanto.mechanics import *
from living_kanto.mechanics.pokemon import STAT_FIELDS


def mon(species='BULBASAUR',level=5,owner='a',seed=1):
    return create_pokemon(species,level,owner,random.Random(seed))

def battle(a=None,b=None):
    return BattleSession.start([{'actor_id':'a','party':[a or mon()]},{'actor_id':'b','party':[b or mon('CHARMANDER',owner='b',seed=2)]}],[1,2,3,4])

def turn(session,first=1,second=1):
    v=session.version
    session.submit('a',{'type':'move','slot':first},expected_version=v)
    return session.submit('b',{'type':'move','slot':second},expected_version=v)

def test_reference_inventory_and_known_cartridge_data():
    d=reference_data()
    assert len(d['species'])==151
    assert d['species']['BULBASAUR']['baseHP']==45
    assert d['species']['MEWTWO']['baseSpAttack']==154
    assert d['moves']['TACKLE']['power']==35
    assert d['moves']['TACKLE']['accuracy']==95
    assert d['moves']['SCRATCH']['pp']==35
    for species in d['species']:
        assert d['learnsets'][species]
        assert all(m in d['moves'] for _,m in d['learnsets'][species])

def test_stats_rounding_and_nature():
    zero={s:0 for s in STAT_FIELDS}
    stats=calculate_stats('BULBASAUR',50,zero,zero)
    assert stats=={'hp':105,'atk':54,'def':54,'spe':50,'spa':70,'spd':70}
    assert calculate_stats('BULBASAUR',50,zero,zero,3)['atk']==59
    assert calculate_stats('BULBASAUR',50,zero,zero,3)['spa']==63
    with pytest.raises(ValueError): calculate_stats('BULBASAUR',50,{s:32 for s in STAT_FIELDS},zero)

def test_individual_creation_and_party_ownership():
    p=mon(); assert len(p['moves'])<=4
    assert p==mon()
    party=[]; transfer(p,'a','b',party)
    assert party==[p['pokemon_id']] and p['ownership_history']==['a','b']
    with pytest.raises(ValueError): transfer(p,'a','c',[])
    with pytest.raises(ValueError): transfer(p,'b','c',['x']*6)

def test_experience_and_evolution_requirements_preserve_identity():
    p=mon(level=15)
    identity=p['pokemon_id']
    assert experience_at_level('BULBASAUR',100)==1059860
    assert not evolution_options(p)
    grant_experience(p,experience_at_level('BULBASAUR',16)-p['experience'])
    assert evolution_options(p)==['IVYSAUR']
    evolve(p,'IVYSAUR')
    assert p['pokemon_id']==identity and p['level']==16
    with pytest.raises(ValueError): evolve(p,'VENUSAUR')
    assert evolution_options(mon('PIKACHU'),item='THUNDER_STONE')==['RAICHU']
    assert evolution_options(mon('KADABRA'),traded=True)==['ALAKAZAM']

def test_catching_owned_forbidden_master_ball_guaranteed_and_healing():
    p=mon('PIDGEY',owner=None)
    assert catch_attempt(p,'MASTER_BALL',random.Random(3))=={'caught':True,'shakes':4}
    p['owner_id']='a'
    with pytest.raises(ValueError): catch_attempt(p,'POKE_BALL',random.Random(3))
    p['hp']=1;p['status']='psn';p['moves'][0]['pp']=0
    heal(p)
    assert p['hp']==p['stats']['hp'] and p['status']=='' and p['moves'][0]['pp']==p['moves'][0]['max_pp']

def test_battle_turn_choices_private_and_pp_cartridge_defaults():
    s=battle()
    before=s.observation('b')
    assert before['request']['active'][0]['moves'][0]['pp']==35
    s.submit('a',{'type':'move','slot':2},expected_version=0)
    after=s.observation('b')
    assert before==after
    assert 'state' not in after and 'pending' not in after
    assert after['opponent']['active'][0]['condition'].endswith('/100')
    result=s.submit('b',{'type':'move','slot':1},expected_version=0)
    assert result['resolved'] and s.version==1
    assert next(p for p in result['pokemon'] if p['owner_id']=='a')['moves'][1]['pp']==39
    with pytest.raises(BattleError): s.submit('a',{'type':'move','slot':1},expected_version=0)

def test_pending_choice_restart_and_deterministic_resolution():
    a=battle();a.submit('a',{'type':'move','slot':1},expected_version=0)
    restored=BattleSession(json.loads(json.dumps(a.to_dict())))
    r1=a.submit('b',{'type':'move','slot':1},expected_version=0)
    r2=restored.submit('b',{'type':'move','slot':1},expected_version=0)
    assert r1==r2
    assert a.to_dict()==restored.to_dict()

def test_illegal_choice_does_not_mutate_committed_battle():
    s=battle();s.submit('a',{'type':'move','slot':1},expected_version=0)
    before=s.to_dict()
    with pytest.raises(BattleError): s.submit('b',{'type':'move','slot':4},expected_version=0)
    assert s.to_dict()==before
    s.submit('b',{'type':'move','slot':1},expected_version=0)

def test_real_battle_damage_faint_and_winner():
    a=mon('CHARMANDER',50);b=mon('CATERPIE',2,'b',2)
    a['moves']=[{'move':'EMBER','pp':25,'max_pp':25}]
    s=battle(a,b);result=turn(s)
    assert result['ended'] and result['winner']=='a'
    assert next(p for p in result['pokemon'] if p['owner_id']=='b')['hp']==0
    with pytest.raises(BattleError): s.submit('a',{'type':'move','slot':1},expected_version=1)

def test_battle_rejects_duplicate_individual_and_wrong_owner():
    p=mon()
    with pytest.raises(BattleError): BattleSession.start([{'actor_id':'a','party':[p]},{'actor_id':'b','party':[p]}],[1,2,3,4])

def test_illegal_first_choice_never_persists_and_allows_retry():
    s=battle();before=s.to_dict()
    with pytest.raises(BattleError): s.submit('a',{'type':'move','slot':4},expected_version=0)
    assert before==s.to_dict()
    assert s.submit('a',{'type':'move','slot':1},expected_version=0)['resolved'] is False
    assert s.submit('b',{'type':'move','slot':1},expected_version=0)['resolved']

def test_doubles_require_complete_healthy_teams():
    with pytest.raises(BattleError,match='Doubles'):
        BattleSession.start([{'actor_id':'a','party':[mon()]},{'actor_id':'b','party':[mon(owner='b')]}], [1,2,3,4],doubles=True)

def test_engine_item_turn_consumes_no_player_pp_and_opponent_attacks():
    s=battle();before=s.record['result']['pokemon']
    result=s.consume_trainer_turn('a',{'type':'move','slot':1},expected_version=0)
    after=result['pokemon']
    own=next(p for p in after if p['owner_id']=='a')
    foe=next(p for p in after if p['owner_id']=='b')
    assert own['moves'][0]['pp']==35
    assert foe['moves'][0]['pp']==34
    assert own['hp']<next(p for p in before if p['owner_id']=='a')['hp']

def test_personality_nature_gender_ability_and_ev_lifecycle():
    from living_kanto.mechanics.pokemon import NATURES, gender_for
    p=mon('PIDGEY',level=20)
    assert p['nature']==NATURES[p['personality']%25]
    assert p['gender']==gender_for(p['species'],p['personality'])
    identity=p['pokemon_id'];pid=p['personality'];slot=p['ability_slot']
    assert not evolution_options(p) # A high-level fresh individual has not leveled up.
    grant_experience(p,experience_at_level('PIDGEY',21)-p['experience'])
    evolve(p,'PIDGEOTTO')
    assert (p['pokemon_id'],p['personality'],p['ability_slot'])==(identity,pid,slot)
    p['held_item']='MACHO_BRACE';grant_evs(p,'BULBASAUR',pokerus=True)
    assert p['evs']['spa']==4
    p['evs']={'hp':255,'atk':254,'def':0,'spe':0,'spa':0,'spd':0}
    grant_evs(p,'BULBASAUR')
    assert sum(p['evs'].values())==510

def test_generation_three_type_immunity_and_status_resolution():
    attacker=mon('PIKACHU',30)
    attacker['moves']=[{'move':'THUNDER_SHOCK','pp':30,'max_pp':30}]
    defender=mon('ONIX',30,'b',2)
    defender['moves']=[{'move':'HARDEN','pp':30,'max_pp':30}]
    s=battle(attacker,defender);hp=defender['hp'];r=turn(s)
    assert next(p for p in r['pokemon'] if p['owner_id']=='b')['hp']==hp
    assert any('|-immune|' in line for line in s.record['result']['log'])
    attacker['moves']=[{'move':'THUNDER_WAVE','pp':20,'max_pp':20}]
    defender=mon('CHARMANDER',30,'b',2)
    defender['moves']=[{'move':'GROWL','pp':40,'max_pp':40}]
    s=battle(attacker,defender);r=turn(s)
    assert next(p for p in r['pokemon'] if p['owner_id']=='b')['status']=='par'

def test_generation_three_priority_wins_over_speed():
    slow=mon('RATTATA',10)
    slow['moves']=[{'move':'QUICK_ATTACK','pp':30,'max_pp':30}]
    fast=mon('MEWTWO',50,'b',2)
    fast['moves']=[{'move':'CONFUSION','pp':25,'max_pp':25}]
    s=battle(slow,fast);turn(s)
    moves=[line for line in s.record['result']['log'] if line.startswith('|move|')]
    assert 'Quick Attack' in moves[0]

def test_fainted_lead_requires_explicit_healthy_party_selection():
    p=mon();p['hp']=0
    with pytest.raises(BattleError,match='lead'):
        battle(p)

def test_multibranch_reference_evolution_eevee_all_kanto_stones():
    p=mon('EEVEE')
    assert evolution_options(p,item='FIRE_STONE')==['FLAREON']
    assert evolution_options(p,item='WATER_STONE')==['VAPOREON']
    assert evolution_options(p,item='THUNDER_STONE')==['JOLTEON']
    assert len(reference_data()['evolutions']['EEVEE'])==5

def test_forced_switch_waiting_opponent_needs_no_choice():
    strong=mon('CHARMANDER',80);strong['moves']=[{'move':'EMBER','pp':25,'max_pp':25}]
    weak=mon('CATERPIE',2,'b',2);reserve=mon('CATERPIE',2,'b',3)
    s=BattleSession.start([{'actor_id':'a','party':[strong]},{'actor_id':'b','party':[weak,reserve]}],[1,2,3,4])
    turn(s)
    assert s.observation('a')['request']['wait']
    assert s.observation('b')['request']['forceSwitch']==[True]
    response=s.submit('b',{'type':'switch','slot':2},expected_version=s.version)
    assert response['resolved'] and not s.ended
    assert s.observation('a')['request']['active']
