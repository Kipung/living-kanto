"""Cmd_getexp integer order, per-foe participation and held-item distribution."""
from .reference import data

def experience_distribution(defeated,party,participants,trainer_id,*,trainer_battle=False):
    healthy=[p for p in party if p['hp']>0 and not p.get('is_egg')]
    sent=[p for p in healthy if p['pokemon_id'] in participants]
    shared=[p for p in healthy if p.get('held_item')=='EXP_SHARE']
    base=data()['species'][defeated['species']]['expYield']*defeated['level']//7
    direct=max(1,(base//2 if shared else base)//max(1,len(sent)))
    share=max(1,(base//2)//len(shared)) if shared else 0
    awards={}
    for p in healthy:
        pid=p['pokemon_id'];amount=(direct if pid in participants else 0)+(share if p.get('held_item')=='EXP_SHARE' else 0)
        if not amount or p['level']>=100:continue
        if p.get('held_item')=='LUCKY_EGG':amount=amount*150//100
        if trainer_battle:amount=amount*150//100
        origin=p.get('original_trainer_id') or next(iter(p.get('ownership_history',[])),trainer_id)
        if origin!=trainer_id:amount=amount*150//100
        awards[pid]=amount
    return awards

def active_ids(session,actor):
    req=(session.observation(actor)['request'] or {}).get('side',{}).get('pokemon',[])
    mons=[p for p in session.record['result']['pokemon'] if p['owner_id']==actor]
    return [p['pokemon_id'] for p,entry in zip(mons,req) if entry.get('active') and p['hp']>0]
