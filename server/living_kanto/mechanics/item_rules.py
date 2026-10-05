"""Pure, reference-backed Gen III inventory and individual transactions.

Every operation validates first and returns copies; the caller commits all
returned entities together with the accepted decision and canonical event.
"""
import copy
from functools import lru_cache
import json
import re
from .reference import REFERENCE, data, normalize
from .pokemon import evolve, evolution_options, calculate_stats, NATURES, grant_experience, experience_at_level

class ItemError(ValueError):
    pass

@lru_cache(maxsize=1)
def item_catalog():
    items=json.loads((REFERENCE/'src/data/items.json').read_text())['items']
    aliases=dict(re.findall(r'#define ITEM_((?:TM|HM)\d\d_\w+)\s+ITEM_((?:TM|HM)\d\d)',(REFERENCE/'include/constants/items.h').read_text()))
    catalog={row['itemId'].removeprefix('ITEM_'):copy.deepcopy(row) for row in items}
    for alias,key in aliases.items():
        catalog[key]['move']=alias[5:]
        catalog[key]['alias']=alias
    return catalog

@lru_cache(maxsize=1)
def item_effects():
    text=(REFERENCE/'src/data/pokemon/item_effects.h').read_text()
    tables={name:{int(i):value.strip() for i,value in re.findall(r'\[(\d+)\]\s*=\s*([^,]+),',body)} for name,body in re.findall(r'static const u8 sItemEffect_(\w+)\[\d+\] = \{(.*?)\n\};',text,re.S)}
    # The C friendship macro is source-defined (5,3,2); preserve its parameters.
    for name,body in re.findall(r'static const u8 sItemEffect_(\w+)\[\d+\] = \{(.*?)\n\};',text,re.S):
        if 'STAT_BOOST_FRIENDSHIP_CHANGE' in body:tables[name].update({6:'1',7:'1',8:'0'})
        macro=re.search(r'VITAMIN_FRIENDSHIP_CHANGE\((\d+)\)',body)
        if macro:
            index=int(macro.group(1))
            tables[name].update({index:'5',index+1:'3',index+2:'2'})
    return {item:tables[table] for item,table in re.findall(r'\[ITEM_(\w+) - ITEM_POTION\]\s*=\s*sItemEffect_(\w+)',text)}

@lru_cache(maxsize=1)
def machine_learnsets():
    text=(REFERENCE/'src/data/pokemon/tmhm_learnsets.h').read_text()
    return {species:[alias[:4] for alias in re.findall(r'TMHM\(((?:TM|HM)\d\d)_\w+\)',body)] for species,body in re.findall(r'\[SPECIES_(\w+)\]\s*=\s*(.*?)(?=\n\s*\[SPECIES_|\n};)',text,re.S) if species in data()['species']}

@lru_cache(maxsize=1)
def tutor_learnsets():
    text=(REFERENCE/'src/data/pokemon/tutor_learnsets.h').read_text()
    return {species:re.findall(r'TUTOR\(MOVE_(\w+)\)',body) for species,body in re.findall(r'\[SPECIES_(\w+)\]\s*=\s*(.*?)(?=\n\s*\[SPECIES_|\n};)',text,re.S) if species in data()['species']}

def _item(item):
    key=normalize(item).removeprefix('ITEM_')
    if re.match(r'^(TM|HM)\d\d_',key):key=key[:4]
    if key not in item_catalog():raise ItemError('Unknown reference item')
    return key

def _owner(trainer,pokemon):
    actor=trainer.get('human_id',trainer.get('actor_id',trainer.get('id')))
    if not actor or pokemon['owner_id']!=actor:raise ItemError('Pokemon ownership mismatch')
    if pokemon['pokemon_id'] not in trainer.get('party',[])+trainer.get('box',[]):raise ItemError('Individual is not in trainer party or storage')
    return actor

def _consume(trainer,key,*,amount=1):
    inventory=trainer.get('inventory',{})
    stored=next((name for name in inventory if normalize(name).removeprefix('ITEM_')==key or normalize(name).removeprefix('ITEM_')==item_catalog()[key].get('alias')),None)
    if stored is None:raise ItemError('Item not owned')
    row=inventory[stored]
    quantity=row.get('quantity',0) if isinstance(row,dict) else row
    if type(quantity) is not int or quantity<max(1,amount):raise ItemError('Insufficient item quantity')
    if isinstance(row,dict):row['quantity']=quantity-amount
    else:inventory[stored]=quantity-amount

