"""FireRed Safari admission, counters, bait/rock/catch and flee.

The wild flee intent is sampled using the pre-turn counters, as in source
battle_ai_script_commands.c; human action executes first (battle_main.c3537).
"""
import copy
import math
from .reference import data


def enter_safari(trainer):
    if trainer.get('safari',{}).get('active'):raise ValueError('Safari visit already active')
    if trainer.get('battle_id') or trainer['money']<500:raise ValueError('Safari requires 500 and no active battle')
    trainer=copy.deepcopy(trainer);trainer['money']-=500
    trainer['safari']={'active':True,'balls':30,'steps':600,'encounter':None}
    return trainer

def take_steps(trainer,steps):
    if type(steps) is not int or steps<0:raise ValueError('Invalid walked step count')
    trainer=copy.deepcopy(trainer)
    safari=trainer.get('safari',{})
    if safari.get('active'):
        safari['steps']=max(0,safari['steps']-steps)
        if not safari['steps']:safari['active']=False;safari['encounter']=None;safari['end_reason']='steps_exhausted'
    return trainer

def start_safari_encounter(trainer,pokemon):
    trainer=copy.deepcopy(trainer);safari=trainer.get('safari',{})
    if not safari.get('active') or safari['balls']<=0 or safari.get('encounter'):raise ValueError('Safari encounter unavailable')
    if pokemon['owner_id'] is not None:raise ValueError('Safari Pokémon already owned')
    row=data()['species'][pokemon['species']]
    safari['encounter']={'pokemon_id':pokemon['pokemon_id'],'catch_factor':row['catchRate']*100//1275,'escape_factor':max(2,row['safariZoneFleeRate']*100//1275),'bait':0,'rock':0,'turn':0}
    return trainer

def safari_turn(trainer,pokemon,action,rng):
    trainer=copy.deepcopy(trainer);pokemon=copy.deepcopy(pokemon)
    safari=trainer.get('safari',{});encounter=safari.get('encounter')
    if not safari.get('active') or not encounter or encounter['pokemon_id']!=pokemon['pokemon_id'] or pokemon['owner_id'] is not None:raise ValueError('Safari encounter unavailable')
    if action not in ('ball','bait','rock','run'):raise ValueError('Illegal Safari action')
    if action=='ball' and safari['balls']<=0:raise ValueError('No Safari balls')
    if action=='ball' and len(trainer['party'])>=6 and len(trainer['box'])>=420:raise ValueError('Party and source storage are full')
    factor=encounter['escape_factor']
    if encounter['rock']:factor=min(20,factor*2)
    elif encounter['bait']:factor=max(1,factor//4)
    # This decision precedes changes from throwing this turn's bait or rock.
    flee=rng.randrange(100)<factor*5
    result={'action':action,'caught':False,'ended':False,'wild_fled':False}
    if action=='run':result.update({'ended':True,'outcome':'ran'})
    elif action=='bait':
        encounter['bait']=min(6,encounter['bait']+rng.randrange(5)+2);encounter['rock']=0
        encounter['catch_factor']=max(3,encounter['catch_factor']//2)
    elif action=='rock':
        encounter['rock']=min(6,encounter['rock']+rng.randrange(5)+2);encounter['bait']=0
        encounter['catch_factor']=min(20,encounter['catch_factor']*2)
    else:
        safari['balls']-=1
        catch_rate=encounter['catch_factor']*1275//100
        hp=pokemon['stats']['hp']
        odds=(catch_rate*15//10)*(3*hp-2*pokemon['hp'])//(3*hp)
        shakes=0
        if odds>254:shakes=4
        elif odds>0:
            threshold=1048560//math.isqrt(math.isqrt(16711680//odds))
            while shakes<4 and rng.randrange(65536)<threshold:shakes+=1
        result['shakes']=shakes
        if shakes==4:
            actor=trainer.get('human_id',trainer.get('actor_id',trainer.get('id')))
            pokemon['owner_id']=actor;pokemon['original_trainer_id']=pokemon.get('original_trainer_id') or actor;pokemon.setdefault('ownership_history',[]).append(actor);pokemon['pokeball']='SAFARI_BALL'
            container=trainer['party'] if len(trainer['party'])<6 else trainer['box'];container.append(pokemon['pokemon_id'])
            trainer['pokedex']=sorted(set(trainer.get('pokedex',[])+[pokemon['species']]))
            result.update({'caught':True,'ended':True,'outcome':'caught'})
        elif safari['balls']==0:result.update({'ended':True,'outcome':'no_balls'})
    if not result['ended']:
        if flee:result.update({'ended':True,'wild_fled':True,'outcome':'wild_fled'})
        elif encounter['rock']:
            encounter['rock']-=1
            if not encounter['rock']:encounter['catch_factor']=data()['species'][pokemon['species']]['catchRate']*100//1275
        elif encounter['bait']:encounter['bait']-=1
    encounter['turn']+=1
    if result['ended']:safari['encounter']=None
    if safari['balls']==0:safari['active']=False;safari['end_reason']='no_balls'
    return trainer,pokemon,result

def safari_observation(trainer,pokemon):
    safari=trainer.get('safari',{});encounter=safari.get('encounter')
    if not encounter:return {}
    return {'kind':'safari','turn':encounter['turn'],'balls':safari['balls'],'steps':safari['steps'],'opponent':{'species':pokemon['species'],'level':pokemon['level'],'hp_percent':pokemon['hp']*100//pokemon['stats']['hp']},'behavior':'angry' if encounter['rock'] else 'eating' if encounter['bait'] else 'watching'}
