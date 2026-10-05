"""Source-backed challenge teams and per-trainer progression.

Only engine-owned completed BattleSession objects can award progress. The caller
must bind the supplied opponent ID to the requested official challenge service.
"""
import copy
from functools import lru_cache
import re
from .battle import BattleSession
from .pokemon import create_pokemon, calculate_stats, NATURES, gender_for
from .reference import REFERENCE, data

GYMS = {'Brock':'boulder','Misty':'cascade','LtSurge':'thunder','Erika':'rainbow','Koga':'soul','Sabrina':'marsh','Blaine':'volcano','Giovanni':'earth'}
LEAGUE = ('Lorelei','Bruno','Agatha','Lance','Champion')

@lru_cache(maxsize=1)
def official_templates():
    parties=(REFERENCE/'src/data/trainer_parties.h').read_text()
    trainers=(REFERENCE/'src/data/trainers.h').read_text()
    species_names=dict(re.findall(r'\[SPECIES_(\w+)\]\s*=\s*_\("([^\"]+)"\)',(REFERENCE/'src/data/text/species_names.h').read_text()))
    charmap={c:int(v,16) for c,v in re.findall(r"^'(.+)'\s*=\s*([A-F0-9]{2})$",(REFERENCE/'charmap.txt').read_text(),re.M)}
    roles={'Miguel':'SuperNerdMiguel','Koichi':'BlackBeltKoichi',**{name:'Leader'+name for name in GYMS},**{name:'EliteFour'+name for name in LEAGUE[:-1]},**{'Champion'+v:'ChampionFirst'+v for v in ('Squirtle','Bulbasaur','Charmander')}}
    result={}
    for role,party_name in roles.items():
        match=re.search(r'\bsParty_'+party_name+r'\[\] = \{(.*?)\n\};',parties,re.S)
        if not match: raise RuntimeError(f'Reference team missing {role}')
        config=re.search(r'\[TRAINER_\w+\]\s*=\s*\{([^}]*?\.party\s*=\s*\w+\(sParty_'+party_name+r'\).*?)\n    \}',trainers,re.S)
        # items contain braces, so delimit trainer records before finding the relevant one.
        configs=re.findall(r'\[TRAINER_\w+\]\s*=\s*\{(.*?)\n    \}',trainers,re.S)
        config=next(c for c in configs if '('+'sParty_'+party_name+')' in c)
        trainer_name=re.search(r'\.trainerName\s*=\s*_\("([^\"]+)"\)',config).group(1)
        female='F_TRAINER_FEMALE' in config
        name_hash=0
        rows=[]
        for body in re.findall(r'\{(.*?)\}',match.group(1),re.S):
            # Move braces occur inside mon braces; this expression intentionally ends at moves close.
            species=re.search(r'\.species\s*=\s*SPECIES_(\w+)',body)
            if not species: continue
            species=species.group(1)
            level=int(re.search(r'\.lvl\s*=\s*(\d+)',body).group(1))
            iv=int(re.search(r'\.iv\s*=\s*(\d+)',body).group(1))*31//255
            moves=[m for m in re.findall(r'MOVE_(\w+)',body) if m!='NONE']
            item=re.search(r'\.heldItem\s*=\s*ITEM_(\w+)',body)
            name_hash+=sum(charmap[c] for c in trainer_name)+sum(charmap[c] for c in species_names[species])
            personality=(0x78 if female else 0x88)+(name_hash<<8)
            rows.append({'species':species,'level':level,'iv':iv,'moves':moves,'item':item.group(1) if item else 'NONE','personality':personality,'nature':NATURES[personality%25]})
        result[role]=rows
    return result

def official_team(role, owner_id, rng, *, champion_variant='Squirtle'):
    if role=='Champion': role+=''+champion_variant
    templates=official_templates()[role]
    team=[]
    for slot,row in enumerate(templates):
        p=create_pokemon(row['species'],row['level'],owner_id,rng,identifier=f'official-{owner_id}-{role.lower()}-{slot}')
        p['ivs']={s:row['iv'] for s in p['ivs']}
        p['nature']=row['nature'];p['personality']=row['personality']
        p['gender']=gender_for(p['species'],p['personality'])
        abilities=data()['species'][p['species']]['abilities']
        p['ability_slot']=(p['personality']&1) if abilities[1]!='NONE' else 0
        p['ability']=abilities[p['ability_slot']]
        p['stats']=calculate_stats(p['species'],p['level'],p['ivs'],p['evs'],row['personality']%25)
        p['hp']=p['stats']['hp'];p['held_item']='' if row['item']=='NONE' else row['item']
        if row['moves']:p['moves']=[{'move':m,'pp':data()['moves'][m]['pp'],'max_pp':data()['moves'][m]['pp']} for m in row['moves']]
        p['official_challenge_team']=True
        team.append(p)
    return team

def _validate_result(trainer, battle, opponent_id):
    if not isinstance(battle,BattleSession) or not battle.ended: raise ValueError('Completed authoritative battle required')
    participants={t['actor_id'] for t in battle.record['teams']}
    trainer_id=trainer.get('human_id',trainer.get('actor_id',trainer.get('id')))
    if participants!={trainer_id,opponent_id}: raise ValueError('Challenge participants mismatch')
    battle_id=battle.record['battle_id']
    if battle_id in trainer.get('progression_battles',[]): raise ValueError('Battle already consumed for progression')
    return trainer_id,battle_id

