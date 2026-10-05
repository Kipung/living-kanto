"""Read mechanics data from the pinned pret/pokefirered reference, never guessed tables."""
from functools import lru_cache
from pathlib import Path
import re

REFERENCE = Path(__file__).resolve().parents[3] / 'reference' / 'pokefirered'

def normalize(value):
    return value.upper().replace('♀','_F').replace('♂','_M').replace("'",'').replace('.','').replace(' ', '_').replace('-', '_')

@lru_cache(maxsize=1)
def data():
    root = REFERENCE
    if not root.exists():
        raise RuntimeError('Pinned pokefirered reference missing; restore reference/pokefirered')
    text = (root/'src/data/pokemon/species_info.h').read_text()
    constants = (root/'include/constants/species.h').read_text()
    species_ids = {k:int(v) for k,v in re.findall(r'#define SPECIES_(\w+)\s+(\d+)', constants) if 1 <= int(v) <= 151}
    species = {}
    for name, body in re.findall(r'\[SPECIES_(\w+)\]\s*=\s*\{\n(.*?)\n    \}', text, re.S):
        if name not in species_ids: continue
        row = {k:int(v) for k,v in re.findall(r'\.(\w+)\s*=\s*(\d+)', body)}
        row['types'] = re.findall(r'TYPE_(\w+)', re.search(r'\.types\s*=\s*\{([^}]+)',body).group(1))
        row['abilities'] = re.findall(r'ABILITY_(\w+)', re.search(r'\.abilities\s*=\s*\{([^}]+)',body).group(1))
        for item_field in ('itemCommon','itemRare'):row[item_field]=re.search(r'\.'+item_field+r'\s*=\s*ITEM_(\w+)',body).group(1)
        row['growth'] = re.search(r'\.growthRate\s*=\s*GROWTH_(\w+)',body).group(1)
        gender = re.search(r'\.genderRatio\s*=\s*([^,]+)',body).group(1)
        percent = re.search(r'PERCENT_FEMALE\(([\d.]+)\)',gender)
        row['genderRatio'] = min(254,int(float(percent.group(1))*255/100)) if percent else {'MON_MALE':0,'MON_FEMALE':254,'MON_GENDERLESS':255}[gender]
        row['number'] = species_ids[name]
        species[name] = row
    moves = {}
    for name, body in re.findall(r'\[MOVE_(\w+)\]\s*=\s*\{\n(.*?)\n    \}', (root/'src/data/battle_moves.h').read_text(), re.S):
        row = {k:int(v) for k,v in re.findall(r'\.(\w+)\s*=\s*(-?\d+)',body)}
        row['type'] = re.search(r'\.type\s*=\s*TYPE_(\w+)',body).group(1)
        row['effect'] = re.search(r'\.effect\s*=\s*EFFECT_(\w+)',body).group(1)
        moves[name] = row
    learns = {name: [(int(level),move) for level,move in re.findall(r'LEVEL_UP_MOVE\((\d+), MOVE_(\w+)\)',body)] for name,body in re.findall(r'static const u16 (\w+)\[\] = \{(.*?)\};', (root/'src/data/pokemon/level_up_learnsets.h').read_text(),re.S)}
    pointers = dict(re.findall(r'\[SPECIES_(\w+)\]\s*=\s*(\w+)',(root/'src/data/pokemon/level_up_learnset_pointers.h').read_text()))
    evolutions = {}
    for name,body in re.findall(r'\[SPECIES_(\w+)\]\s*=\s*(.*?)(?=\n\s*\[SPECIES_|\n};)',(root/'src/data/pokemon/evolution.h').read_text(),re.S):
        evolutions[name] = re.findall(r'\{EVO_(\w+),\s*(\w+),\s*SPECIES_(\w+)\}',body)
    return {'species':species,'moves':moves,'learnsets':{s:learns[pointers[s]] for s in species}, 'evolutions':evolutions}
