"""Pinned friendship event table and source held-ball/region modifiers."""
import json,re
from functools import lru_cache
from .reference import REFERENCE

@lru_cache(maxsize=1)
def friendship_events():
    text=(REFERENCE/'src/pokemon.c').read_text()
    table=re.search(r'sFriendshipEventDeltas\[\]\[3\]\s*=\s*\{(.*?)\n\};',text,re.S).group(1)
    return {event:[int(v) for v in re.findall(r'-?\d+',values)] for event,values in re.findall(r'\[FRIENDSHIP_EVENT_(\w+)\]\s*=\s*\{([^}]+)',table)}

@lru_cache(maxsize=256)
def region_section(map_id):
    path=REFERENCE/'data/maps'/str(map_id)/'map.json'
    return json.loads(path.read_text()).get('region_map_section') if path.exists() else None

def change_friendship(pokemon,event,*,map_id=None):
    value=pokemon.get('friendship',0);column=0 if value<100 else 1 if value<200 else 2
    delta=friendship_events()[event][column]
    return apply_friendship_delta(pokemon,delta,map_id=map_id)

def apply_friendship_delta(pokemon,delta,*,map_id=None):
    value=pokemon.get('friendship',0)
    if delta>0:
        if pokemon.get('held_item')=='SOOTHE_BELL':delta=delta*150//100
        if pokemon.get('pokeball')=='LUXURY_BALL':delta+=1
        origin=region_section(pokemon.get('origin_map_id'))
        if origin and origin==region_section(map_id):delta+=1
    pokemon['friendship']=max(0,min(255,value+delta))
    return pokemon['friendship']
