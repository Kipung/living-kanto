"""Physical source gift balls; source global one-time flags become per trainer."""
import json,re,copy
from functools import lru_cache
from .reference import REFERENCE
from .pokemon import create_pokemon
@lru_cache(maxsize=1)
def gift_templates():
    result={}
    for mid in ('CeladonCity_Condominiums_RoofRoom','SaffronCity_Dojo'):
        scripts=(REFERENCE/'data/maps'/mid/'scripts.inc').read_text()
        for obj in json.loads((REFERENCE/'data/maps'/mid/'map.json').read_text())['object_events']:
            species=next((s for s in ('EEVEE','HITMONLEE','HITMONCHAN') if s.title().replace('Hitmonlee','Hitmonlee').lower() in obj['script'].lower()),None)
            if not species:continue
            level=int(re.search(r'givemon (?:SPECIES_EEVEE|VAR_TEMP_1), (\d+)',scripts).group(1))
            key=species.lower();result[key]={'gift_id':key,'species':species,'level':level,'map_id':mid,'x':obj['x'],'y':obj['y'],'claim_group':'dojo_hitmon' if species!='EEVEE' else key,'requires_dojo_win':species!='EEVEE','source_script':obj['script']}
    mid='SilphCo_7F'
    scripts=(REFERENCE/'data/maps'/mid/'scripts.inc').read_text()
    obj=next(o for o in json.loads((REFERENCE/'data/maps'/mid/'map.json').read_text())['object_events'] if o['script'].endswith('_LaprasGuy'))
    level=int(re.search(r'givemon SPECIES_LAPRAS, (\d+)',scripts).group(1))
    result['lapras']={'gift_id':'lapras','species':'LAPRAS','level':level,'map_id':mid,'x':obj['x'],'y':obj['y'],'claim_group':'lapras','requires_dojo_win':False,'source_script':obj['script'],'adaptation':'Physical one-time-per-trainer gift station replaces campaign NPC dialogue; no scripted human or victory is created.'}
    return result

def available_gifts(trainer):
    return [g for g in gift_templates().values() if g['map_id']==trainer['map_id'] and abs(g['x']-trainer['x'])+abs(g['y']-trainer['y'])<=1 and g['claim_group'] not in trainer.get('source_gifts',[]) and (not g['requires_dojo_win'] or trainer.get('access',{}).get('dojo_master_defeated')) and (len(trainer['party'])<6 or len(trainer['box'])<420)]

def receive_gift(trainer,gift_id,rng):
    gift=next((g for g in available_gifts(trainer) if g['gift_id']==gift_id),None)
    if gift is None:raise ValueError('Source gift unavailable')
    h=copy.deepcopy(trainer);p=create_pokemon(gift['species'],gift['level'],h['human_id'],rng,identifier=f'pokemon-gift-{h["human_id"]}-{gift_id}')
    p['origin_map_id']=gift['map_id'];p['pokeball']='POKE_BALL';p['source_gift']=gift['source_script']
    h['party' if len(h['party'])<6 else 'box'].append(p['pokemon_id']);h.setdefault('source_gifts',[]).append(gift['claim_group']);h['pokedex']=sorted(set(h['pokedex']+[p['species']]))
    return h,p
