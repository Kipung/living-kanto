"""PC management and negotiated transfers between persistent human entities."""
import copy
from ..contracts.base import content_hash
from ..contracts.human import LegalAction
from ..mechanics import evolution_options
from ..mechanics.item_rules import ItemError, item_catalog, trade_exchange
from ..mechanics.reference import normalize, data
from ..mechanics import pc, inventory
from .engine import EngineError

PC_ACTIONS = frozenset({'store_deposit', 'store_withdraw', 'store_swap', 'store_move',
    'store_select_box', 'store_select_pokemon', 'store_rename_box', 'store_open', 'store_item_page',
    'item_deposit', 'item_withdraw'})
ITEM_TRADE_ACTIONS = frozenset({'item_trade_offer', 'item_trade_accept', 'item_trade_decline', 'trade_select_partner', 'item_trade_select', 'item_trade_page'})


def option(action, arguments, **known):
    return LegalAction(action=action, arguments=arguments, known_consequences=known)


def mon_terms(mon):
    """Only facts explicitly disclosed with the offered individual, not its memories."""
    return {k: copy.deepcopy(mon[k]) for k in ('pokemon_id', 'species', 'level', 'hp', 'stats', 'status', 'moves', 'held_item', 'nature') if k in mon}


def map_visit_changes(state,changes):
    """Finalize true map transfers after all proposed human changes are applied."""
    import random
    from ..mechanics.renewable_items import regenerate_on_entry
    prospective={}
    for change in changes:
        parts=change.get('path','').split('.')
        if change.get('op')!='set' or len(parts)<2 or parts[0]!='humans':continue
        hid=parts[1]
        if hid not in state.humans:continue
        if len(parts)==2:
            prospective[hid]=copy.deepcopy(change['value'])
            continue
        actor=prospective.setdefault(hid,copy.deepcopy(state.humans[hid]))
        parent=actor
        for key in parts[2:-1]:parent=parent.setdefault(key,{})
        parent[parts[-1]]=copy.deepcopy(change['value'])
    result=[]
    for hid,actor in prospective.items():
        if actor.get('map_id')==state.humans[hid]['map_id']:continue
        result.append({'op':'set','path':f'humans.{hid}.map_visit','value':state.humans[hid].get('map_visit',0)+1})
        rng=random.Random(f"{state.world_facts.get('seed',1)}:{state.state_version}:{hid}:renewable")
        renewed,receipt=regenerate_on_entry(actor,rng)
        if receipt:
            for key in ('field_steps','collected_hidden_items','renewable_hidden_items','last_renewable_items'):
                if renewed.get(key)!=actor.get(key):result.append({'op':'set','path':f'humans.{hid}.{key}','value':renewed[key]})
    return result

