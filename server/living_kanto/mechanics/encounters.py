"""Pinned cartridge encounter slot distributions for land, Surf and rods."""
import json
from functools import lru_cache
from .reference import REFERENCE,data

@lru_cache(maxsize=1)
def encounter_rules():
    group=json.loads((REFERENCE/'src/data/wild_encounters.json').read_text())['wild_encounter_groups'][0]
    return {row['type']:row for row in group['fields']}

def select_encounter(tables,method,rng,*,rod=None):
    field={'land':'land_mons','surf':'water_mons','fish':'fishing_mons'}[method]
    available=[row for row in tables if row.get(field)]
    if not available:raise ValueError('No reference encounters for this method')
    rules=encounter_rules()[field]
    indexes=rules.get('groups',{}).get(rod) if method=='fish' else list(range(len(rules['encounter_rates'])))
    if indexes is None:raise ValueError('Unknown rod')
    baseline=next((row for row in available if 'FireRed' in row.get('base_label','')),available[0])
    candidates=[];weights=[]
    for i in indexes:
        variants=[]
        for table in [baseline]+[row for row in available if row is not baseline]:
            mons=table[field]['mons']
            if len(mons)!=len(rules['encounter_rates']):raise ValueError('Encounter table slot count mismatch')
            row=mons[i]
            if row['species'].removeprefix('SPECIES_') in data()['species'] and row not in variants:variants.append(row)
        for row in variants:candidates.append(row);weights.append(rules['encounter_rates'][i]/len(variants))
    if not candidates:raise ValueError('No original-151 encounter species')
    return rng.choices(candidates,weights=weights,k=1)[0]

def fishing_bite(rng):
    # field_player_avatar.c Fishing6: if Random() & 1, no bite.
    return not (rng.randrange(65536)&1)


def walking_encounter(trainer,cell,tables,party,rng,*,surfing=False,bicycle=False):
    """One accepted walked tile; copied trainer counters and source selected row.

    Rate RNG uses pinned ISO_RANDOMIZE2; the caller's canonical seeded RNG
    supplies cartridge main-RNG cooldown/terrain/slot/level draws. This preserves
    source probability/order, not the entire ROM's unrelated global RNG stream.
    """
    import copy
    h=copy.deepcopy(trainer);counter=h.setdefault('field_encounter',{})
    if counter.get('map_id')!=h['map_id']:
        counter.update({'map_id':h['map_id'],'steps':0,'rate_buff':0,'prev_behavior':0,'rate_rng':rng.randrange(65536)})
    repel=counter.get('repel_steps',0)
    if repel:counter['repel_steps']=repel-1
    behavior=cell.get('behavior',0);previous=counter.get('prev_behavior',0);counter['prev_behavior']=behavior
    encounter_type=cell.get('encounter_type',0)
    field='land_mons' if encounter_type==1 else 'water_mons' if encounter_type==2 else None
    rows=[row for row in tables if field and row.get(field)]
    if not rows or h.get('battle_id') or not party and not h.get('safari',{}).get('active'):return h,None
    if party and not any(p['hp']>0 for p in party) and not h.get('safari',{}).get('active'):return h,None
    baseline=next((row for row in rows if 'FireRed' in row.get('base_label','')),rows[0]);info=baseline[field];base=info['encounter_rate']
    minimum=0 if base>=80 else 8 if base<10 else 8-base//10
    minimum*=256;early=5*256;lead=party[0] if party else {};ability=lead.get('ability');tag=lead.get('held_item')=='CLEANSE_TAG';flute=counter.get('flute')
    if flute=='white':minimum-=minimum//2;early+=early//2
    elif flute=='black':minimum*=2;early//=2
    if tag:minimum+=minimum//3;early-=early//3
    if ability=='STENCH':minimum*=2;early//=2
    elif ability=='ILLUMINATE':minimum//=2;early*=2
    if counter.get('steps',0)<minimum//256:
        counter['steps']=counter.get('steps',0)+1
        if rng.randrange(65536)%100>=early//256:return h,None
    if previous!=behavior and rng.randrange(65536)%100>=60:return h,None
    rate=base*16
    if bicycle:rate=rate*80//100
    rate+=counter.get('rate_buff',0)*16//200
    if flute=='white':rate+=rate//2
    elif flute=='black':rate//=2
    if tag:rate=rate*2//3
    if ability=='STENCH':rate//=2
    elif ability=='ILLUMINATE':rate*=2
    counter['rate_rng']=(counter['rate_rng']*1103515245+12345)&0xffffffff
    if (counter['rate_rng']>>16)%1600>=min(1600,rate):
        counter['rate_buff']=0 if counter.get('repel_steps',0) else (counter.get('rate_buff',0)+base)&65535
        return h,None
    weights=encounter_rules()[field]['encounter_rates'];draw=rng.randrange(65536)%sum(weights);index=0
    while draw>=weights[index]:draw-=weights[index];index+=1
    variants=[]
    for table in [baseline]+[r for r in rows if r is not baseline]:
        variant=table[field]['mons'][index]
        if variant['species'].removeprefix('SPECIES_') in data()['species'] and variant not in variants:variants.append(variant)
    if not variants:return h,None
    row=variants[rng.randrange(65536)%len(variants)] if len(variants)>1 else variants[0];level=row['min_level']+rng.randrange(65536)%(row['max_level']-row['min_level']+1)
    if counter.get('repel_steps',0) and level<next((p['level'] for p in party if p['hp']>0),101):
        counter['rate_buff']=0;return h,None
    counter['rate_buff']=0;counter['steps']=0
    return h,{'species':row['species'],'min_level':level,'max_level':level}
