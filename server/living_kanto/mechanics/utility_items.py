"""Shared-world VS Seeker rematch invitations and private Fame Checker notebook.

Cartridge source movement charge/range is preserved; rematches require actual
entity decisions. Fame facts are snapshots of public residents the user saw.
"""
import copy
import json
import re
from functools import lru_cache
from .item_rules import ItemError, _consume
from .inventory import quantity
from .reference import REFERENCE

VS_ADAPTATION = ('VS Seeker addresses nearby persistent entities after a completed encounter between those trainers. '
                 'Each rematch requires a fresh accepted human decision and uses the existing personal-duel rules; '
                 'no scripted willingness, promoted team, XP or prize is awarded. Invitations expire after 100 actual walking tiles '
                 'or departure from the source map. Source charge of 100 and detection rectangle 7 by 5 are preserved.')
FAME_ADAPTATION = ('Fame Checker stores only public identity, role, place last observed and public badge records '
                   'of visible canonical residents. It does not disclose private biographies, goals, parties or memories. '
                   'Setup offices remain declared setup facts, distinct from earned badge records.')


def _ready(trainer, item):
    if trainer.get('battle_id') or trainer.get('safari', {}).get('encounter'):
        raise ItemError('Utility item cannot be used during battle')
    updated = copy.deepcopy(trainer)
    _consume(updated, item, amount=0)
    return updated


@lru_cache(maxsize=256)
def map_type(map_id):
    path = REFERENCE / 'data/maps' / map_id / 'map.json'
    return json.loads(path.read_text()).get('map_type') if path.exists() else None


def vs_charge(trainer):
    utility = trainer.get('utility_items', {})
    baseline = utility.get('vs_used_walked', trainer.get('acquisition', {}).get('vs_acquired_walked', 0))
    return min(100, max(0, trainer.get('field_steps', {}).get('walked', 0) - baseline))


def invitation_live(state, offer):
    if offer.get('source') != 'vs_seeker':
        return True
    proposer = state.humans.get(offer['proposer'])
    recipient = state.humans.get(offer['recipient'])
    return bool(proposer and recipient and proposer['map_id'] == offer['source_map'] == recipient['map_id']
                and proposer.get('field_steps', {}).get('walked', 0) < offer['expires_walked']
                and all(state.humans[actor].get('map_visit', 0)==epoch for actor,epoch in offer.get('map_visits', {}).items()))


def _previous_opponents(state, hid):
    # The engine's completed duel records are factual; subjective claims never qualify.
    return {record['opponent'] if record['challenger'] == hid else record['challenger']
            for record in state.world_facts.get('battles', {}).values()
            if record.get('ended') and not record.get('wild') and hid in (record.get('challenger'), record.get('opponent'))
            and record.get('outcome') in (record.get('challenger'), record.get('opponent'))}


def vs_candidates(state, trainer):
    hid = trainer['human_id']; previously_fought = _previous_opponents(state, hid)
    if not trainer.get('party') or not any(state.pokemon[p]['hp'] > 0 for p in trainer['party'] if p in state.pokemon):
        return []
    candidates = []
    for oid, other in sorted(state.humans.items()):
        if oid not in previously_fought or oid == hid or other['map_id'] != trainer['map_id']:
            continue
        if abs(other['x'] - trainer['x']) > 7 or abs(other['y'] - trainer['y']) > 5:
            continue
        if other.get('battle_id') or other.get('activity') or other.get('service_request') or other.get('safari', {}).get('encounter'):
            continue
        if not other.get('party') or not any(state.pokemon[p]['hp'] > 0 for p in other['party'] if p in state.pokemon):
            continue
        candidates.append(oid)
    return candidates


