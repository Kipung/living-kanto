import copy,random
from living_kanto.mechanics import BattleSession,create_pokemon
from living_kanto.mechanics.battle import _invoke

def teams(traded=False,badges=()):
    a=create_pokemon('RATTATA',100,'a',random.Random(1),identifier='pokemon-cartridge-a')
    b=create_pokemon('RATTATA',100,'b',random.Random(2),identifier='pokemon-cartridge-b')
    a['moves']=[{'move':'TAIL_WHIP','pp':30,'max_pp':30}];b['moves']=[{'move':'GROWL','pp':40,'max_pp':40}]
    if traded:a['ownership_history']=['original-trainer','a'];a['original_trainer_id']='original-trainer'
    return [{'actor_id':'a','party':[a],'badge_ids':list(badges)},{'actor_id':'b','party':[b]}]

def test_source_badge_base_damage_stats_speed_and_link_exceptions():
    t=teams(badges=['boulder','soul','volcano','thunder']);session=BattleSession.start(t,[1,2,3,4])
    context=_invoke({'operation':'cartridge_context','state':session.record['result']['state'],'actor_id':'a'})[0]
    stats=t[0]['party'][0]['stats']
    assert context['stats']=={k:stats[k]*110//100 for k in ('atk','def','spa','spd')}
    assert context['speed']==stats['spe']*110//100
    restored=BattleSession(session.to_dict());assert restored.record['result']['state']==session.record['result']['state']
    linked=BattleSession.start(t,[1,2,3,4],challenge={'kind':'personal'})
    context=_invoke({'operation':'cartridge_context','state':linked.record['result']['state'],'actor_id':'a'})[0]
    assert context['stats']=={k:stats[k] for k in ('atk','def','spa','spd')} and context['speed']==stats['spe']

def turn(session):
    session.submit('a',{'type':'move','slot':1},expected_version=session.version)
    return session.submit('b',{'type':'move','slot':1},expected_version=session.version)

def test_source_trade_obedience_canonical_result_replay_and_earth_exemption():
    t=teams(True);s=BattleSession.start(t,[1,2,3,4]);r=BattleSession(s.to_dict())
    turn(s);turn(r)
    events=s.record['result']['state']['cartridge']['events']
    assert events and events[0]['pokemon_id']=='pokemon-cartridge-a'
    assert s.record['result']['state']==r.record['result']['state']
    own=BattleSession.start(teams(False),[1,2,3,4]);turn(own)
    assert own.record['result']['state']['cartridge']['events']==[]
    earth=BattleSession.start(teams(True,['earth']),[1,2,3,4]);turn(earth)
    assert earth.record['result']['state']['cartridge']['events']==[]
    link=BattleSession.start(t,[1,2,3,4],challenge={'kind':'personal'});turn(link)
    assert link.record['result']['state']['cartridge']['events']==[]

def test_boulder_badge_changes_actual_damage_and_original_trainer_tradeback():
    t=teams();t[0]['party'][0]['moves']=[{'move':'TACKLE','pp':35,'max_pp':35}]
    plain=BattleSession.start(t,[1,2,3,4]);boosted=copy.deepcopy(t);boosted[0]['badge_ids']=['boulder']
    badge=BattleSession.start(boosted,[1,2,3,4]);turn(plain);turn(badge)
    hp=lambda s:next(p['hp'] for p in s.record['result']['pokemon'] if p['owner_id']=='b')
    assert hp(badge)<hp(plain)
    own=teams();own[0]['party'][0]['ownership_history']=['a','someone-else','a']
    original=BattleSession.start(own,[1,2,3,4]);turn(original)
    assert original.record['result']['state']['cartridge']['events']==[]