def _selected_move(pokemon,slot):
    if type(slot) is not int or not 1<=slot<=len(pokemon['moves']):raise ItemError('Choose a valid one-based move slot')
    return pokemon['moves'][slot-1]

def _change_friendship(pokemon,delta,*,map_id=None):
    from .friendship import apply_friendship_delta
    apply_friendship_delta(pokemon,delta,map_id=map_id)


def apply_item(trainer,pokemon,item,*,move_slot=None,evolution_target=None,battle=False,battle_conditions=None):
    """Return trainer/Pokemon copies, event. No-effect/illegal uses consume nothing.

    Battle context validates cartridge battleUsage. Temporary confusion,
    infatuation and X-item effects are handled by the battle service, not this
    persistent-state function.
    """
    actor=_owner(trainer,pokemon);key=_item(item)
    metadata=item_catalog()[key]
    if battle and not metadata.get('battleUsage'):raise ItemError('Item is not usable in a battle')
    effect=item_effects().get(key)
    if not effect:raise ItemError('Item requires a different authoritative service')
    t=copy.deepcopy(trainer);p=copy.deepcopy(pokemon);before=copy.deepcopy(p)
    flags=' '.join(effect.values())
    conditions=battle_conditions or {}
    battle_effects={}
    transient=key in ('X_ATTACK','X_DEFEND','X_SPEED','X_ACCURACY','X_SPECIAL','DIRE_HIT','GUARD_SPEC','RED_FLUTE') or any(flag in flags for flag in ('ITEM0_','ITEM1_','ITEM2_','ITEM3_GUARD_SPEC'))
    if transient and battle and not conditions.get('active'):raise ItemError('This battle item requires an active Pokemon')
    if transient and not battle:raise ItemError('Temporary item effect is only usable in battle')
    changed=False;friendship_before=p['friendship']
    boost_flags={'X_ATTACK':'atk','X_DEFEND':'def','X_SPEED':'spe','X_ACCURACY':'accuracy','X_SPECIAL':'spa'}
    if key in boost_flags:
        stat=boost_flags[key]
        if conditions.get('boosts',{}).get(stat,0)>=6:raise ItemError('Stat stage is already maximum')
        battle_effects['boost']={stat:1};changed=True
    if key=='DIRE_HIT':
        if conditions.get('focusenergy'):raise ItemError('Critical-hit focus already active')
        battle_effects['focusenergy']=True;changed=True
    if key=='GUARD_SPEC':
        if conditions.get('mist'):raise ItemError('Guard protection already active')
        battle_effects['mist']=True;changed=True
    if key=='RED_FLUTE' and conditions.get('infatuation'):
        battle_effects['cure_infatuation']=True;changed=True
    if ('ITEM3_CONFUSION' in flags or 'ITEM3_STATUS_ALL' in flags) and conditions.get('confusion'):
        battle_effects['cure_confusion']=True;changed=True
    if 'ITEM4_EVO_STONE' in flags:
        options=evolution_options(p,item=key)
        target=evolution_target or (options[0] if len(options)==1 else None)
        if target not in options:raise ItemError('Evolution stone has no effect on this individual')
        evolve(p,target,item=key);changed=True
    if 'ITEM3_LEVEL_UP' in flags:
        if p['level']>=100:raise ItemError('Already at maximum level')
        old_max=p['stats']['hp'];old_hp=p['hp']
        pending=grant_experience(p,experience_at_level(p['species'],p['level']+1)-p['experience'],adjust_friendship=False)
        p['pending_moves']=p.get('pending_moves',[])+[m for m in pending if m not in p.get('pending_moves',[])]
        if old_hp==0:p['hp']=p['stats']['hp']-old_max
        changed=True
    cures={'ITEM3_SLEEP':('slp',),'ITEM3_POISON':('psn','tox'),'ITEM3_BURN':('brn',),'ITEM3_FREEZE':('frz',),'ITEM3_PARALYSIS':('par',),'ITEM3_STATUS_ALL':('slp','psn','tox','brn','frz','par')}
    for flag,statuses in cures.items():
        if flag in flags and p['status'] in statuses:p['status']='';changed=True
    if 'ITEM4_HEAL_HP' in flags and 'ITEM3_LEVEL_UP' not in flags:
        revive='ITEM4_REVIVE' in flags
        if (revive and p['hp']==0) or (not revive and p['hp']>0):
            value=effect.get(6,'0')
            maximum=p['stats']['hp']
            amount=maximum if value=='ITEM6_HEAL_HP_FULL' else max(1,maximum//2) if value=='ITEM6_HEAL_HP_HALF' else int(value)
            hp=min(maximum,p['hp']+amount)
            if hp!=p['hp']:p['hp']=hp;changed=True
    if 'ITEM4_HEAL_PP_ALL' in flags:
        moves=[_selected_move(p,move_slot)] if 'ITEM4_HEAL_PP_ONE' in flags else p['moves']
        value=effect[6]
        for move in moves:
            pp=move['max_pp'] if value=='ITEM6_HEAL_PP_FULL' else min(move['max_pp'],move['pp']+int(value))
            if pp!=move['pp']:move['pp']=pp;changed=True
    if 'ITEM4_PP_UP' in flags or 'ITEM5_PP_MAX' in flags:
        move=_selected_move(p,move_slot);base=data()['moves'][move['move']]['pp']
        ups=move.get('pp_ups',next((n for n in range(4) if base*(5+n)//5==move['max_pp']),0))
        if ups>=3 or ('ITEM4_PP_UP' in flags and move['max_pp']<=4):raise ItemError('PP boost has no effect')
        new_ups=3 if 'ITEM5_PP_MAX' in flags else ups+1
        new_max=base*(5+new_ups)//5
        move['pp']+=new_max-move['max_pp'];move['max_pp']=new_max;move['pp_ups']=new_ups;changed=True
    ev_flags={'ITEM4_EV_HP':'hp','ITEM4_EV_ATK':'atk','ITEM5_EV_DEF':'def','ITEM5_EV_SPEED':'spe','ITEM5_EV_SPATK':'spa','ITEM5_EV_SPDEF':'spd'}
    for flag,stat in ev_flags.items():
        if flag in flags:
            gain=min(10,100-p['evs'][stat],510-sum(p['evs'].values()))
            if gain<=0:raise ItemError('Vitamin EV cap reached')
            old_max=p['stats']['hp'];p['evs'][stat]+=gain
            p['stats']=calculate_stats(p['species'],p['level'],p['ivs'],p['evs'],NATURES.index(p['nature']))
            if p['hp']>0:p['hp']+=p['stats']['hp']-old_max
            changed=True
    if not changed:raise ItemError('Item has no effect')
    # Source friendship params follow the consumable effect parameter.
    if 'ITEM5_FRIENDSHIP' in flags:
        numeric=[(i,int(v)) for i,v in sorted(effect.items()) if i>=6 and re.fullmatch(r'-?\d+',v)]
        changes=[v for _,v in numeric[-3:]]
        if len(changes)==3:_change_friendship(p,changes[0 if friendship_before<100 else 1 if friendship_before<200 else 2],map_id=trainer.get('map_id'))
    # Blue/Yellow/Red flutes are reusable. Red/Yellow already need battle service.
    if metadata.get('fieldUseFunc')=='FieldUseFunc_BlackWhiteFlute' or key.endswith('_FLUTE'):_consume(t,key,amount=0)
    else:_consume(t,key)
    event={'type':'item_used','actor_id':actor,'pokemon_id':p['pokemon_id'],'item':key,'before':before,'after':copy.deepcopy(p),'battle_effects':battle_effects}
    return t,p,event

def _teach(pokemon,move,replace_slot):
    if any(m['move']==move for m in pokemon['moves']):raise ItemError('Move already known')
    slot={'move':move,'pp':data()['moves'][move]['pp'],'max_pp':data()['moves'][move]['pp'],'pp_ups':0}
    if len(pokemon['moves'])<4 and replace_slot is None:pokemon['moves'].append(slot);return
    old=_selected_move(pokemon,replace_slot)
    hm_moves={r['move'] for k,r in item_catalog().items() if k.startswith('HM') and 'move' in r}
    if old['move'] in hm_moves:raise ItemError('HM move requires Move Deleter')
    pokemon['moves'][replace_slot-1]=slot

def teach_machine(trainer,pokemon,item,*,replace_slot=None):
    actor=_owner(trainer,pokemon);key=_item(item)
    metadata=item_catalog()[key]
    if 'move' not in metadata:raise ItemError('Item is not a TM or HM')
    if key not in machine_learnsets()[pokemon['species']]:raise ItemError('Species cannot learn this machine')
    if trainer.get('battle_id'):raise ItemError('Cannot teach moves during battle')
    t=copy.deepcopy(trainer);p=copy.deepcopy(pokemon)
    _consume(t,key,amount=0 if key.startswith('HM') else 1)
    _teach(p,metadata['move'],replace_slot)
    from .friendship import change_friendship
    change_friendship(p,'LEARN_TMHM',map_id=trainer.get('map_id'))
    return t,p,{'type':'move_learned','actor_id':actor,'pokemon_id':p['pokemon_id'],'move':metadata['move'],'source_item':key}

def teach_tutor(trainer,pokemon,move,*,tutor_id,replace_slot=None):
    actor=_owner(trainer,pokemon);move=normalize(move)
    if move not in tutor_learnsets()[pokemon['species']]:raise ItemError('Species cannot learn this tutor move')
    if tutor_id in trainer.get('used_tutors',[]):raise ItemError('Tutor already used')
    if trainer.get('battle_id'):raise ItemError('Cannot teach moves during battle')
    t=copy.deepcopy(trainer);p=copy.deepcopy(pokemon);_teach(p,move,replace_slot)
    t.setdefault('used_tutors',[]).append(tutor_id)
    return t,p,{'type':'move_learned','actor_id':actor,'pokemon_id':p['pokemon_id'],'move':move,'tutor_id':tutor_id,'adaptation':'one use per trainer rather than cartridge global tutor flag'}

def trade_exchange(first_trainer,first_pokemon,second_trainer,second_pokemon,*,offers,expected_state_version):
    """Atomic reciprocal same-individual trade, only after both accepted offers."""
    first=_owner(first_trainer,first_pokemon);second=_owner(second_trainer,second_pokemon)
    if first==second or first_pokemon['pokemon_id']==second_pokemon['pokemon_id']:raise ItemError('Distinct owners and individuals required')
    if first_trainer.get('battle_id') or second_trainer.get('battle_id'):raise ItemError('Cannot trade during battle')
    if len(offers)!=2 or len({o.get('trade_id') for o in offers})!=1 or not offers[0].get('trade_id'):raise ItemError('Two matching accepted trade offers required')
    for actor,own,requested in ((first,first_pokemon,second_pokemon),(second,second_pokemon,first_pokemon)):
        matches=[o for o in offers if o.get('actor_id')==actor]
        if len(matches)!=1:raise ItemError('Each actor must accept once')
        offer=matches[0]
        if offer.get('accepted') is not True or offer.get('state_version')!=expected_state_version or offer.get('offered_pokemon')!=own['pokemon_id'] or offer.get('requested_pokemon')!=requested['pokemon_id']:raise ItemError('Unaccepted or stale trade offer')
    trainers=[copy.deepcopy(first_trainer),copy.deepcopy(second_trainer)]
    pokemon=[copy.deepcopy(first_pokemon),copy.deepcopy(second_pokemon)]
    for index in range(2):
        t=trainers[index];outgoing=pokemon[index]['pokemon_id'];incoming=pokemon[1-index]['pokemon_id']
        if incoming in t.get('party',[])+t.get('box',[]):raise ItemError('Duplicate received individual')
        locations=[key for key in ('party','box') if outgoing in t.get(key,[])]
        if len(locations)!=1 or t[locations[0]].count(outgoing)!=1:raise ItemError('Ownership container corrupt')
        key=locations[0];t[key][t[key].index(outgoing)]=incoming
        p=pokemon[1-index];p['owner_id']=first if index==0 else second
        p.setdefault('ownership_history',[]).append(p['owner_id'])
        p['friendship']=70 # trade_scene.c:1073, except eggs (breeding is excluded).
        options=evolution_options(p,traded=True)
        if options:evolve(p,options[0],traded=True)
        t['pokedex']=sorted(set(t.get('pokedex',[])+[p['species']]))
    return trainers[0],pokemon[1],trainers[1],pokemon[0],{'type':'pokemon_traded','trade_id':offers[0]['trade_id'],'actors':[first,second],'pokemon_ids':[p['pokemon_id'] for p in pokemon]}
