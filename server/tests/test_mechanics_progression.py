import random
import pytest
from living_kanto.mechanics import create_pokemon, BattleSession
from living_kanto.mechanics.progression import *


def completed(winner='a',opponent='leader',battle_id='one',challenge=None):
    strong=create_pokemon('CHARMANDER',100,winner,random.Random(1))
    strong['moves']=[{'move':'EMBER','pp':25,'max_pp':25}]
    weak=create_pokemon('CATERPIE',2,opponent if winner=='a' else 'a',random.Random(2))
    s=BattleSession.start([{'actor_id':strong['owner_id'],'party':[strong]},{'actor_id':weak['owner_id'],'party':[weak]}],[1,2,3,4],battle_id=battle_id,challenge=challenge or {'kind':'gym','gym':'Brock'})
    s.submit(strong['owner_id'],{'type':'move','slot':1},expected_version=0)
    s.submit(weak['owner_id'],{'type':'move','slot':1},expected_version=0)
    assert s.ended
    return s

def test_reference_teams_first_challenge_moves_and_iv_conversion():
    brock=official_team('Brock','brock',random.Random(1))
    assert [(p['species'],p['level']) for p in brock]==[('GEODUDE',12),('ONIX',14)]
    assert brock[1]['moves'][2]['move']=='ROCK_TOMB'
    assert brock[0]['ivs']['hp']==0 and brock[0]['nature']=='Jolly'
    lorelei=official_team('Lorelei','lorelei',random.Random(1))
    assert len(lorelei)==5 and lorelei[0]['ivs']['hp']==30
    for role in [*GYMS,*LEAGUE]:
        team=official_team(role,role,random.Random(1))
        assert 1<=len(team)<=6
        assert all(1<=len(p['moves'])<=4 and p['owner_id']==role and p['official_challenge_team'] for p in team)

def test_badges_require_real_win_and_are_individual_and_idempotent():
    trainer={'human_id':'a','badges':[]};other={'human_id':'b','badges':[]}
    battle=completed()
    assert award_gym_badge(trainer,'Brock',battle,'leader')['badge']=='boulder'
    assert other['badges']==[]
    with pytest.raises(ValueError): award_gym_badge(trainer,'Misty',battle,'leader')
    with pytest.raises(ValueError): award_gym_badge(other,'Brock',battle,'leader')
    loser={'human_id':'a','badges':[]}
    with pytest.raises(ValueError): award_gym_badge(loser,'Brock',completed('leader',battle_id='loss'),'leader')
    assert loser['badges']==[]

def test_league_eight_badges_and_loss_reset():
    trainer={'human_id':'a','badges':[]}
    with pytest.raises(ValueError): begin_league(trainer)
    trainer['badges']=list(GYMS.values());begin_league(trainer)
    title={'current_champion':'incumbent'}
    record_league_result(trainer,completed(opponent='lorelei',challenge={'kind':'league','opponent':'Lorelei'}),'lorelei',title)
    assert next_league_opponent(trainer)=='Bruno'
    event=record_league_result(trainer,completed('bruno',battle_id='loss',challenge={'kind':'league','opponent':'Bruno'}),'bruno',title)
    assert event['type']=='league_attempt_failed' and not trainer['league']['active']
    begin_league(trainer);assert next_league_opponent(trainer)=='Lorelei'
    assert title['current_champion']=='incumbent'

def test_title_succession_records_team_and_all_five_real_victories():
    trainer={'human_id':'a','badges':list(GYMS.values())}
    title={'current_champion':'incumbent','hall_of_fame':[],'tenures':[]}
    begin_league(trainer)
    team=[create_pokemon('CHARMANDER',100,'a',random.Random(1))]
    for index,role in enumerate(LEAGUE):
        opponent='incumbent' if role=='Champion' else role.lower()
        event=record_league_result(trainer,completed(opponent=opponent,battle_id=f'stage-{index}',challenge={'kind':'league','opponent':role}),opponent,title,eligible_team=team)
    assert event['type']=='champion_succeeded'
    assert title['current_champion']=='a' and len(title['hall_of_fame'][0]['battle_ids'])==5
    assert title['challenge_team']==team and not trainer['league']['active']

def test_source_official_money_class_and_last_original_party_level():
    from living_kanto.mechanics.progression import official_prize
    assert official_prize('Brock',14)==1400
    assert official_prize('Lorelei',54)==5400
    assert official_prize('Champion',63)==6300
    assert official_prize('Brock',14,doubles=True,amulet_coin=True)==5600

def test_source_whiteout_badge_level_money_cap():
    from living_kanto.mechanics.progression import whiteout_loss,GYMS
    h={'money':3000,'badges':[]};party=[{'level':5},{'level':20}]
    assert whiteout_loss(h,party)==160
    h['badges']=list(GYMS.values());assert whiteout_loss(h,party)==2400
    h['money']=10;assert whiteout_loss(h,party)==10
