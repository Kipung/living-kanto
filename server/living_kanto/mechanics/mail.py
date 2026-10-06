"""Pure source-mail lifecycle; caller commits returned entities atomically.

Sources: mail.h (12 stationery types and nine composer words), mail_data.c
(GiveMailToMon, TakeMailFromMon2), constants/global.h (10 PC letters), and
trade_scene.c:1060–1079 (a traded individual carries its existing letter).
Adaptation: AI authors write 1–200 free-text characters instead of nine fixed
phrase words. Authorship/species are snapshots and never change on transfer.
PC proximity and service availability are checked by the gameplay caller.
"""
import copy
import re
from functools import lru_cache
from .item_rules import ItemError, _item
from .inventory import add, remove, stacks
from .reference import REFERENCE
from ..contracts.human import LegalAction


@lru_cache(maxsize=1)
def mail_types():
    source = (REFERENCE / 'include/mail.h').read_text()
    macro = source.split('#define IS_ITEM_MAIL', 1)[1].split('#define FIRST_MAIL_IDX', 1)[0]
    return tuple(dict.fromkeys(re.findall(r'ITEM_(\w+_MAIL)', macro)))


@lru_cache(maxsize=1)
def mailbox_capacity():
    source = (REFERENCE / 'include/constants/global.h').read_text()
    # Source reserves PARTY_SIZE letter records for the party, then ten for PC.
    match = re.search(r'#define MAIL_COUNT\s+\(PARTY_SIZE\s*\+\s*(\d+)\)', source)
    if not match:
        raise ItemError('Pinned mail capacity definition is unsupported')
    return int(match.group(1))


def _actor(trainer):
    return trainer.get('human_id', trainer.get('actor_id', trainer.get('id')))


def _party(trainer, pokemon):
    if not _actor(trainer) or pokemon.get('owner_id') != _actor(trainer):
        raise ItemError('Mail requires an owned individual')
    if pokemon.get('pokemon_id') not in trainer.get('party', []):
        raise ItemError('Mail requires a party individual, not PC storage')
    if pokemon.get('is_egg') or pokemon.get('egg'):
        raise ItemError('Eggs cannot carry mail')


def _available(trainer):
    if trainer.get('battle_id') or trainer.get('service_request') or trainer.get('activity'):
        raise ItemError('Trainer is busy')


def _letter(pokemon):
    letter = pokemon.get('mail')
    if not isinstance(letter, dict) or not letter.get('mail_id') or letter.get('item') not in mail_types():
        raise ItemError('Individual carries no written mail')
    if _item(pokemon.get('held_item', 'NONE') or 'NONE') != letter['item']:
        raise ItemError('Attached mail and held stationery disagree')
    return letter


def _mailbox(trainer):
    box = trainer.get('mailbox', {})
    if not isinstance(box, dict):
        raise ItemError('Invalid PC mailbox')
    return box


def _return_held(trainer, pokemon):
    held = pokemon.get('held_item')
    if pokemon.get('mail') or held and _item(held) in mail_types():
        raise ItemError('Take the existing mail to PC or explicitly discard it first')
    if held and _item(held) != 'NONE':
        trainer['inventory'] = add(trainer.get('inventory', {}), held, 1)


def write_mail(trainer, pokemon, item, text, *, mail_id):
    _available(trainer); _party(trainer, pokemon)
    if not isinstance(item, str): raise ItemError('Mail item must be a source identifier')
    key = _item(item)
    if key not in mail_types():
        raise ItemError('Choose a source mail stationery item')
    if not isinstance(text, str) or not text.strip() or len(text) > 200:
        raise ItemError('Mail text must contain 1–200 characters')
    if not isinstance(mail_id, str) or not mail_id or len(mail_id) > 128 or '.' in mail_id or mail_id in _mailbox(trainer):
        raise ItemError('A fresh stable mail identifier is required')
    t, p = copy.deepcopy(trainer), copy.deepcopy(pokemon)
    # Removing stationery before returning the old held item frees its bag slot.
    t['inventory'] = remove(t.get('inventory', {}), key, 1)
    _return_held(t, p)
    letter = {'mail_id': mail_id, 'item': key, 'text': text,
              'author_id': _actor(trainer), 'author_name': trainer.get('name', _actor(trainer)),
              'species': pokemon.get('species')}
    p['mail'] = letter; p['held_item'] = key
    return t, p, {'kind': 'mail.written', 'mail_id': mail_id, 'pokemon_id': p['pokemon_id'],
                  'author_id': _actor(t), 'item': key, 'text_adaptation': 'free_text_200'}


