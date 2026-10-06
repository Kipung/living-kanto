"""Fourteen source boxes with thirty slots, preserving legacy flat ownership.

Placements are optional metadata. Legacy and newly caught boxed individuals
receive deterministic free slots on read; only an accepted PC operation saves
the resolved layout. Reading never mutates an existing save.
"""
import copy
from .item_rules import ItemError
from .pokemon import heal

BOXES = 14
SLOTS = 30


def layout(trainer):
    saved = copy.deepcopy(trainer.get('pc_storage', {}))
    saved.setdefault('current_box', 1); saved.setdefault('names', {})
    known = saved.get('placements', {}); placements = {}; used = set()
    if len(set(trainer.get('box', []))) != len(trainer.get('box', [])):
        raise ItemError('Duplicate stored Pokemon identity')
    for pid in trainer.get('box', []):
        place = known.get(pid, {}); box, slot = place.get('box'), place.get('slot')
        if type(box) is int and type(slot) is int and 1 <= box <= BOXES and 1 <= slot <= SLOTS and (box, slot) not in used:
            placements[pid] = {'box': box, 'slot': slot}; used.add((box, slot))
    for pid in trainer.get('box', []):
        if pid in placements: continue
        cell = next(((b, s) for b in range(1, BOXES + 1) for s in range(1, SLOTS + 1) if (b, s) not in used), None)
        if cell is None: raise ItemError('Pokemon storage is full (420)')
        placements[pid] = {'box': cell[0], 'slot': cell[1]}; used.add(cell)
    saved['placements'] = placements
    if saved.get('selected_pokemon') not in trainer.get('party', []) + trainer.get('box', []): saved.pop('selected_pokemon', None)
    return saved


def free_slot(saved, box):
    if type(box) is not int or not 1 <= box <= BOXES: raise ItemError('Choose a box from 1 to 14')
    used = {row['slot'] for row in saved['placements'].values() if row['box'] == box}
    return next((slot for slot in range(1, SLOTS + 1) if slot not in used), None)


def usable(pokemon): return pokemon['hp'] > 0 and not pokemon.get('is_egg')


def deposit_allowed(trainer, pokemon, all_pokemon):
    pid = pokemon['pokemon_id']
    return (pid in trainer['party'] and pokemon['owner_id'] == trainer['human_id']
            and not pokemon.get('mail') and not pokemon.get('held_item', '').endswith('_MAIL')
            and any(usable(all_pokemon[other]) for other in trainer['party'] if other != pid)
            and len(trainer['box']) < BOXES * SLOTS)


def change(trainer, all_pokemon, action, args):
    if trainer.get('battle_id') or trainer.get('service_request') or trainer.get('activity'): raise ItemError('Trainer is busy')
    h = copy.deepcopy(trainer); saved = layout(h); updated = []
    pid = args.get('pokemon_id')
    if action in ('store_select_box', 'store_rename_box'):
        box = args.get('box'); free_slot(saved, box)
        if action == 'store_select_box':
            if set(args) != {'box'}: raise ItemError('Invalid box selection')
            saved['current_box'] = box
        else:
            if set(args) != {'box', 'text'} or not isinstance(args['text'], str) or not 1 <= len(args['text'].strip()) <= 8:
                raise ItemError('Box name must contain 1 to 8 characters')
            saved['names'][str(box)] = args['text'].strip()
    elif action == 'store_select_pokemon':
        if set(args) != {'pokemon_id'} or pid not in h['party'] + h['box']: raise ItemError('Owned individual required')
        saved['selected_pokemon'] = pid
    else:
        if pid not in h['party'] + h['box'] or all_pokemon[pid]['owner_id'] != h['human_id']: raise ItemError('Owned individual required')
        p = copy.deepcopy(all_pokemon[pid])
        if action == 'store_deposit':
            if set(args) - {'pokemon_id', 'box'} or not deposit_allowed(h, p, all_pokemon): raise ItemError('Cannot deposit last usable party Pokemon, mail, or full storage')
            box = args.get('box', saved['current_box']); slot = free_slot(saved, box)
            if slot is None:
                if 'box' in args: raise ItemError('Selected box is full')
                box = next((b for b in range(1, BOXES + 1) if free_slot(saved, b) is not None), None)
                if box is None: raise ItemError('Pokemon storage is full')
                slot = free_slot(saved, box)
            h['party'].remove(pid); h['box'].append(pid); saved['placements'][pid] = {'box': box, 'slot': slot}
            # BoxMonToMon resets condition; restoring source box PP on deposit
            # prevents storage from retaining battle injuries or depleted PP.
            heal(p); updated.append(p)
        elif action == 'store_withdraw':
            if set(args) != {'pokemon_id'} or pid not in h['box'] or len(h['party']) >= 6: raise ItemError('Party is full or individual not stored')
            h['box'].remove(pid); h['party'].append(pid); saved['placements'].pop(pid); heal(p); updated.append(p)
        elif action == 'store_move':
            if set(args) != {'pokemon_id', 'box'} or pid not in h['box']: raise ItemError('Stored individual and destination required')
            box = args['box']
            if saved['placements'][pid]['box'] == box: raise ItemError('Individual is already in that box')
            slot = free_slot(saved, box)
            if slot is None: raise ItemError('Selected box is full')
            saved['placements'][pid] = {'box': box, 'slot': slot}
        elif action == 'store_swap':
            other = args.get('party_pokemon_id')
            if set(args) != {'pokemon_id', 'party_pokemon_id'} or pid not in h['box'] or other not in h['party']:
                raise ItemError('Choose one stored and one party individual')
            outgoing = all_pokemon[other]
            if outgoing['owner_id'] != h['human_id'] or outgoing.get('mail') or outgoing.get('held_item', '').endswith('_MAIL'):
                raise ItemError('Cannot store mail or another trainer’s Pokemon')
            if not usable(p) and not any(usable(all_pokemon[i]) for i in h['party'] if i != other): raise ItemError('Party must retain a usable Pokemon')
            place = saved['placements'].pop(pid); saved['placements'][other] = place
            h['party'][h['party'].index(other)] = pid; h['box'][h['box'].index(pid)] = other
            outgoing = copy.deepcopy(outgoing); heal(outgoing); heal(p); updated.extend((p, outgoing))
        else: raise ItemError('Unknown PC operation')
    h['pc_storage'] = saved
    return h, updated
