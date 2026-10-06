"""Pinned FireRed party-wide flute and guaranteed wild escape bag items.

Sources: item_use.c:FieldUseFunc_PokeFlute/BattleUseFunc_PokeDoll;
battle_script_commands.c:VARIOUS_CHECK_POKEFLUTE; battle_scripts_2.s.
"""
import copy
from .item_rules import _item, _consume, ItemError

ESCAPE_ITEMS = ('POKE_DOLL', 'FLUFFY_TAIL')


def use_party_flute(trainer, party):
    if trainer.get('battle_id') or trainer.get('safari', {}).get('encounter'):
        raise ItemError('Field flute cannot be used during battle')
    if [p['pokemon_id'] for p in party] != trainer.get('party', []):
        raise ItemError('Flute requires the complete owned party')
    if any(p['owner_id'] != trainer['human_id'] for p in party):
        raise ItemError('Pokemon ownership mismatch')
    t = copy.deepcopy(trainer)
    _consume(t, 'POKE_FLUTE', amount=0)
    updated = copy.deepcopy(party)
    for pokemon in updated:
        if pokemon['hp'] > 0 and pokemon['status'] == 'slp':
            pokemon['status'] = ''
    return t, updated


def prepare_battle_special(trainer, item, *, wild, link_like=False):
    key = _item(item)
    if key not in ('POKE_FLUTE', *ESCAPE_ITEMS):
        raise ItemError('Unsupported special battle item')
    if link_like:
        raise ItemError('Source link-like battles prohibit bag items')
    if key in ESCAPE_ITEMS and not wild:
        raise ItemError('Escape item requires a wild battle')
    t = copy.deepcopy(trainer)
    _consume(t, key, amount=0 if key == 'POKE_FLUTE' else 1)
    return t, {'cure_party_sleep': True} if key == 'POKE_FLUTE' else {'guaranteed_escape': True}
