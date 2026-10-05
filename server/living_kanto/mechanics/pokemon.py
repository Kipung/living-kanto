"""Persistent Gen III individual lifecycle; all random draws use supplied RNG."""
import math
from .reference import data, normalize

STAT_FIELDS = {'hp':'baseHP','atk':'baseAttack','def':'baseDefense','spe':'baseSpeed','spa':'baseSpAttack','spd':'baseSpDefense'}
# Cartridge nature ordering: stat increased by nature // 5, decreased by nature % 5.
NATURE_STATS = ('atk','def','spe','spa','spd')
NATURES = ('Hardy','Lonely','Brave','Adamant','Naughty','Bold','Docile','Relaxed','Impish','Lax','Timid','Hasty','Serious','Jolly','Naive','Modest','Mild','Quiet','Bashful','Rash','Calm','Gentle','Sassy','Careful','Quirky')

def experience_at_level(species, level):
    if not 1 <= level <= 100: raise ValueError('level must be 1..100')
    growth = data()['species'][normalize(species)]['growth']
    n = level
    if n == 1: return 0 if growth == 'MEDIUM_SLOW' else 1
    if growth == 'MEDIUM_FAST': return n**3
    if growth == 'FAST': return 4*n**3//5
    if growth == 'SLOW': return 5*n**3//4
    if growth == 'MEDIUM_SLOW': return 6*n**3//5 - 15*n*n + 100*n - 140
    raise NotImplementedError(f'Unsupported Kanto growth rate {growth}')

