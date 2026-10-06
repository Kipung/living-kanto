"""Pinned hidden pickups and Itemfinder range, ranking and underfoot digging.

Each trainer owns their source hidden flags. Source hidden coins use Coin Case;
underfoot items are discovered only by using Itemfinder on their actual tile.
References: src/itemfinder.c; src/field_control_avatar.c; obtain_item.inc.
"""
import copy
import json
from functools import lru_cache
from ..mechanics.reference import REFERENCE
from ..mechanics.item_rules import ItemError, _consume
from ..mechanics.inventory import add, quantity

DIRECTIONS = {'north': (0, -1), 'south': (0, 1), 'west': (-1, 0), 'east': (1, 0)}
SOURCE = 'pret/pokefirered/src/itemfinder.c;src/field_control_avatar.c;data/scripts/obtain_item.inc'


@lru_cache(maxsize=256)
def _map_events(map_id):
    path = REFERENCE / 'data/maps' / map_id / 'map.json'
    return json.loads(path.read_text()) if path.exists() else None


def rows(game_map):
    source = _map_events(game_map.map_id)
    events = source if source is not None else game_map.events
    return [row for row in events.get('bg_events', []) if row.get('type') == 'hidden_item']


def is_unclaimed(trainer, row):
    from ..mechanics.renewable_items import available
    return available(trainer,row['flag']) and row['flag'] not in trainer.get('collected_hidden_items', [])


def front_candidates(trainer, game_map):
    if trainer.get('battle_id') or trainer.get('safari', {}).get('encounter'):
        return []
    dx, dy = DIRECTIONS.get(trainer.get('facing', 'south'), (0, 1))
    front = (trainer['x'] + dx, trainer['y'] + dy)
    elevation = int(game_map.cells.get((trainer['x'], trainer['y']), {}).get('elevation', 0))
    return [row for row in rows(game_map) if not row.get('underfoot') and is_unclaimed(trainer, row)
            and (row['x'], row['y']) == front
            and (not row.get('elevation') or not elevation or row['elevation'] == elevation)]


def collect(trainer, row, *, underfoot=False):
    if not is_unclaimed(trainer, row):
        raise ItemError('Hidden source item already collected')
    result = copy.deepcopy(trainer)
    count = 1 if underfoot else int(row.get('quantity', 1))
    item = row['item'].removeprefix('ITEM_')
    if item == 'NONE':
        if not quantity(result.get('inventory', {}), 'COIN_CASE'):
            raise ItemError('Hidden coins require Coin Case')
        coins = result.get('acquisition', {}).get('coins', 0)
        if coins + count > 9999:
            raise ItemError('Coin Case is full')
        result.setdefault('acquisition', {})['coins'] = coins + count
    else:
        result['inventory'] = add(result.get('inventory', {}), item, count)
    result.setdefault('collected_hidden_items', []).append(row['flag'])
    result['last_hidden_item'] = {'flag': row['flag'], 'item': item, 'quantity': count,
                                  'underfoot': underfoot, 'map_id': trainer['map_id'], 'source': SOURCE,
                                  'adaptation': 'Source collected hidden flags are owned per trainer.'}
    return result


def collection_changes(trainer, row, *, underfoot=False):
    updated = collect(trainer, row, underfoot=underfoot)
    return [{'op': 'set', 'path': f'humans.{trainer["human_id"]}.{key}', 'value': updated[key]}
            for key in ('inventory', 'acquisition', 'collected_hidden_items', 'last_hidden_item')
            if updated.get(key) != trainer.get(key)]


def _relative_connected(trainer, game_map, maps):
    """Project adjoining map edge tiles into the current source map coordinate space."""
    for connection in game_map.events.get('connections', []) or []:
        target = connection.get('map_name') or connection.get('map')
        other = maps.get(target)
        if other is None:
            other = next((m for m in maps.values() if m.reference_id == target), None)
        if other is None:
            continue
        offset = int(connection.get('offset', 0)); direction = connection['direction']
        for row in rows(other):
            if row.get('underfoot') or not is_unclaimed(trainer, row):
                continue
            x, y = row['x'], row['y']
            if direction == 'up': x, y = x + offset, y - other.height
            elif direction == 'down': x, y = x + offset, y + game_map.height
            elif direction == 'left': x, y = x - other.width, y + offset
            elif direction == 'right': x, y = x + game_map.width, y + offset
            else: continue
            if 0 <= x < game_map.width and 0 <= y < game_map.height:
                continue
            dx, dy = x - trainer['x'], y - trainer['y']
            if -7 <= dx <= 7 and -5 <= dy <= 5:
                yield (dx, dy, row)


def response(trainer, game_map, maps):
    candidates = []
    for row in rows(game_map):
        if not is_unclaimed(trainer, row):
            continue
        dx, dy = row['x'] - trainer['x'], row['y'] - trainer['y']
        if row.get('underfoot'):
            if dx == dy == 0:
                return {'response': 'underfoot', 'direction': 'underfoot', 'strength_beeps': 3}, row
        elif -7 <= dx <= 7 and -5 <= dy <= 5:
            candidates.append((dx, dy, row))
    # Source scans external tiles in x/y order, after current map event order.
    candidates += sorted(_relative_connected(trainer, game_map, maps), key=lambda entry: (entry[0], entry[1]))
    if not candidates:
        return {'response': 'none', 'direction': None, 'strength_beeps': 0}, None
    dx, dy, row = min(candidates, key=lambda entry: (abs(entry[0]) + abs(entry[1]), abs(entry[1]), -entry[1]))
    direction = ('east' if dx > 0 else 'west') if abs(dx) > abs(dy) else ('south' if dy > 0 else 'north')
    if dx == dy == 0:
        direction = 'underfoot'
    return {'response': 'nearby', 'direction': direction, 'strength_beeps': 4 if max(abs(dx), abs(dy)) <= 3 else 2}, None


def use_itemfinder(trainer, game_map, maps):
    if trainer.get('battle_id') or trainer.get('safari', {}).get('encounter'):
        raise ItemError('Itemfinder cannot be used during battle')
    updated = copy.deepcopy(trainer)
    _consume(updated, 'ITEMFINDER', amount=0)
    receipt, underfoot = response(trainer, game_map, maps)
    receipt.update(item='ITEMFINDER', source=SOURCE, map_id=trainer['map_id'], x=trainer['x'], y=trainer['y'], reusable=True)
    if underfoot:
        try:
            updated = collect(updated, underfoot, underfoot=True)
        except ItemError as exc:
            receipt['collection_error'] = str(exc)
        else:
            receipt['collected'] = copy.deepcopy(updated['last_hidden_item'])
    updated['last_itemfinder'] = receipt
    return updated, receipt
