"""One source walking tile: every128 friendship; every5 nonforced poison."""
import copy
from .friendship import change_friendship

def field_steps(trainer,party,rng,*,forced=False):
    h=copy.deepcopy(trainer);mons=copy.deepcopy(party);counter=h.setdefault('field_steps',{})
    if any(p['owner_id']!=h['human_id'] for p in mons):raise ValueError('Walking party ownership mismatch')
    counter['happiness']=(counter.get('happiness',0)+1)%128
    if counter['happiness']==0:
        for mon in mons:
            if not rng.randrange(65536)&1:change_friendship(mon,'WALKING',map_id=h['map_id'])
    poison_faint=False
    if not forced:
        counter['poison']=(counter.get('poison',0)+1)%5
        if counter['poison']==0:
            for mon in mons:
                if mon.get('status') not in ('psn','tox'):continue
                mon['hp']=max(0,mon['hp']-1)
                if not mon['hp']:poison_faint=True;change_friendship(mon,'FAINT_OUTSIDE_BATTLE',map_id=h['map_id']);mon['status']=''
    return h,mons,bool(poison_faint and mons and all(p['hp']==0 for p in mons))