def read_mail(trainer, pokemon):
    _party(trainer, pokemon)
    return copy.deepcopy(_letter(pokemon))


def mail_to_pc(trainer, pokemon):
    _available(trainer); _party(trainer, pokemon)
    letter = _letter(pokemon); box = _mailbox(trainer)
    if len(box) >= mailbox_capacity():
        raise ItemError('PC mailbox is full (10 letters)')
    if letter['mail_id'] in box:
        raise ItemError('Letter is already in the mailbox')
    t, p = copy.deepcopy(trainer), copy.deepcopy(pokemon)
    t.setdefault('mailbox', {})[letter['mail_id']] = copy.deepcopy(letter)
    p.pop('mail', None); p['held_item'] = ''
    return t, p, {'kind': 'mail.deposited', 'mail_id': letter['mail_id'], 'pokemon_id': p['pokemon_id']}


def mail_attach(trainer, pokemon, mail_id):
    _available(trainer); _party(trainer, pokemon)
    letter = _mailbox(trainer).get(mail_id)
    if not isinstance(letter, dict) or letter.get('mail_id') != mail_id or letter.get('item') not in mail_types():
        raise ItemError('PC letter unavailable')
    t, p = copy.deepcopy(trainer), copy.deepcopy(pokemon)
    _return_held(t, p)
    p['mail'] = copy.deepcopy(letter); p['held_item'] = letter['item']
    t['mailbox'].pop(mail_id)
    return t, p, {'kind': 'mail.attached', 'mail_id': mail_id, 'pokemon_id': p['pokemon_id']}


def mail_discard(trainer, *, pokemon=None, mail_id=None, discard_mail=False):
    _available(trainer)
    if discard_mail is not True:
        raise ItemError('Deleting letter text requires explicit discard_mail=true')
    if (pokemon is None) == (mail_id is None):
        raise ItemError('Choose exactly one attached or PC letter')
    if pokemon is not None:
        _party(trainer, pokemon); letter = _letter(pokemon)
    else:
        letter = _mailbox(trainer).get(mail_id)
        if not isinstance(letter, dict) or letter.get('mail_id') != mail_id or letter.get('item') not in mail_types():
            raise ItemError('PC letter unavailable')
    t = copy.deepcopy(trainer)
    t['inventory'] = add(t.get('inventory', {}), letter['item'], 1)
    p = copy.deepcopy(pokemon) if pokemon is not None else None
    if p is not None:
        p.pop('mail', None); p['held_item'] = ''
    else:
        t['mailbox'].pop(mail_id)
    return t, p, {'kind': 'mail.discarded', 'mail_id': letter['mail_id'], 'text_deleted': True,
                  'stationery_returned': letter['item']}