def calculate_stats(species, level, ivs, evs, nature=0):
    row = data()['species'][normalize(species)]
    if not 1 <= level <= 100 or not 0 <= nature < 25: raise ValueError('invalid level or nature')
    if any(not 0<=ivs[s]<=31 or not 0<=evs[s]<=255 for s in STAT_FIELDS) or sum(evs.values()) > 510: raise ValueError('invalid IV/EV allocation')
    stats = {}
    for stat, field in STAT_FIELDS.items():
        val = (2*row[field] + ivs[stat] + evs[stat]//4)*level//100
        if stat == 'hp': val += level+10
        else:
            val += 5
            plus,minus = NATURE_STATS[nature//5],NATURE_STATS[nature%5]
            if plus != minus: val = val*(110 if stat==plus else 90 if stat==minus else 100)//100
        stats[stat] = val
    return stats

def create_pokemon(species, level, owner_id, rng, identifier=None):
    species = normalize(species)
    row = data()['species'][species]
    ivs = {s:rng.randrange(32) for s in STAT_FIELDS}
    evs = {s:0 for s in STAT_FIELDS}
    personality = rng.getrandbits(32)
    nature = personality%25
    available = []
    for learned, move in data()['learnsets'][species]:
        if learned <= level and move not in available: available.append(move)
    moves = [{'move':m,'pp':data()['moves'][m]['pp'],'max_pp':data()['moves'][m]['pp']} for m in available[-4:]]
    stats = calculate_stats(species,level,ivs,evs,nature)
    ability_choices = [a for a in row['abilities'] if a!='NONE']
    ability_slot = (personality & 1) if len(ability_choices)>1 else 0
    ability = ability_choices[ability_slot]
    return {'pokemon_id':identifier or f'pokemon-{rng.getrandbits(128):032x}','species':species,'owner_id':owner_id,'original_trainer_id':owner_id,'level':level,'ivs':ivs,'evs':evs,'nature':NATURES[nature], 'personality':personality,'ability_slot':ability_slot,'gender':gender_for(species,personality), 'stats':stats,'hp':stats['hp'],'status':'','moves':moves,'ability':ability,'friendship':row['friendship'],'experience':experience_at_level(species,level),'held_item':'','ownership_history':[owner_id] if owner_id else []}

def heal(pokemon):
    pokemon['hp'] = pokemon['stats']['hp']; pokemon['status'] = ''
    for move in pokemon['moves']: move['pp'] = move['max_pp']

def transfer(pokemon, previous_owner, new_owner, party):
    if pokemon['owner_id'] != previous_owner: raise ValueError('ownership changed')
    if len(party) >= 6: raise ValueError('party is full; choose storage')
    if pokemon['pokemon_id'] in party: raise ValueError('duplicate individual')
    pokemon['owner_id'] = new_owner
    pokemon['ownership_history'].append(new_owner)
    party.append(pokemon['pokemon_id'])

def catch_attempt(pokemon, ball, rng, *, turn=0, already_caught=False):
    if pokemon['owner_id'] is not None: raise ValueError('cannot catch owned Pokémon')
    if pokemon['hp'] <= 0: raise ValueError('cannot catch fainted Pokémon')
    ball = normalize(ball).removeprefix('ITEM_')
    row = data()['species'][pokemon['species']]
    multipliers = {'POKE_BALL':10,'GREAT_BALL':15,'ULTRA_BALL':20,'MASTER_BALL':10,'PREMIER_BALL':10,'LUXURY_BALL':10,'DIVE_BALL':10,'NET_BALL':30 if set(row['types'])&{'WATER','BUG'} else 10,'NEST_BALL':max(10,40-pokemon['level']),'REPEAT_BALL':30 if already_caught else 10,'TIMER_BALL':min(40,10+turn)}
    if ball not in multipliers: raise ValueError('unsupported ball (Safari uses separate encounter rules)')
    hp = pokemon['stats']['hp']
    odds = (row['catchRate']*multipliers[ball]//10)*(3*hp-2*pokemon['hp'])//(3*hp)
    if pokemon['status'] in ('slp','frz'): odds *= 2
    elif pokemon['status'] in ('psn','brn','par','tox'): odds = odds*15//10
    if ball=='MASTER_BALL' or odds>254: return {'caught':True,'shakes':4}
    if odds==0: return {'caught':False,'shakes':0}
    threshold = 1048560//math.isqrt(math.isqrt(16711680//odds))
    shakes = 0
    while shakes<4 and rng.randrange(65536)<threshold: shakes += 1
    return {'caught':shakes==4,'shakes':shakes}

def experience_reward(defeated, *, participants=1, trainer_battle=False, traded=False):
    if participants<1: raise ValueError('participants must be positive')
    exp = max(1,data()['species'][defeated['species']]['expYield']*defeated['level']//7//participants)
    if trainer_battle: exp = exp*150//100
    if traded: exp = exp*150//100
    return exp

def grant_experience(pokemon, amount, *, map_id=None, adjust_friendship=True):
    if amount<0: raise ValueError('negative experience')
    pokemon['experience'] = min(experience_at_level(pokemon['species'],100),pokemon['experience']+amount)
    old = pokemon['level']
    while pokemon['level']<100 and pokemon['experience']>=experience_at_level(pokemon['species'],pokemon['level']+1): pokemon['level'] += 1
    if pokemon['level']==old:return []
    if adjust_friendship:
        from .friendship import change_friendship
        for _ in range(old,pokemon['level']):change_friendship(pokemon,'GROW_LEVEL',map_id=map_id)
    max_before = pokemon['stats']['hp']
    pokemon['stats'] = calculate_stats(pokemon['species'],pokemon['level'],pokemon['ivs'],pokemon['evs'],NATURES.index(pokemon['nature']))
    if pokemon['hp']>0: pokemon['hp'] += pokemon['stats']['hp']-max_before
    pokemon['evolution_opportunity']={'species':pokemon['species'],'level':pokemon['level'],'targets':evolution_options(pokemon,level_up=True)}
    # Learning remains an explicit trainer choice; never discard an existing move silently.
    return [{'level':lvl,'move':move} for lvl,move in data()['learnsets'][pokemon['species']] if old<lvl<=pokemon['level']]

def evolution_options(pokemon, *, item=None, traded=False, level_up=False):
    if pokemon.get('held_item')=='EVERSTONE': return []
    results = []
    for method,param,target in data()['evolutions'].get(pokemon['species'],[]):
        if target not in data()['species']: continue
        if traded:
            if method=='TRADE':results.append(target)
        elif item is not None:
            if method=='ITEM' and normalize(item).removeprefix('ITEM_')==param.removeprefix('ITEM_'):results.append(target)
        elif (method=='LEVEL' and pokemon['level']>=int(param)) or (method=='FRIENDSHIP' and pokemon['friendship']>=220):
            opportunity=pokemon.get('evolution_opportunity') or {}
            if level_up or (opportunity.get('species')==pokemon['species'] and opportunity.get('level')==pokemon['level'] and target in opportunity.get('targets',[])):results.append(target)
    return results

def evolve(pokemon, target, **conditions):
    target = normalize(target)
    if target not in evolution_options(pokemon,**conditions): raise ValueError('evolution requirements unmet')
    before = pokemon['stats']['hp']
    pokemon['species'] = target
    pokemon['evolution_opportunity']=None
    pokemon['stats'] = calculate_stats(target,pokemon['level'],pokemon['ivs'],pokemon['evs'],NATURES.index(pokemon['nature']))
    if pokemon['hp']>0: pokemon['hp'] += pokemon['stats']['hp']-before
    choices = data()['species'][target]['abilities']
    slot = pokemon.get('ability_slot',pokemon.get('personality',0)&1)
    pokemon['ability'] = choices[slot] if choices[slot]!='NONE' else choices[0]
    if 'personality' in pokemon: pokemon['gender'] = gender_for(target,pokemon['personality'])


def gender_for(species,personality):
    ratio = data()['species'][normalize(species)]['genderRatio']
    if ratio==255: return 'N'
    if ratio==254: return 'F'
    return 'F' if ratio>(personality&255) else 'M'

def grant_evs(pokemon,defeated_species,*,pokerus=False):
    row=data()['species'][normalize(defeated_species)]
    fields={'hp':'HP','atk':'Attack','def':'Defense','spe':'Speed','spa':'SpAttack','spd':'SpDefense'}
    total=sum(pokemon['evs'].values())
    for stat,label in fields.items():
        multiplier=(2 if pokerus else 1)*(2 if pokemon.get('held_item')=='MACHO_BRACE' else 1)
        gain=min(row['evYield_'+label]*multiplier,255-pokemon['evs'][stat],510-total)
        pokemon['evs'][stat]+=gain; total+=gain
    return dict(pokemon['evs'])

def learn_move(pokemon,move,*,replace_slot=None):
    move=normalize(move)
    if move not in [m for level,m in data()['learnsets'][pokemon['species']] if level<=pokemon['level']]: raise ValueError('Move not learned at this level')
    if any(m['move']==move for m in pokemon['moves']): raise ValueError('Move already known')
    slot={'move':move,'pp':data()['moves'][move]['pp'],'max_pp':data()['moves'][move]['pp']}
    if len(pokemon['moves'])<4: pokemon['moves'].append(slot)
    elif type(replace_slot) is int and 0<=replace_slot<4: pokemon['moves'][replace_slot]=slot
    else: raise ValueError('Choose one of four move slots to replace')
