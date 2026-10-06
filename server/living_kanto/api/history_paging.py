"""Bounded observer history pages; history remains canonical and complete."""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Literal

from fastapi import HTTPException, Query

from ..store import StoreError
from ..store.storage_layout import unpack

PATTERNS = {
    'interactions': re.compile(r'talk|dialog|social|relationship|trade|challenge|interaction'),
    'pokemon': re.compile(r'pokemon|battle|capture|catch|heal|move.learn|evol'),
    'travel': re.compile(r'moved|travel|map|warp'),
    'progress': re.compile(r'inventory|item|badge|money|purchase|gym|league|champion'),
}


def mentions(value, ids):
    if isinstance(value, str):
        return value in ids
    if isinstance(value, list):
        return any(mentions(item, ids) for item in value)
    if isinstance(value, dict):
        return any(key in ids or mentions(item, ids) for key, item in value.items())
    return False


def clock_only(event):
    inputs = event.get('deterministic_inputs') or {}
    return (event.get('event_kind') == 'world.shared_tick'
            and not inputs.get('activity_completions')
            and all(not row.get('event_kind') or row['event_kind'] in ('human.moved', 'human.entered_map')
                    for row in inputs.get('routes', [])))


def place(value):
    return re.sub(r'([a-z])([A-Z])', r'\1 \2', str(value or '').replace('_', ' / '))


def event_text(event, humans):
    """Mirror client/live/model.mjs display text so name searches stay useful."""
    inputs = event.get('deterministic_inputs') or {}
    cause = event.get('causation') or {}
    routes = inputs.get('routes') or []
    decisions = cause.get('decisions') or []
    name = lambda ident: humans.get(ident, {}).get('name') or ident
    if event.get('event_kind') == 'world.shared_tick':
        names = [name(row.get('human_id')) for row in routes]
        label = ' · '.join(names) + ' advanced together' if names else 'Shared time advanced'
        return label + ' · ' + str((inputs.get('shared_time') or {}).get('elapsed', 0)) + 's'
    if decisions:
        return ' · '.join(str(name(row.get('human_id'))) + (' started resting' if row.get('action') == 'rest' else ' started work') for row in decisions)
    actor = (routes[0].get('human_id') if routes else None) or cause.get('human_id') or cause.get('actor_id')
    who = humans.get(actor, {}).get('name') or 'World'
    action = cause.get('action') or event.get('event_kind', '')
    args = cause.get('action_arguments') or {}
    target = humans.get(args.get('human_id'), {}).get('name')
    labels = {'talk_to': 'chatted' + (' with ' + target if target else ''), 'work': 'started work',
              'rest': 'started resting', 'journey_to': 'travelled', 'travel_to': 'walked',
              'walk_to': 'walked', 'enter_map': 'entered a building', 'train': 'found a wild encounter',
              'battle_move': 'chose a battle move', 'battle_turn': 'chose battle actions',
              'choose_starter': 'received a starter', 'shop_buy': 'ordered ' + place(args.get('item')),
              'heal_party': 'requested healing', 'serve': 'served a customer',
              'remember': 'recorded a memory', 'set_goal': 'set a goal'}
    kind = event.get('event_kind')
    label = 'started a battle' if kind == 'battle.started' else 'finished a battle' if kind == 'battle.ended' else labels.get(action, str(action).replace('_', ' ').replace('.', ' '))
    position = (event.get('after') or {}).get('position')
    return who + ' ' + label + (' · ' + place(position.get('map_id')) if position else '')


def history_page(store, run_id, human_id, before=None, limit=50, search='', category='all'):
    if not 1 <= limit <= 100 or category not in ('all', *PATTERNS) or (before is not None and before < 0):
        raise ValueError('Invalid history pagination parameters')
    # Obtain a verified snapshot, then release the writer lock before scanning.
    _, state, _ = store.load_run(run_id)
    humans = state.humans
    human = humans.get(human_id)
    if human is None and human_id not in state.npcs:
        raise HTTPException(404, 'Person not found')
    human = human or {}
    owned = set(human.get('party') or []) | set(human.get('box') or [])
    ids = {human_id} | {ident for ident, pokemon in state.pokemon.items()
                        if pokemon.get('owner_id') == human_id or ident in owned}
    through = state.state_version
    upper = min(before, through) if before is not None else through
    matches = []
    needle = search.lower()
    # A separate read-only snapshot does not hold the RunStore writer lock.
    connection = sqlite3.connect(Path(store.path).resolve().as_uri() + '?mode=ro', uri=True)
    try:
        cursor = connection.execute('SELECT event_json FROM events WHERE run_id=? AND event_index<? ORDER BY event_index DESC', (run_id, upper))
        for (payload,) in cursor:
            event = unpack(payload)
            if clock_only(event) or not mentions(event, ids):
                continue
            serialized = json.dumps(event, ensure_ascii=False, separators=(',', ':'))
            if category != 'all' and not PATTERNS[category].search(serialized):
                continue
            if needle and needle not in serialized.lower() and needle not in event_text(event, humans).lower():
                continue
            matches.append(event)
            if len(matches) > limit:
                break
    finally:
        connection.close()
    has_more = len(matches) > limit
    events = matches[:limit]
    return {'events': events, 'next_before': events[-1]['event_index'] if has_more else None,
            'has_more': has_more, 'through_version': through}


def install_history_paging(app, open_store):
    @app.get('/runs/{run_id}/history')
    def get_history(run_id: str, human_id: str, before: int | None = Query(None, ge=0),
                    limit: int = Query(50, ge=1, le=100), search: str = Query('', max_length=500),
                    category: Literal['all', 'interactions', 'pokemon', 'travel', 'progress'] = 'all'):
        try:
            return history_page(open_store(run_id), run_id, human_id, before, limit, search, category)
        except StoreError as exc:
            raise HTTPException(404, str(exc)) from exc