def propose_mail(trainer, pokemon_map, action, arguments, *, new_mail_id=None):
    """Strict proposal dispatcher: trainer copy, individual updates, factual detail."""
    args = dict(arguments); pid = args.get('pokemon_id')
    if pid is not None and not isinstance(pid, str): raise ItemError('Invalid individual identifier')
    if 'mail_id' in args and not isinstance(args['mail_id'], str): raise ItemError('Invalid mail identifier')
    pokemon = pokemon_map.get(pid)
    if action == 'write_mail' and set(args) == {'pokemon_id', 'item', 'text'} and pokemon:
        # IDs must be unique among every attached letter, not only this mailbox.
        if any((p.get('mail') or {}).get('mail_id') == new_mail_id for p in pokemon_map.values()):
            raise ItemError('Mail identifier is already attached to an individual')
        t, p, event = write_mail(trainer, pokemon, args['item'], args['text'], mail_id=new_mail_id)
    elif action == 'read_mail' and set(args) == {'pokemon_id'} and pokemon:
        return copy.deepcopy(trainer), {}, {'kind': 'mail.read', 'contents': read_mail(trainer, pokemon)}
    elif action == 'read_mail' and set(args) == {'mail_id'}:
        letter = _mailbox(trainer).get(args['mail_id'])
        if not isinstance(letter, dict): raise ItemError('PC letter unavailable')
        return copy.deepcopy(trainer), {}, {'kind': 'mail.read', 'contents': copy.deepcopy(letter)}
    elif action == 'mail_to_pc' and set(args) == {'pokemon_id'} and pokemon:
        t, p, event = mail_to_pc(trainer, pokemon)
    elif action == 'mail_attach' and set(args) == {'pokemon_id', 'mail_id'} and pokemon:
        if any((p.get('mail') or {}).get('mail_id') == args['mail_id'] for p in pokemon_map.values()):
            raise ItemError('PC letter is already attached to an individual')
        t, p, event = mail_attach(trainer, pokemon, args['mail_id'])
    elif action == 'mail_discard' and set(args) in ({'pokemon_id', 'discard_mail'}, {'mail_id', 'discard_mail'}):
        if pid is not None and not pokemon: raise ItemError('Individual unavailable')
        t, p, event = mail_discard(trainer, pokemon=pokemon, mail_id=args.get('mail_id'), discard_mail=args['discard_mail'])
    else:
        raise ItemError('Invalid mail action arguments')
    return t, ({p['pokemon_id']: p} if p else {}), event


def mail_actions(state, human_id, *, at_pc=False):
    trainer = state.humans[human_id]; actions = []
    if trainer.get('battle_id') or trainer.get('service_request') or trainer.get('activity'):
        return actions
    try: blank = {key: amount for key, amount in stacks(trainer.get('inventory', {})).items() if key in mail_types()}
    except ItemError: blank = {}
    for pid in trainer.get('party', []):
        pokemon = state.pokemon.get(pid)
        if not pokemon: continue
        try: _party(trainer, pokemon)
        except ItemError: continue
        if pokemon.get('mail'):
            try: read_mail(trainer, pokemon)
            except ItemError: continue
            actions.append(LegalAction(action='read_mail', arguments={'pokemon_id': pid}, known_consequences={'reads_own_letter': True}))
            if at_pc:
                try: mail_to_pc(trainer, pokemon)
                except ItemError: pass
                else: actions.append(LegalAction(action='mail_to_pc', arguments={'pokemon_id': pid}, known_consequences={'preserves_letter_text': True}))
            try: mail_discard(trainer, pokemon=pokemon, discard_mail=True)
            except ItemError: pass
            else: actions.append(LegalAction(action='mail_discard', arguments={'pokemon_id': pid, 'discard_mail': True}, known_consequences={'permanently_deletes_text': True, 'returns_blank_stationery': True}))
            continue
        for key in blank:
            try: write_mail(trainer, pokemon, key, 'Capacity check', mail_id='mail-capacity-check')
            except ItemError: continue
            actions.append(LegalAction(action='write_mail', arguments={'pokemon_id': pid, 'item': key, 'text': '<letter text: 1–200 characters>'}, known_consequences={'consumes_blank_mail': True, 'replaces_held_item_into_bag': bool(pokemon.get('held_item')), 'message_format': 'free_text_200'}))
        if at_pc:
            for mail_id in _mailbox(trainer):
                try: mail_attach(trainer, pokemon, mail_id)
                except ItemError: continue
                actions.append(LegalAction(action='mail_attach', arguments={'pokemon_id': pid, 'mail_id': mail_id}, known_consequences={'removes_letter_from_pc': True, 'preserves_original_author': True}))
    if at_pc:
        for mail_id in _mailbox(trainer):
            actions.append(LegalAction(action='read_mail', arguments={'mail_id': mail_id}, known_consequences={'reads_pc_letter': True}))
            try: mail_discard(trainer, mail_id=mail_id, discard_mail=True)
            except ItemError: continue
            actions.append(LegalAction(action='mail_discard', arguments={'mail_id': mail_id, 'discard_mail': True}, known_consequences={'permanently_deletes_text': True, 'returns_blank_stationery': True}))
    return actions