class EntitySystemsMixin:
    def pc_actions(self, state, hid):
        h = state.humans[hid]
        if not self.at_storage_pc(h) or h.get('battle_id'): return []
        saved = pc.layout(h); actions = []
        mode = saved.get('mode', 'pokemon')
        for target in ('pokemon','items','mail'):
            if target != mode: actions.append(option('store_open', {'mode': target}, opens={'pokemon':'Pokemon boxes','items':'PC item storage','mail':'PC mailbox'}[target]))
        if mode == 'mail': return actions
        if mode == 'items':
            items = sorted(key for key in inventory.stacks(h['inventory']) if inventory.transferable(key))
            pages = max(1, (len(items) + 19) // 20); page = min(saved.get('items_page', 0), pages - 1)
            for target in range(pages):
                if target != page: actions.append(option('store_item_page', {'page': target}, page=target + 1, pages=pages))
            for action, source, names in (('item_deposit', h['inventory'], items[page * 20:(page + 1) * 20]),
                    ('item_withdraw', h.get('pc_items', {}), sorted(inventory.stacks(h.get('pc_items', {}))))):
                for key in names:
                    count = inventory.quantity(source, key)
                    for amount in sorted({1, min(count, 999)}):
                        try: inventory.transfer_items(h, key, amount, deposit=action == 'item_deposit')
                        except ItemError: continue
                        actions.append(option(action, {'item': key.lower(), 'quantity': amount}, amount=amount, same_items=True))
            return actions
        for box in range(1, 15):
            if box != saved['current_box']: actions.append(option('store_select_box', {'box': box}, name=saved['names'].get(str(box), f'Box {box}'), occupied=sum(p['box'] == box for p in saved['placements'].values()), capacity=30))
        actions.append(option('store_rename_box', {'box': saved['current_box'], 'text': '<message, <=200 chars>'}, max_name_characters=8))
        for pid in h['party']:
            if pc.deposit_allowed(h, state.pokemon[pid], state.pokemon): actions.append(option('store_deposit', {'pokemon_id': pid}, same_individual=True, heals_condition=True, box=saved['current_box']))
        current = [pid for pid in h['box'] if saved['placements'][pid]['box'] == saved['current_box']]
        for pid in h['party'] + current:
            if pid != saved.get('selected_pokemon'): actions.append(option('store_select_pokemon', {'pokemon_id': pid}, species=state.pokemon[pid]['species'], level=state.pokemon[pid]['level']))
        if len(h['party']) < 6:
            for pid in current: actions.append(option('store_withdraw', {'pokemon_id': pid}, same_individual=True, heals_condition=True))
        selected = saved.get('selected_pokemon')
        if selected in h['box']:
            for box in range(1, 15):
                if box != saved['placements'][selected]['box'] and pc.free_slot(saved, box) is not None:
                    actions.append(option('store_move', {'pokemon_id': selected, 'box': box}, same_individual=True))
            for pid in h['party']:
                args = {'pokemon_id': selected, 'party_pokemon_id': pid}
                try: pc.change(h, state.pokemon, 'store_swap', args)
                except ItemError: continue
                actions.append(option('store_swap', args, same_individuals=True, full_party_supported=True))
        from ..mechanics.storage import release_pokemon
        owned = [state.pokemon[pid] for pid in h['party'] + h['box']]
        for pid in h['party'] + ([selected] if selected in h['box'] else []):
            try: release_pokemon(h, state.pokemon[pid], owned)
            except ValueError: continue
            actions.append(option('release_pokemon', {'pokemon_id': pid}, ownership_ends=True, persistent_individual=True, irreversible_intention=True))
        return actions

    def pc_changes(self, state, hid, action, args):
        h = state.humans[hid]
        if not self.at_storage_pc(h): raise EngineError('Stand facing a physical PC')
        if action in ('item_deposit', 'item_withdraw'):
            if set(args) != {'item', 'quantity'}: raise EngineError('Item and quantity required')
            updated = inventory.transfer_items(h, args['item'], args['quantity'], deposit=action == 'item_deposit'); mons = []
            keys = ('inventory', 'pc_items')
        elif action in ('store_open', 'store_item_page'):
            updated = copy.deepcopy(h); saved = pc.layout(h); mons = []; keys = ('pc_storage',)
            if action == 'store_open':
                if set(args) != {'mode'} or args['mode'] not in ('pokemon', 'items', 'mail'): raise EngineError('Choose Pokemon or item storage')
                saved['mode'] = args['mode']
            else:
                count = sum(inventory.transferable(key) for key in inventory.stacks(h['inventory']))
                if set(args) != {'page'} or type(args['page']) is not int or not 0 <= args['page'] < max(1, (count + 19) // 20): raise EngineError('Item storage page unavailable')
                saved['items_page'] = args['page']
            updated['pc_storage'] = saved
        else:
            updated, mons = pc.change(h, state.pokemon, action, args); keys = ('party', 'box', 'pc_storage')
        changes = [{'op': 'set', 'path': f'humans.{hid}.{key}', 'value': updated[key]} for key in keys if updated.get(key) != h.get(key)]
        changes.extend({'op': 'set', 'path': f'pokemon.{p["pokemon_id"]}', 'value': p} for p in mons)
        return changes, 'human.stored', 1

    def entity_inventory_actions(self, state, hid):
        h = state.humans[hid]; actions = []
        for item in inventory.stacks(h['inventory']):
            if item_catalog()[item].get('registrability') and item.lower() != h.get('registered_item'):
                actions.append(option('register_item', {'item': item.lower()}, ready_on_select=True))
        if h.get('registered_item'): actions.append(option('unregister_item', {}, clears_shortcut=True))
        if self.shop_prices(h['map_id']):
            sale_items=sorted((item,count) for item,count in inventory.stacks(h['inventory']).items()
                if inventory.transferable(item) and item_catalog()[item].get('price',0)//2>0)
            pages=max(1,(len(sale_items)+9)//10)
            page=min(h.get('trade_preferences',{}).get('sell_page',0),pages-1)
            for target in range(pages):
                if target!=page: actions.append(option('shop_sell_page',{'page':target},page=target+1,pages=pages))
            for item,count in sale_items[page*10:(page+1)*10]:
                price=item_catalog()[item].get('price',0)//2
                for amount in sorted({1,min(count,999)}):
                    actions.append(option('shop_sell',{'item':item.lower(),'quantity':amount},total_price=price*amount))
        return actions

    def pc_approach_actions(self, state, hid):
        from .field import actor_map, DIRECTIONS
        from .pathfinding import shortest_path, PathNotFound
        h = state.humans[hid]
        if not hasattr(self,'_pc_tiles'): self._pc_tiles={}
        mid=h['map_id']
        if mid not in self._pc_tiles:self._pc_tiles[mid]=[(pos,cell) for pos,cell in sorted(self.maps[mid].cells.items()) if cell.get('behavior')==0x83]
        if not self._pc_tiles[mid]: return []
        gm = actor_map(self.maps[mid], h, state)
        actions = []
        for (x, y), cell in self._pc_tiles[mid]:
            for facing, (dx, dy) in DIRECTIONS.items():
                target = (x - dx, y - dy)
                if target == (h['x'], h['y']):
                    if h.get('facing') != facing: actions.append(option('turn_to', {'direction': facing}, opens_interaction='PC'))
                    continue
                try: route = shortest_path(gm, (h['x'], h['y']), target, surfing=False)
                except PathNotFound: continue
                actions.append(option('travel_to', {'x': target[0], 'y': target[1]}, destination_kind='PC', facing_required=facing, route_length=len(route)))
                break
            if len(actions) >= 2: break
        return actions

    def _trade_nearby(self, state, first, second):
        a = state.humans.get(first); b = state.humans.get(second)
        return bool(a and b and first != second and all(h.get('ready_at',0)<=state.simulated_time for h in (a,b)) and not any(h.get(k) for h in (a, b) for k in ('battle_id', 'activity', 'service_request', 'movement_intent'))
            and a['map_id'] == b['map_id'] and abs(a['x'] - b['x']) + abs(a['y'] - b['y']) <= min(self.interaction_radius(a), self.interaction_radius(b)))

    @staticmethod
    def _trade_mon_valid(state, actor, pid, fingerprint=None):
        h = state.humans[actor]; p = state.pokemon.get(pid)
        return bool(p and pid in h['party'] and p.get('owner_id') == actor and not p.get('is_egg') and (fingerprint is None or content_hash(p) == fingerprint))

    def _trade_valid(self, state, offer):
        if offer.get('expires_at', state.simulated_time + 1) <= state.simulated_time: return False
        if not self._trade_nearby(state, offer['proposer'], offer['recipient']): return False
        if offer.get('kind') == 'items':
            try: self._item_exchange(state, offer)
            except (ItemError, EngineError): return False
            return True
        if not self._trade_mon_valid(state, offer['proposer'], offer['offered_pokemon'], offer['offered_hash']): return False
        if offer['phase'] == 'countered':
            return self._trade_mon_valid(state, offer['recipient'], offer['counter_pokemon'], offer['counter_hash'])
        return True

    def trade_actions(self, state, hid):
        h = state.humans[hid]; actions = []
        for tid, offer in state.world_facts.get('trade_offers', {}).items():
            if offer['phase'] not in ('offered', 'countered') or hid not in (offer['proposer'], offer['recipient']): continue
            item = offer.get('kind') == 'items'
            actions.append(option('item_trade_decline' if item else 'trade_decline', {'trade_id': tid}, closes_offer=True, partner=offer['recipient'] if hid == offer['proposer'] else offer['proposer']))
            if not self._trade_valid(state, offer): continue
            if item:
                if hid == offer['recipient']: actions.append(option('item_trade_accept', {'trade_id': tid}, gives=offer['requesting'], receives=offer['giving'], pays=offer['payment'], permanent_transfer=True))
            elif offer['phase'] == 'offered' and offer['recipient'] == hid:
                for pid in h['party']:
                    mon = state.pokemon[pid]
                    if self._trade_mon_valid(state, hid, pid) and (offer['wanted_species'] == 'ANY' or mon['species'] == offer['wanted_species']):
                        actions.append(option('trade_accept', {'trade_id': tid, 'pokemon_id': pid}, receives=mon_terms(state.pokemon[offer['offered_pokemon']]), requires_proposer_confirmation=True))
            elif offer['phase'] == 'countered' and offer['proposer'] == hid:
                actions.append(option('trade_accept', {'trade_id': tid}, receives=mon_terms(state.pokemon[offer['counter_pokemon']]), permanent_ownership_transfer=True))
        # A concrete ANY request allows the numbered local-model provider to
        # negotiate an actual counterpart, rather than emitting a placeholder.
        partners=[other for other in state.humans if self._trade_nearby(state,hid,other)]
        preferred=h.get('trade_preferences',{}).get('partner')
        partner=preferred if preferred in partners else (partners[0] if partners else None)
        for other in partners:
            if other!=partner:actions.append(option('trade_select_partner',{'human_id':other},partner_name=state.humans[other]['name']))
        count = 0
        for other in ([partner] if partner else []):
            for pid in h['party']:
                if not self._trade_mon_valid(state, hid, pid): continue
                actions.append(option('trade_offer', {'human_id': other, 'pokemon_id': pid, 'wanted_species': 'ANY'}, creates_offer=True, requires_reciprocal_confirmation=True, offers=mon_terms(state.pokemon[pid])))
                count += 1
                if count >= 12: break
            if count >= 12: break
        actions.extend(self.item_trade_actions(state, hid))
        return actions

    def _trade_records(self, state):
        offers = copy.deepcopy(state.world_facts.get('trade_offers', {}))
        for offer in offers.values():
            if offer['phase'] in ('offered', 'countered') and offer.get('expires_at', state.simulated_time + 1) <= state.simulated_time:
                offer['phase'] = 'expired'
        return offers

    @staticmethod
    def _trade_save(offers):
        inactive = [key for key, value in offers.items() if value['phase'] not in ('offered', 'countered')]
        for key in inactive[:-100]: offers.pop(key)
        return {'op': 'set', 'path': 'world_facts.trade_offers', 'value': offers}

    def trade_changes(self, state, hid, action, args):
        offers = self._trade_records(state); h = state.humans[hid]; changes = []
        if action == 'trade_offer':
            if set(args) != {'human_id', 'pokemon_id', 'wanted_species'}: raise EngineError('Trade offer requires target, own individual and desired species')
            target, pid = args['human_id'], args['pokemon_id']; species = normalize(str(args['wanted_species']))
            if not self._trade_nearby(state, hid, target) or not self._trade_mon_valid(state, hid, pid) or species != 'ANY' and species not in data()['species']: raise EngineError('Illegal trade offer')
            tid = f'trade-{state.state_version}-{hid}'
            for old in offers.values():
                if old['proposer'] == hid and old.get('kind') != 'items' and old['phase'] in ('offered', 'countered'): old['phase'] = 'superseded'
            offers[tid] = {'trade_id': tid, 'kind': 'pokemon', 'proposer': hid, 'recipient': target, 'offered_pokemon': pid,
                'wanted_species': species, 'phase': 'offered', 'offered_hash': content_hash(state.pokemon[pid]),
                'offered_details': mon_terms(state.pokemon[pid]), 'offer_version': state.state_version,
                'expires_at': state.simulated_time + 3600}
        else:
            tid = args.get('trade_id'); offer = offers.get(tid)
            if not offer or offer.get('kind') == 'items' or offer['phase'] not in (('offered','countered','expired') if action=='trade_decline' else ('offered','countered')) or hid not in (offer['proposer'], offer['recipient']): raise EngineError('Trade offer unavailable')
            if action == 'trade_decline':
                if set(args) != {'trade_id'}: raise EngineError('Invalid decline arguments')
                offer['phase'] = 'declined'
            else:
                if not self._trade_valid(state, offer): raise EngineError('Trade individual changed or partner unavailable; create new offer')
                if offer['phase'] == 'offered':
                    if hid != offer['recipient'] or set(args) != {'trade_id', 'pokemon_id'}: raise EngineError('Only recipient can offer counterpart')
                    pid = args['pokemon_id']
                    if not self._trade_mon_valid(state, hid, pid) or offer['wanted_species'] != 'ANY' and state.pokemon[pid]['species'] != offer['wanted_species']: raise EngineError('Counterpart not eligible')
                    offer.update({'phase': 'countered', 'counter_pokemon': pid, 'counter_hash': content_hash(state.pokemon[pid]), 'counter_details': mon_terms(state.pokemon[pid]), 'counter_version': state.state_version})
                else:
                    if hid != offer['proposer'] or set(args) != {'trade_id'}: raise EngineError('Proposer must confirm final individual exchange')
                    first = state.pokemon[offer['offered_pokemon']]; second = state.pokemon[offer['counter_pokemon']]
                    accepted = [{'actor_id': actor, 'trade_id': tid, 'accepted': True, 'state_version': state.state_version, 'offered_pokemon': p['pokemon_id'], 'requested_pokemon': other['pokemon_id']}
                        for actor, p, other in ((hid, first, second), (offer['recipient'], second, first))]
                    t1, p1, t2, p2, event = trade_exchange(h, first, state.humans[offer['recipient']], second, offers=accepted, expected_state_version=state.state_version)
                    for trainer in (t1, t2):
                        received = p1 if trainer['human_id'] == hid else p2
                        if not pc.usable(received) and not any(pc.usable(state.pokemon[p]) for p in trainer['party'] if p != received['pokemon_id']): raise EngineError('Trade would leave no usable party Pokemon')
                        for key in ('party', 'box', 'pokedex'): changes.append({'op': 'set', 'path': f'humans.{trainer["human_id"]}.{key}', 'value': trainer[key]})
                    for p in (p1, p2):
                        changes.append({'op': 'set', 'path': f'pokemon.{p["pokemon_id"]}', 'value': p})
                        for sid, claim in state.world_facts.get('static_encounters', {}).items():
                            if claim.get('pokemon_id') == p['pokemon_id']: changes.append({'op': 'set', 'path': f'world_facts.static_encounters.{sid}', 'value': {**claim, 'owner_id': p['owner_id']}})
                    offer.update({'phase': 'completed', 'completed_version': state.state_version, 'completed_at': state.simulated_time})
        changes.append(self._trade_save(offers))
        return changes, 'human.traded' if offers[tid]['phase'] == 'completed' else 'world.public_event', 1

    def item_trade_actions(self, state, hid):
        h = state.humans[hid]; actions = []
        # Fixed one-item offers are immediately usable by numbered AI. Exact
        # quantity/barter/payment terms may also be supplied through the API.
        items=sorted(key for key in inventory.stacks(h['inventory']) if inventory.transferable(key))
        prefs=h.get('trade_preferences',{});pages=max(1,(len(items)+19)//20);page=min(prefs.get('item_page',0),pages-1)
        selected=prefs.get('item');selected=selected if selected in items else (items[0] if items else None)
        for item in items[page*20:(page+1)*20]:
            if item!=selected:actions.append(option('item_trade_select',{'item':item.lower()},selects_owned_item=True))
        for target in range(pages):
            if target!=page:actions.append(option('item_trade_page',{'page':target},page=target+1,pages=pages))
        partners=[other for other in state.humans if self._trade_nearby(state,hid,other)]
        partner=prefs.get('partner');partner=partner if partner in partners else (partners[0] if partners else None)
        for other in ([partner] if partner else []):
            for item in ([selected] if selected else []):
                price = item_catalog()[item].get('price', 0) // 2
                for payment in sorted({0, price}):
                    args = {'human_id': other, 'giving': {item.lower(): 1}, 'requesting': {}, 'payment': payment}
                    offer = {'proposer': hid, 'recipient': other, **{k: v for k, v in args.items() if k != 'human_id'}}
                    try: self._item_proposal(state, offer)
                    except ItemError: continue
                    actions.append(option('item_trade_offer', args, requires_other_acceptance=True, gift=payment == 0))
        return actions

    @staticmethod
    def _item_terms(terms):
        if not isinstance(terms, dict) or len(terms) > 20: raise ItemError('Trade terms must contain at most twenty item stacks')
        result = {}
        for name, amount in terms.items():
            if not isinstance(name,str):raise ItemError('Item trade identifiers must be strings')
            key = normalize(name).removeprefix('ITEM_')
            if key not in item_catalog() or not inventory.transferable(key) or type(amount) is not int or not 1 <= amount <= 999:
                raise ItemError('Trade only owned ordinary items in quantities from 1 to 999')
            if key.lower() in result: raise ItemError('Duplicate item trade term')
            result[key.lower()] = amount
        return result

    def _item_exchange(self, state, offer):
        giving = self._item_terms(offer['giving']); requesting = self._item_terms(offer['requesting']); payment = offer['payment']
        if not giving or set(giving).intersection(requesting) or type(payment) is not int or not 0 <= payment <= 999999: raise ItemError('Invalid item trade terms')
        a = copy.deepcopy(state.humans[offer['proposer']]); b = copy.deepcopy(state.humans[offer['recipient']])
        if b['money'] < payment or a['money'] + payment > 999999: raise ItemError('Insufficient payment or money limit reached')
        # Remove both sides before adding, permitting barter into a full pocket
        # when the outgoing stack releases the required slot.
        for h, terms in ((a, giving), (b, requesting)):
            for item, amount in terms.items(): h['inventory'] = inventory.remove(h['inventory'], item, amount)
        for h, terms in ((b, giving), (a, requesting)):
            for item, amount in terms.items(): h['inventory'] = inventory.add(h['inventory'], item, amount)
        a['money'] += payment; b['money'] -= payment
        return a, b

    def _item_proposal(self, state, offer):
        """An invitation discloses terms; it cannot inspect the recipient's bag."""
        giving=self._item_terms(offer['giving']); requesting=self._item_terms(offer['requesting']); payment=offer['payment']
        if not giving or set(giving).intersection(requesting) or type(payment) is not int or not 0<=payment<=999999:
            raise ItemError('Invalid item trade terms')
        h=state.humans[offer['proposer']]
        if h['money']+payment>999999: raise ItemError('Money limit reached')
        bag=copy.deepcopy(h['inventory'])
        for item,amount in giving.items():bag=inventory.remove(bag,item,amount)
        for item,amount in requesting.items():bag=inventory.add(bag,item,amount)

    def item_trade_changes(self, state, hid, action, args):
        offers = self._trade_records(state); changes = []
        if action in ('trade_select_partner','item_trade_select','item_trade_page'):
            prefs=copy.deepcopy(state.humans[hid].get('trade_preferences',{}))
            if action=='trade_select_partner':
                if set(args)!={'human_id'} or not self._trade_nearby(state,hid,args['human_id']):raise EngineError('Nearby available partner required')
                prefs['partner']=args['human_id']
            elif action=='item_trade_select':
                if set(args)!={'item'} or not inventory.transferable(args['item']) or not inventory.quantity(state.humans[hid]['inventory'],args['item']):raise EngineError('Owned ordinary item required')
                prefs['item']=normalize(args['item']).removeprefix('ITEM_')
            else:
                count=sum(inventory.transferable(item) for item in inventory.stacks(state.humans[hid]['inventory']))
                if set(args)!={'page'} or type(args['page'])is not int or not 0<=args['page']<max(1,(count+19)//20):raise EngineError('Item trade page unavailable')
                prefs['item_page']=args['page']
            return [{'op':'set','path':f'humans.{hid}.trade_preferences','value':prefs}],'world.public_event',1
        if action == 'item_trade_offer':
            if set(args) != {'human_id', 'giving', 'requesting', 'payment'} or not self._trade_nearby(state, hid, args['human_id']): raise EngineError('Nearby available trade partner required')
            tid = f'item-trade-{state.state_version}-{hid}'
            offer = {'trade_id': tid, 'kind': 'items', 'proposer': hid, 'recipient': args['human_id'], 'giving': self._item_terms(args['giving']), 'requesting': self._item_terms(args['requesting']),
                'payment': args['payment'], 'phase': 'offered', 'offer_version': state.state_version, 'expires_at': state.simulated_time + 3600}
            self._item_proposal(state, offer)
            for old in offers.values():
                if old['proposer'] == hid and old.get('kind') == 'items' and old['phase'] == 'offered': old['phase'] = 'superseded'
            offers[tid] = offer
        else:
            tid = args.get('trade_id'); offer = offers.get(tid)
            if set(args) != {'trade_id'} or not offer or offer.get('kind') != 'items' or offer['phase'] not in (('offered','expired') if action=='item_trade_decline' else ('offered',)) or hid not in (offer['proposer'], offer['recipient']): raise EngineError('Item trade offer unavailable')
            if action == 'item_trade_decline': offer['phase'] = 'declined'
            else:
                if hid != offer['recipient'] or not self._trade_valid(state, offer): raise EngineError('Only available recipient may accept current terms')
                for h in self._item_exchange(state, offer):
                    for key in ('inventory', 'money'): changes.append({'op': 'set', 'path': f'humans.{h["human_id"]}.{key}', 'value': h[key]})
                offer.update({'phase': 'completed', 'completed_version': state.state_version, 'completed_at': state.simulated_time})
        changes.append(self._trade_save(offers))
        return changes, 'human.traded' if offers[tid]['phase'] == 'completed' else 'world.public_event', 1
