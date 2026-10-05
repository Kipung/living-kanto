"""Source release limits; world retains released individual instead of zeroing it."""
import copy

def release_pokemon(trainer,pokemon,owned,*,simulated_time=None):
    actor=trainer['human_id'];pid=pokemon['pokemon_id']
    if trainer.get('battle_id') or pokemon['owner_id']!=actor or pid not in trainer['party']+trainer['box']:raise ValueError('Owned stored individual required')
    if pokemon.get('is_egg') or pokemon.get('held_item','').endswith('_MAIL'):raise ValueError('Source eggs/mail cannot be released')
    if pid in trainer['party'] and not any(p['pokemon_id']!=pid and p['pokemon_id'] in trainer['party'] and p['hp']>0 and not p.get('is_egg') for p in owned):raise ValueError('Cannot release last usable party Pokemon')
    moves={m['move'] for m in pokemon['moves']}
    for restricted in moves.intersection({'SURF','DIVE'}):
        if not any(p['pokemon_id']!=pid and any(m['move']==restricted for m in p['moves']) for p in owned):raise ValueError('Cannot release sole source Surf/Dive user')
    h=copy.deepcopy(trainer);p=copy.deepcopy(pokemon)
    h['party']=[i for i in h['party'] if i!=pid];h['box']=[i for i in h['box'] if i!=pid]
    p['owner_id']=None;p.setdefault('release_history',[]).append({'trainer_id':actor,'time':simulated_time,'map_id':trainer['map_id']})
    return h,p