def use_vs_seeker(state, trainer):
    updated = _ready(trainer, 'VS_SEEKER')
    if map_type(trainer['map_id']) not in ('MAP_TYPE_ROUTE', 'MAP_TYPE_CITY', 'MAP_TYPE_TOWN') or trainer['map_id'] == 'ViridianForest':
        raise ItemError('VS Seeker requires an outdoor town, city or route')
    charge = vs_charge(trainer)
    receipt = {'item': 'VS_SEEKER', 'charge': charge, 'source': 'pret/pokefirered/src/vs_seeker.c;src/item_use.c:FieldUseFunc_VsSeeker',
               'adaptation': VS_ADAPTATION, 'invitations': []}
    offers = copy.deepcopy(state.world_facts.get('trainer_challenges', {}))
    if charge < 100:
        receipt.update(response='not_charged', steps_remaining=100-charge)
    else:
        candidates = vs_candidates(state, trainer)
        if not candidates:
            receipt['response'] = 'no_rematch_entities_in_range'
        else:
            walked = trainer.get('field_steps', {}).get('walked', 0)
            updated.setdefault('utility_items', {})['vs_used_walked'] = walked
            for target in candidates:
                # Preserve other pending interactions; one VS invitation per pair.
                existing = next((key for key, offer in offers.items() if offer['status'] == 'pending'
                                 and {offer['proposer'], offer['recipient']} == {trainer['human_id'], target}
                                 and invitation_live(state, offer)), None)
                if existing:
                    receipt['invitations'].append(existing)
                    continue
                key = f'vs-{state.state_version}-{trainer["human_id"]}-{target}'
                offers[key] = {'proposer': trainer['human_id'], 'recipient': target, 'doubles': False, 'status': 'pending',
                               'source': 'vs_seeker', 'source_map': trainer['map_id'], 'expires_walked': walked+100,
                               'map_visits': {actor:state.humans[actor].get('map_visit', 0) for actor in (trainer['human_id'], target)},
                               'adaptation': VS_ADAPTATION}
                receipt['invitations'].append(key)
            receipt.update(response='invitations_sent', charge=0)
    updated['last_vs_seeker'] = receipt
    return updated, offers, receipt


@lru_cache(maxsize=1)
def fame_names():
    source = (REFERENCE / 'src/fame_checker.c').read_text()
    tokens = set(re.findall(r'\[FAMECHECKER_(\w+)\]\s*=', source.split('static const u16 sTrainerIdxs[] = {')[1].split('};')[0]))
    names = {'OAK': 'Professor Oak', 'DAISY': 'Daisy', 'BROCK': 'Brock', 'MISTY': 'Misty', 'LTSURGE': 'Lt. Surge',
             'ERIKA': 'Erika', 'KOGA': 'Koga', 'SABRINA': 'Sabrina', 'BLAINE': 'Blaine', 'LORELEI': 'Lorelei',
             'BRUNO': 'Bruno', 'AGATHA': 'Agatha', 'LANCE': 'Lance', 'BILL': 'Bill', 'MRFUJI': 'Mr. Fuji', 'GIOVANNI': 'Giovanni'}
    return {names[token] for token in tokens}


def use_fame_checker(state, trainer, *, vision_radius=6):
    updated = _ready(trainer, 'FAME_CHECKER')
    records = copy.deepcopy(trainer.get('utility_items', {}).get('fame_records', {}))
    for oid, other in sorted(state.humans.items()):
        if other.get('name') not in fame_names() or oid == trainer['human_id'] or other['map_id'] != trainer['map_id']:
            continue
        if abs(other['x']-trainer['x']) > vision_radius or abs(other['y']-trainer['y']) > vision_radius:
            continue
        records[oid] = {'human_id': oid, 'name': other['name'], 'public_role': other.get('role', 'resident'),
                        'last_observed_map': trainer['map_id'], 'observed_at': state.simulated_time,
                        'public_badges': copy.deepcopy(other.get('badges', [])),
                        'office_provenance': 'declared_initial_setup' if other.get('setup_role') in ('gym_leader','elite_four','professor') else 'public_observation'}
    updated.setdefault('utility_items', {})['fame_records'] = records
    receipt = {'item': 'FAME_CHECKER', 'residents': list(records.values()), 'source': 'pret/pokefirered/src/fame_checker.c:sTrainerIdxs',
               'adaptation': FAME_ADAPTATION, 'reusable': True}
    updated['last_fame_checker'] = receipt
    return updated, receipt


@lru_cache(maxsize=1)
def _cartography():
    sections = {row['id']:row for row in json.loads((REFERENCE/'src/data/region_map/region_map_sections.json').read_text())['map_sections']}
    maps = {row['name']:row for path in (REFERENCE/'data/maps').glob('*/map.json') for row in [json.loads(path.read_text())]}
    return maps, sections


