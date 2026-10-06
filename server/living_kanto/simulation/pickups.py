"""Source item balls with per-trainer repeatable collection.

Adaptation: each trainer may collect each source item ball once. This avoids
another trainer permanently consuming an essential progression item. It is
declared explicitly; these are not globally scarce shared dropped items.
"""
import copy
from functools import lru_cache
import re
from ..contracts.human import LegalAction
from ..mechanics.reference import REFERENCE


@lru_cache(maxsize=1)
def source_items():
    text = (REFERENCE / 'data/scripts/item_ball_scripts.inc').read_text()
    result = {label: (item.lower(), int(amount or 1))
            for label, item, amount in re.findall(
                r'(\w+)::\s*\n\s*finditem ITEM_(\w+)(?:,\s*(\d+))?', text)}
    # The excluded Rocket campaign normally reveals this source item ball.
    # Shared-world adaptation: it is physically available once per trainer;
    # no scripted grunt victory is invented. Other custom rewards keep their
    # own scenario/battle gates rather than being parsed as unconditional gifts.
    label = 'RocketHideout_B4F_EventScript_LiftKey'
    script = (REFERENCE / 'data/maps/RocketHideout_B4F/scripts.inc').read_text()
    body = re.search(r'(?m)^' + label + r'::\n(.*?)(?=^\w+::|\Z)', script, re.S)
    gift = re.search(r'\bgiveitem ITEM_(\w+)(?:,\s*(\d+))?', body.group(1)) if body else None
    if not gift:
        raise ValueError('Pinned Lift Key item-ball script is unresolved')
    result[label] = (gift.group(1).lower(), int(gift.group(2) or 1))
    return result


def candidates(human, game_map):
    collected = set(human.get('collected_source_items', []))
    result = []
    for index, obj in enumerate(game_map.events.get('object_events', [])):
        script = obj.get('script')
        if obj.get('graphics_id') != 'OBJ_EVENT_GFX_ITEM_BALL' or script not in source_items():
            continue
        key = f'{game_map.map_id}:{obj.get("local_id", index)}:{script}'
        if key in collected or abs(obj['x'] - human['x']) + abs(obj['y'] - human['y']) > 1:
            continue
        item, quantity = source_items()[script]
        result.append((key, item, quantity, script))
    return result


def actions(human, game_map):
    from .hidden_items import front_candidates
    hidden = [LegalAction(action='pick_up_item', arguments={'object_id': 'hidden:' + row['flag']},
                         known_consequences={'searches_facing_tile': True, 'per_trainer_once': True})
              for row in front_candidates(human, game_map)]
    return hidden + [LegalAction(action='pick_up_item', arguments={'object_id': key},
                        known_consequences={'item': item, 'quantity': quantity,
                                            'source_script': script, 'per_trainer_once': True})
            for key, item, quantity, script in candidates(human, game_map)]


def changes(human, game_map, arguments):
    from .hidden_items import front_candidates, collection_changes
    hidden = next((row for row in front_candidates(human, game_map)
                   if arguments == {'object_id': 'hidden:' + row['flag']}), None)
    if hidden is not None:return collection_changes(human, hidden)
    match = next((entry for entry in candidates(human, game_map)
                  if arguments == {'object_id': entry[0]}), None)
    if match is None:
        raise ValueError('Source item is unavailable, out of reach, or already collected')
    key, item, quantity, script = match
    inventory = copy.deepcopy(human['inventory'])
    entry = inventory.setdefault(item, {'item_id': item, 'quantity': 0})
    entry['quantity'] += quantity
    prefix = f'humans.{human["human_id"]}'
    return [{'op': 'set', 'path': prefix + '.inventory', 'value': inventory},
            {'op': 'set', 'path': prefix + '.collected_source_items',
             'value': human.get('collected_source_items', []) + [key]}]