def award_gym_badge(trainer, gym, battle, leader_id):
    if gym not in GYMS: raise ValueError('Unknown gym')
    trainer_id,battle_id=_validate_result(trainer,battle,leader_id)
    if battle.record.get('challenge')!={'kind':'gym','gym':gym}: raise ValueError('Battle is not the requested official gym challenge')
    if battle.winner!=trainer_id: raise ValueError('Gym victory required')
    badge=GYMS[gym]
    if badge in trainer.get('badges',[]): raise ValueError('Badge already earned')
    trainer.setdefault('badges',[]).append(badge)
    trainer.setdefault('progression_battles',[]).append(battle_id)
    return {'type':'badge_earned','actor_id':trainer_id,'gym':gym,'badge':badge,'battle_id':battle_id}

def begin_league(trainer):
    if not set(GYMS.values()).issubset(trainer.get('badges',[])): raise ValueError('Eight badges required')
    if trainer.get('league',{}).get('active'): raise ValueError('League attempt already active')
    trainer['league']={'active':True,'stage':0,'battle_ids':[]}
    return copy.deepcopy(trainer['league'])

def next_league_opponent(trainer):
    league=trainer.get('league',{})
    if not league.get('active'): raise ValueError('No active league attempt')
    return LEAGUE[league['stage']]

def record_league_result(trainer,battle,opponent_id,championship,*,eligible_team=None):
    trainer_id,battle_id=_validate_result(trainer,battle,opponent_id)
    expected=next_league_opponent(trainer)
    if battle.record.get('challenge')!={'kind':'league','opponent':expected}: raise ValueError('Battle is not the required official league challenge')
    if expected=='Champion' and championship['current_champion']!=opponent_id: raise ValueError('Current champion must be challenged')
    if battle.winner!=trainer_id:
        trainer['league']={'active':False,'stage':0,'battle_ids':[],'failed_battle_id':battle_id}
        trainer.setdefault('progression_battles',[]).append(battle_id)
        return {'type':'league_attempt_failed','actor_id':trainer_id,'opponent':expected,'battle_id':battle_id}
    if expected=='Champion':
        if not eligible_team or len(eligible_team)>6 or any(p['owner_id']!=trainer_id for p in eligible_team): raise ValueError('Eligible owned championship team required')
        if len({p['pokemon_id'] for p in eligible_team})!=len(eligible_team): raise ValueError('Duplicate championship individual')
    trainer.setdefault('progression_battles',[]).append(battle_id)
    trainer['league']['battle_ids'].append(battle_id)
    if expected!='Champion':
        trainer['league']['stage']+=1
        return {'type':'league_stage_won','actor_id':trainer_id,'opponent':expected,'battle_id':battle_id,'next_opponent':next_league_opponent(trainer)}
    previous=championship['current_champion']
    entry={'champion_id':trainer_id,'previous_champion':previous,'battle_ids':copy.deepcopy(trainer['league']['battle_ids']),'team':copy.deepcopy(eligible_team)}
    championship.setdefault('hall_of_fame',[]).append(entry)
    championship.setdefault('tenures',[]).append({'champion_id':trainer_id,'defeated_champion':previous,'battle_id':battle_id})
    championship['current_champion']=trainer_id
    championship['challenge_team']=copy.deepcopy(eligible_team)
    trainer['league']['active']=False
    return {'type':'champion_succeeded','actor_id':trainer_id,'previous_champion':previous,'battle_id':battle_id}

@lru_cache(maxsize=1)
def official_money_classes():
    """Pinned gTrainerMoneyTable and exact official trainer record classes."""
    text=(REFERENCE/'src/battle_main.c').read_text()
    table=re.search(r'gTrainerMoneyTable\[\]\s*=\s*\{(.*?)\n\};',text,re.S).group(1)
    values={name:int(value) for name,value in re.findall(r'\{TRAINER_CLASS_(\w+),\s*(\d+)\}',table)}
    trainers=(REFERENCE/'src/data/trainers.h').read_text()
    result={}
    for config in re.findall(r'\[TRAINER_\w+\]\s*=\s*\{(.*?)\n    \}',trainers,re.S):
        party=re.search(r'sParty_(Leader\w+|EliteFour\w+|ChampionFirst\w+|BlackBeltKoichi|SuperNerdMiguel)',config)
        if not party:continue
        cls=re.search(r'\.trainerClass\s*=\s*TRAINER_CLASS_(\w+)',config).group(1)
        role=party.group(1).removeprefix('Leader').removeprefix('EliteFour').replace('ChampionFirst','Champion')
        if role=='BlackBeltKoichi':role='Koichi'
        if role=='SuperNerdMiguel':role='Miguel'
        result[role]=values[cls]
    return result

def official_prize(role,last_mon_level,*,doubles=False,amulet_coin=False):
    """Cmd_getmoneyreward: four times original last party level and class value."""
    if role=='Champion':role='ChampionSquirtle' # all source first-champion variants share class.
    if type(last_mon_level) is not int or not 1<=last_mon_level<=100:raise ValueError('Invalid prize level')
    return 4*last_mon_level*official_money_classes()[role]*(2 if doubles else 1)*(2 if amulet_coin else 1)

def whiteout_loss(trainer,party):
    """overworld.c ComputeWhiteOutMoneyLoss, source badge multiplier table."""
    source=(REFERENCE/'src/overworld.c').read_text()
    values=[int(v) for v in re.findall(r'\d+',re.search(r'sWhiteOutMoneyLossMultipliers\[\]\s*=\s*\{(.*?)\};',source,re.S).group(1))]
    badges=len(set(trainer.get('badges',[])).intersection(GYMS.values()))
    return min(trainer['money'],max((p['level'] for p in party),default=0)*4*values[badges])
