"""Consensual personal duels; source link-like battles give no XP/prize or loss."""
import copy,itertools
from .battle import BattleSession

def available(state,a,b,doubles=False,*,radius=6):
    if a==b or a not in state.humans or b not in state.humans:return False
    x,y=state.humans[a],state.humans[b]
    if x.get('activity') or y.get('activity') or x.get('service_request') or y.get('service_request'):return False
    if x.get('battle_id') or y.get('battle_id') or x.get('safari',{}).get('encounter') or y.get('safari',{}).get('encounter'):return False
    if x['map_id']!=y['map_id'] or abs(x['x']-y['x'])+abs(x['y']-y['y'])>radius:return False
    return all(1<=len(t['party'])<=6 and all(pid in state.pokemon and state.pokemon[pid]['owner_id']==t['human_id'] for pid in t['party']) and sum(state.pokemon[pid]['hp']>0 for pid in t['party'])>=(2 if doubles else 1) for t in (x,y))

def start_personal_duel(state,offer,rng,battle_id):
    if offer['status']!='pending' or not available(state,offer['proposer'],offer['recipient'],offer['doubles']):raise ValueError('Challenge no longer available')
    teams=[]
    for hid in (offer['proposer'],offer['recipient']):
        party=[copy.deepcopy(state.pokemon[pid]) for pid in state.humans[hid]['party']];party.sort(key=lambda p:p['hp']<=0)
        teams.append({'actor_id':hid,'party':party})
    return BattleSession.start(teams,[rng.randrange(65536) for _ in range(4)],battle_id=battle_id,doubles=offer['doubles'],challenge={'kind':'personal','economy':'source-link-like-no-rewards'})

def double_turn_choices(session,actor):
    """Enumerate source-format two-slot choices; simulator validates submit."""
    req=session.observation(actor)['request'] or {}
    if req.get('wait'):return []
    own=req.get('side',{}).get('pokemon',[]);forced=req.get('forceSwitch')
    switches=[{'type':'switch','slot':i} for i,p in enumerate(own,1) if not p.get('active') and 'fnt' not in p['condition']]
    options=[]
    active=[p for p in own if p.get('active')]
    for index in range(2):
        slot=[]
        if forced is not None:
            slot=copy.deepcopy(switches) if index<len(forced) and forced[index] else [{'type':'pass'}]
        else:
            entry=(req.get('active') or [])[index] if index<len(req.get('active') or []) else {}
            if index>=len(active) or 'fnt' in active[index]['condition']:slot=[{'type':'pass'}]
            else:
                for i,m in enumerate(entry.get('moves',[]),1):
                    if m.get('disabled') or m.get('pp',1)<=0:continue
                    target=m.get('target','normal')
                    targets=[1,2,-(2-index)] if target in ('normal','any') else [1,2] if target=='adjacentFoe' else [-(2-index)] if target=='adjacentAlly' else [None]
                    for aim in targets:
                        choice={'type':'move','slot':i}
                        if aim is not None:choice['target']=aim
                        slot.append(choice)
                if not entry.get('trapped'):slot+=copy.deepcopy(switches)
        options.append(slot)
    return [{'choices':list(pair)} for pair in itertools.product(*options) if not (pair[0]['type']==pair[1]['type']=='switch' and pair[0]['slot']==pair[1]['slot'])]
