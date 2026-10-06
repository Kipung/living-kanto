"""Pinned renewable hidden flags: step saturation and entry-only source sampling."""
import copy
import json
import re
from functools import lru_cache
from .reference import REFERENCE

SOURCE = 'pret/pokefirered/src/renewable_hidden_items.c;src/new_game.c;src/overworld.c'


@lru_cache(maxsize=1)
def catalog():
    text = (REFERENCE / 'src/renewable_hidden_items.c').read_text()
    names = {row['id']: row['name'] for path in (REFERENCE / 'data/maps').glob('*/map.json')
             for row in [json.loads(path.read_text())]}
    groups = []
    for map_id, body in re.findall(r'\.mapGroup\s*=\s*MAP_GROUP\((MAP_\w+)\),(.*?)\n    \},', text, re.S):
        groups.append({'map_id': names[map_id], **{
            rarity: re.findall(r'HIDDEN_ID\((FLAG_\w+)\)', re.search(r'\.' + rarity + r'\s*=\s*\{(.*?)\}', body, re.S).group(1))
            for rarity in ('rare', 'uncommon', 'common')}})
    threshold = int(re.search(r'if \(var < (\d+)\)', text).group(1))
    rare = int(re.search(r'if \(rval >= (\d+)\)', text).group(1))
    uncommon = int(re.search(r'else if \(rval >= (\d+)\)', text).group(1))
    return {'groups': groups, 'threshold': threshold, 'rare_threshold': rare, 'uncommon_threshold': uncommon}


@lru_cache(maxsize=1)
def renewable_flags():
    return frozenset(flag for group in catalog()['groups'] for rarity in ('rare','uncommon','common') for flag in group[rarity])


def available(trainer, flag):
    # Source new_game.c initially sets every renewable flag. Ordinary hidden
    # items start unclaimed; renewable items first appear after the first cycle.
    return flag not in renewable_flags() or flag in trainer.get('renewable_hidden_items', {}).get('available_flags', [])


def regenerate_on_entry(trainer, rng):
    """Return actor copy and receipt only on an eligible actual map entry.

    Parent canonical transfer processing calls this after applying accepted step
    changes. All groups, including excluded map groups, consume their original
    ordered uint16 modulo100draw, preserving the source sampling algorithm.
    Generated flags remain engine-private; receipts reveal only the counter.
    """
    rule = catalog()
    if trainer['map_id'] not in {row['map_id'] for row in rule['groups']}:
        return trainer, None
    if trainer.get('field_steps', {}).get('renewable', 0) < rule['threshold']:
        return trainer, None
    updated = copy.deepcopy(trainer)
    updated.setdefault('field_steps', {})['renewable'] = 0
    flags = []
    for group in rule['groups']:
        draw = rng.randrange(65536) % 100
        rarity = 'rare' if draw >= rule['rare_threshold'] else 'uncommon' if draw >= rule['uncommon_threshold'] else 'common'
        flags.extend(group[rarity])
    updated['collected_hidden_items'] = [flag for flag in trainer.get('collected_hidden_items', []) if flag not in renewable_flags()]
    generation = trainer.get('renewable_hidden_items', {}).get('generation', 0)+1
    updated['renewable_hidden_items'] = {'generation': generation, 'available_flags': sorted(set(flags))}
    receipt = {'generation': generation, 'trigger_map': trainer['map_id'], 'source': SOURCE,
               'step_threshold': rule['threshold'], 'adaptation': 'Renewable hidden flags and step counter belong to each trainer.'}
    updated['last_renewable_items'] = receipt
    return updated, receipt