def use_town_map(trainer, supported_maps):
    updated = _ready(trainer, 'TOWN_MAP')
    source_maps, sections = _cartography()
    visited = set(trainer.get('field', {}).get('visited_maps', [])) | {trainer['map_id']}
    seen_sections = {source_maps[mid]['region_map_section'] for mid in visited if mid in source_maps}
    section_ids = {source_maps[mid]['region_map_section'] for mid in supported_maps if mid in source_maps}
    locations = [{**copy.deepcopy(sections[key]),'visited':key in seen_sections}
                 for key in sorted(section_ids) if key in sections and 'x' in sections[key]]
    here = source_maps.get(trainer['map_id'], {})
    receipt = {'item':'TOWN_MAP','locations':locations,'you':{'map_id':trainer['map_id'],
               'section':here.get('region_map_section'),'x':trainer['x'],'y':trainer['y']},'reusable':True,
               'source':'pret/pokefirered/src/region_map.c;src/data/region_map/region_map_sections.json',
               'adaptation':'Public source cartography and own visited places only; live entities and hidden encounters are not included.'}
    updated['last_town_map'] = receipt
    return updated, receipt


TEACHY_TOPICS = ('battle','status','matchups','catching','tms','register')
LESSONS = {
    'battle': 'Use your Pokémon and permitted moves to reduce the opposing Pokémon HP. A Pokémon at zero HP cannot battle; heal it at a Pokémon Center. The engine resolves each selected move and its PP.',
    'status': 'Poison, paralysis, sleep, burns and freezing can impair Pokémon. Poison and paralysis persist after battle; field poison also hurts while walking. Use a suitable owned remedy or visit a Pokémon Center.',
    'matchups': 'Pokémon and moves have types. Compare the attacking move type against the defending Pokémon types: some combinations are effective, resisted or ineffective. Choose moves using the information revealed in your battle observation.',
    'catching': 'Catch wild Pokémon with owned Poké Balls. Weaken the target without making it faint; sleep or paralysis can help. A failed ball still consumes the ball and a turn. Another trainer’s Pokémon cannot be caught.',
    'tms': 'A compatible TM teaches a move and is consumed; HMs are reusable. Read the move description and choose a species that can learn it. Pokémon know up to four moves; replacing an HM move requires the Move Deleter.',
    'register': 'Register an eligible owned key item with register_item for its shortcut; unregister_item clears it. Registration gives quick access and preserves the item’s usual restrictions, effects and consumption.'}


def teachy_topics(trainer):
    return TEACHY_TOPICS if quantity(trainer.get('inventory', {}), 'TM_CASE') else TEACHY_TOPICS[:4]


def use_teachy_tv(trainer, topic):
    updated = _ready(trainer, 'TEACHY_TV')
    if topic not in teachy_topics(trainer):raise ItemError('Teachy TV topic unavailable: choose a source topic; TM Case unlocks TM and registration lessons')
    # Source headings are read rather than invented, while lessons paraphrase
    # source teachings for this world's existing semantic action controls.
    names = {'battle':'TeachBattle','status':'StatusProblems','matchups':'TypeMatchups','catching':'CatchPkmn','tms':'AboutTMs','register':'RegisterItem'}
    text = (REFERENCE/'src/data/text/teachy_tv.h').read_text()
    title = re.search(r'gTeachyTvString_'+names[topic]+r'\[\]\s*=\s*_\("([^"]+)"\)',text).group(1)
    receipt = {'item':'TEACHY_TV','topic':topic,'title':title,'lesson':LESSONS[topic],'reusable':True,
               'source':'pret/pokefirered/src/data/text/teachy_tv.h;src/teachy_tv.c:TeachyTvSetupWindow',
               'adaptation':'Source lessons use semantic action controls. Demonstrations are informational; no canonical Pokémon, battle result, XP or reward is created.'}
    learned = updated.setdefault('utility_items', {}).setdefault('teachy_topics', [])
    if topic not in learned:learned.append(topic)
    updated['last_teachy_tv'] = receipt
    return updated, receipt


def use_powder_jar(trainer):
    updated = _ready(trainer, 'POWDER_JAR')
    amount = trainer.get('acquisition', {}).get('berry_powder', 0)
    if type(amount) is not int or not 0 <= amount <= 99999:raise ItemError('Invalid source Berry Powder amount')
    receipt = {'item':'POWDER_JAR','berry_powder':amount,'reusable':True,
               'source':'pret/pokefirered/src/item_use.c:FieldUseFunc_PowderJar;src/berry_powder.c',
               'excluded_feature':'Berry Crush requires at least two linked players (src/berry_crush.c:GetLinkPlayerCount). Online multiplayer is excluded by the project scope; reading the actual jar amount grants no powder.'}
    updated['last_powder_jar'] = receipt
    return updated, receipt
