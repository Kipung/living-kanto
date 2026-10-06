"""Pinned FireRed bag pockets, PC item limits and atomic inventory transfers.

Positive stacks are counted; old zero-quantity entries remain harmless. Reading
an old save never migrates it or changes its hash. New gains obey source limits.
"""
import copy
import re
from functools import lru_cache
from .item_rules import ItemError, _item, item_catalog
from .reference import REFERENCE


@lru_cache(maxsize=1)
def limits():
    text = (REFERENCE / 'include/constants/global.h').read_text()
    constants = {key: int(n) for key, n in re.findall(r'#define (PC_ITEMS_COUNT|BAG_\w+_COUNT)\s+(\d+)', text)}
    return {'POCKET_ITEMS': constants['BAG_ITEMS_COUNT'], 'POCKET_KEY_ITEMS': constants['BAG_KEYITEMS_COUNT'],
            'POCKET_POKE_BALLS': constants['BAG_POKEBALLS_COUNT'], 'POCKET_TM_CASE': constants['BAG_TMHM_COUNT'],
            'POCKET_BERRY_POUCH': constants['BAG_BERRIES_COUNT'], 'pc': constants['PC_ITEMS_COUNT']}


def stacks(inventory):
    result = {}
    for name, row in inventory.items():
        amount = row.get('quantity', 0) if isinstance(row, dict) else row
        if type(amount) is not int or amount < 0:
            raise ItemError('Invalid inventory quantity')
        if amount:
            key = _item(name)
            if key == 'NONE':
                raise ItemError('Empty item cannot be owned')
            result[key] = result.get(key, 0) + amount
    return result


def quantity(inventory, item):
    return stacks(inventory).get(_item(item), 0)


def transferable(item):
    key = _item(item); row = item_catalog()[key]
    return key != 'NONE' and row.get('pocket') != 'POCKET_KEY_ITEMS' and not row.get('importance', 0) and row.get('pocket') in limits()


def add(inventory, item, amount, *, pc=False):
    if type(amount) is not int or not 1 <= amount <= 999:
        raise ItemError('Quantity must be an integer from 1 to 999')
    key = _item(item); counts = stacks(inventory); row = item_catalog()[key]
    pocket = row.get('pocket')
    if key == 'NONE' or pocket not in limits():
        raise ItemError('Item has no usable source pocket')
    if pc and not transferable(key):
        raise ItemError('Important and key items must stay in the bag')
    if counts.get(key, 0) + amount > 999:
        raise ItemError('Item stack is full (999)')
    used = len(counts) if pc else sum(item_catalog()[k].get('pocket') == pocket for k in counts)
    if key not in counts and used >= limits()['pc' if pc else pocket]:
        raise ItemError('PC item storage is full' if pc else 'Bag pocket is full')
    result = copy.deepcopy(inventory)
    # Collapse aliases of this item only, retaining unrelated legacy entries.
    for name in list(result):
        if _item(name) == key: result.pop(name)
    result[key.lower()] = {'item_id': key.lower(), 'quantity': counts.get(key, 0) + amount}
    # Source AddBagItem provisions these containers on the first acquisition.
    if not pc and pocket in ('POCKET_TM_CASE', 'POCKET_BERRY_POUCH'):
        container = 'TM_CASE' if pocket == 'POCKET_TM_CASE' else 'BERRY_POUCH'
        if not quantity(result, container): result = add(result, container, 1)
    return result


def remove(inventory, item, amount):
    if type(amount) is not int or not 1 <= amount <= 999:
        raise ItemError('Quantity must be an integer from 1 to 999')
    key = _item(item); count = quantity(inventory, key)
    if count < amount: raise ItemError('Insufficient item quantity')
    result = copy.deepcopy(inventory)
    for name in list(result):
        if _item(name) == key: result.pop(name)
    if count > amount: result[key.lower()] = {'item_id': key.lower(), 'quantity': count - amount}
    return result


def transfer_items(trainer, item, amount, *, deposit):
    if trainer.get('battle_id') or trainer.get('service_request') or trainer.get('activity'):
        raise ItemError('Trainer is busy')
    if not transferable(item): raise ItemError('Important and key items must stay in the bag')
    source, destination = ('inventory', 'pc_items') if deposit else ('pc_items', 'inventory')
    result = copy.deepcopy(trainer)
    result[source] = remove(result.get(source, {}), item, amount)
    result[destination] = add(result.get(destination, {}), item, amount, pc=deposit)
    return result


def validate_gains(before, after):
    """Check every authoritative bag gain, grandfathering unchanged legacy bags."""
    old, new = stacks(before), stacks(after)
    gains = {key: count - old.get(key, 0) for key, count in new.items() if count > old.get(key, 0)}
    for key, gain in gains.items():
        if new[key] > 999: raise ItemError('Item stack is full (999)')
        pocket = item_catalog()[key].get('pocket')
        if pocket not in limits(): raise ItemError('Item has no usable source pocket')
        count = sum(item_catalog()[k].get('pocket') == pocket for k in new)
        if key not in old and count > limits()[pocket]: raise ItemError('Bag pocket is full')


def sell_items(trainer, item, amount):
    key = _item(item); price = item_catalog()[key].get('price', 0) // 2
    if not transferable(key) or price < 1: raise ItemError('Item cannot be sold')
    result = copy.deepcopy(trainer)
    result['inventory'] = remove(result['inventory'], key, amount)
    result['money'] = min(999999, result['money'] + price * amount)
    return result
