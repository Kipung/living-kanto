"""Crowded choices remain executable; care feedback never performs care."""
import copy
from test_gameplay import game,act,scenario,state,locate
from living_kanto.mechanics.item_rules import item_catalog
from living_kanto.mechanics.inventory import transferable
from living_kanto.simulation.individual_life import life_view


def test_shop_inventory_pages_preserve_movement_care_and_all_sale_items(game):
 engine,_=game
 from test_entity_storage_trades import fixture_mons
 mons=fixture_mons(game);pid=mons[0]['pokemon_id'];locate(game,'human-001','CeladonCity_DepartmentStore_5F')
 items=[key for key,row in item_catalog().items() if transferable(key) and row.get('price',0)>0 and row['pocket']=='POCKET_ITEMS'][:42]
 items += [key for key,row in item_catalog().items() if transferable(key) and row.get('price',0)>0 and row['pocket']=='POCKET_TM_CASE'][:30]
 scenario(game,[{'op':'set','path':'humans.human-001.inventory','value':{key.lower():{'quantity':2} for key in items}},
  {'op':'set','path':f'pokemon.{pid}.hp','value':1}])
 before=state(game);menu=engine.legal_actions(before,'human-001')
 assert any(a.action=='wait' for a in menu) and any(a.action=='walk_to' for a in menu)
 assert any(a.action=='journey_to' and a.known_consequences.get('destination_kind')=='healing' for a in menu)
 assert sum(a.action=='shop_sell' for a in menu)<=20
 sold=set(a.arguments['item'].upper() for a in menu if a.action=='shop_sell')
 pages=sorted(a.arguments['page'] for a in menu if a.action=='shop_sell_page')
 for page in pages:
  current=act(game,'human-001','shop_sell_page',{'page':page})
  sold.update(a.arguments['item'].upper() for a in engine.legal_actions(current,'human-001') if a.action=='shop_sell')
 assert sold==set(items)
 after=state(game)
 assert after.humans['human-001']['inventory']==before.humans['human-001']['inventory']
 assert after.pokemon==before.pokemon
 assert game[1].replay('gameplay-test').state_hash==after.state_hash


def test_legacy_staff_guidance_without_assignment_mutation_or_forced_return(game):
 engine,_=game;hid='human-056';before=state(game);station=before.humans[hid]['service_assignment']
 changes=[{'op':'set','path':f'humans.{hid}.workplace','value':None}]
 scenario(game,changes);locate(game,hid,'ViridianCity')
 before=state(game);obs=engine.observation_for(before,hid)
 duty=obs.self_state['care_summary']['service_duty']
 assert duty['map_id']==station['map_id'] and not duty['at_assigned_station']
 assert any(a.action=='wait' for a in obs.legal_actions)
 assert state(game).state_hash==before.state_hash
 assert len(obs.self_state['care_summary']['party_members'])==len([p for p in obs.party if not p.get('is_egg')])
