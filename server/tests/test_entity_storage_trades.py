"""Explicit fixtures; real engine transactions, ownership and replay checks."""
import copy
import random
import pytest
from test_gameplay import game,act,locate,scenario,state
from test_mechanics_storage_gameplay import pc as pc_location
from test_mechanics_inventory_gameplay import trade_fixture
from living_kanto.mechanics import create_pokemon
from living_kanto.mechanics import inventory, pc
from living_kanto.mechanics.item_rules import ItemError,item_catalog
from living_kanto.simulation.engine import EngineError
from living_kanto.runtime.decision_wire import build_decision_wire


def at_pc(game, hid='human-001'):
    mid,position,facing=pc_location(game);locate(game,hid,mid,position)
    scenario(game,[{'op':'set','path':f'humans.{hid}.facing','value':facing}])


def fixture_mons(game, count=2, boxed=0):
    mons=[create_pokemon('RATTATA',5,'human-001',random.Random(i),identifier=f'pc-person-{i}') for i in range(count+boxed)]
    scenario(game,[{'op':'set','path':f'pokemon.{p["pokemon_id"]}','value':p} for p in mons]+[
        {'op':'set','path':'humans.human-001.party','value':[p['pokemon_id'] for p in mons[:count]]},
        {'op':'set','path':'humans.human-001.box','value':[p['pokemon_id'] for p in mons[count:]]}])
    return mons


def test_legacy_boxes_read_only_preserve_slots_and_fill_holes():
    h={'box':['a','b','c'],'party':[],'pc_storage':{'placements':{'a':{'box':14,'slot':30},'old':{'box':1,'slot':1}}}}
    before=copy.deepcopy(h);saved=pc.layout(h)
    assert h==before
    assert saved['placements']=={'a':{'box':14,'slot':30},'b':{'box':1,'slot':1},'c':{'box':1,'slot':2}}
    h['box']=[str(i) for i in range(420)]
    assert len(pc.layout(h)['placements'])==420
    h['box'].append('overflow')
    with pytest.raises(ItemError,match='full'):pc.layout(h)


def test_box_select_move_full_party_swap_and_restart_replay(game):
    mons=fixture_mons(game,count=6,boxed=1);at_pc(game);pid=mons[-1]['pokemon_id']
    act(game,'human-001','store_select_pokemon',{'pokemon_id':pid})
    s=act(game,'human-001','store_move',{'pokemon_id':pid,'box':14})
    assert s.humans['human-001']['pc_storage']['placements'][pid]=={'box':14,'slot':1}
    act(game,'human-001','store_select_box',{'box':14})
    act(game,'human-001','store_rename_box',{'box':14,'text':'Partners'})
    s=act(game,'human-001','store_swap',{'pokemon_id':pid,'party_pokemon_id':mons[0]['pokemon_id']})
    h=s.humans['human-001'];assert len(h['party'])==6 and pid in h['party'] and mons[0]['pokemon_id'] in h['box']
    assert h['pc_storage']['placements'][mons[0]['pokemon_id']]=={'box':14,'slot':1}
    assert s.pokemon[pid]['owner_id']=='human-001' and s.pokemon[pid]['personality']==mons[-1]['personality']
    assert game[1].replay('gameplay-test').state_hash==s.state_hash
    # Disk reconstruction must retain new optional metadata without migration.
    from living_kanto.store import RunStore
    restored=RunStore(game[1].path)
    assert restored.load_run('gameplay-test')[1].state_hash==s.state_hash
    restored.close()


def test_storage_restores_condition_retains_held_and_protects_last_usable(game):
    mons=fixture_mons(game);at_pc(game);pid=mons[0]['pokemon_id']
    scenario(game,[{'op':'set','path':f'pokemon.{pid}.hp','value':1},{'op':'set','path':f'pokemon.{pid}.status','value':'psn'},
        {'op':'set','path':f'pokemon.{pid}.held_item','value':'ORAN_BERRY'},
        {'op':'set','path':f'pokemon.{pid}.moves','value':[{'move':'TACKLE','pp':0,'max_pp':35}]}])
    act(game,'human-001','store_deposit',{'pokemon_id':pid})
    s=act(game,'human-001','store_withdraw',{'pokemon_id':pid})
    assert s.pokemon[pid]['hp']==s.pokemon[pid]['stats']['hp'] and s.pokemon[pid]['status']==''
    assert s.pokemon[pid]['moves'][0]['pp']==35 and s.pokemon[pid]['held_item']=='ORAN_BERRY'
    scenario(game,[{'op':'set','path':f'pokemon.{mons[1]["pokemon_id"]}.hp','value':0}])
    before=state(game)
    with pytest.raises(EngineError):act(game,'human-001','store_deposit',{'pokemon_id':pid})
    assert state(game).state_hash==before.state_hash


def test_pc_items_quantity_limits_key_protection_and_private_observation(game):
    at_pc(game);hid='human-001'
    scenario(game,[{'op':'set','path':f'humans.{hid}.inventory','value':{'potion':{'quantity':9},'bicycle':{'quantity':1}}}])
    act(game,hid,'store_open',{'mode':'items'})
    s=act(game,hid,'item_deposit',{'item':'potion','quantity':8})
    assert s.humans[hid]['inventory']['potion']['quantity']==1 and s.humans[hid]['pc_items']['potion']['quantity']==8
    before=s
    with pytest.raises(EngineError):act(game,hid,'item_deposit',{'item':'bicycle','quantity':1})
    with pytest.raises(EngineError):act(game,hid,'item_deposit',{'item':'potion','quantity':True})
    assert state(game).state_hash==before.state_hash
    s=act(game,hid,'item_withdraw',{'item':'potion','quantity':8})
    assert s.humans[hid]['inventory']['potion']['quantity']==9 and 'potion' not in s.humans[hid]['pc_items']
    obs=game[0].observation_for(s,hid)
    assert obs.self_state['pc_items']=={} and 'pc_items' not in game[0].observation_for(s,'human-002').self_state.get('other',{})
    assert game[1].replay('gameplay-test').state_hash==s.state_hash


def test_source_bag_pockets_stack_pc_capacity_and_container_acquisition():
    assert inventory.limits()['POCKET_ITEMS']==42 and inventory.limits()['pc']==30
    bag=inventory.add({},'TM03',1)
    assert bag['tm03']['quantity']==1 and bag['tm_case']['quantity']==1
    bag=inventory.add(bag,'ORAN_BERRY',1)
    assert bag['berry_pouch']['quantity']==1
    with pytest.raises(ItemError,match='999'):inventory.add({'potion':{'quantity':999}},'POTION',1)
    keys=[k for k in item_catalog() if item_catalog()[k]['pocket']=='POCKET_ITEMS' and inventory.transferable(k)]
    bag={key.lower():{'quantity':1} for key in keys[:42]}
    with pytest.raises(ItemError,match='pocket'):inventory.add(bag,keys[42],1)
    store={key.lower():{'quantity':1} for key in keys[:30]}
    with pytest.raises(ItemError,match='full'):inventory.add(store,keys[30],1,pc=True)
    # Existing legacy bag is untouched, while an extra new kind is rejected.
    legacy={key.lower():{'quantity':1} for key in keys[:43]}
    inventory.validate_gains(legacy,legacy)
    with pytest.raises(ItemError,match='full'):inventory.validate_gains(legacy,{**legacy,keys[43].lower():{'quantity':1}})


def nearby_items(game):
    locate(game,'human-001','PalletTown',(10,10));locate(game,'human-002','PalletTown',(11,10))
    scenario(game,[{'op':'set','path':'humans.human-001.inventory','value':{'potion':{'quantity':4}}},
        {'op':'set','path':'humans.human-002.inventory','value':{'antidote':{'quantity':3}}}])


def test_item_barter_payment_both_acceptance_atomic_replay_and_stale_reject(game):
    nearby_items(game);initial=state(game)
    s=act(game,'human-001','item_trade_offer',{'human_id':'human-002','giving':{'potion':2},'requesting':{'antidote':1},'payment':150})
    tid=next(key for key in s.world_facts['trade_offers'] if key.startswith('item-trade'))
    assert s.humans['human-001']['inventory']==initial.humans['human-001']['inventory']
    assert not game[0].observation_for(s,'human-003').self_state['trade_offers']
    s=act(game,'human-002','item_trade_accept',{'trade_id':tid})
    assert s.humans['human-001']['inventory']['potion']['quantity']==2
    assert s.humans['human-001']['inventory']['antidote']['quantity']==1
    assert s.humans['human-002']['inventory']['potion']['quantity']==2
    assert s.humans['human-002']['inventory']['antidote']['quantity']==2
    assert s.humans['human-001']['money']==initial.humans['human-001']['money']+150
    assert s.humans['human-002']['money']==initial.humans['human-002']['money']-150
    assert game[1].replay('gameplay-test').state_hash==s.state_hash
    before=s
    with pytest.raises(EngineError):act(game,'human-002','item_trade_accept',{'trade_id':tid})
    assert state(game).state_hash==before.state_hash


def test_changed_items_expired_offers_distant_decline_and_busy_partners(game):
    nearby_items(game)
    s=act(game,'human-001','item_trade_offer',{'human_id':'human-002','giving':{'potion':4},'requesting':{},'payment':0})
    tid=next(key for key in s.world_facts['trade_offers'] if key.startswith('item-trade'))
    scenario(game,[{'op':'set','path':'humans.human-001.inventory.potion.quantity','value':1}]);before=state(game)
    with pytest.raises(EngineError):act(game,'human-002','item_trade_accept',{'trade_id':tid})
    assert state(game).state_hash==before.state_hash
    locate(game,'human-002','ViridianCity',(5,5))
    s=act(game,'human-002','item_trade_decline',{'trade_id':tid});assert s.world_facts['trade_offers'][tid]['phase']=='declined'
    locate(game,'human-002','PalletTown',(11,10))
    scenario(game,[{'op':'set','path':'humans.human-002.activity','value':{'kind':'rest','ends_at':10000}}])
    assert not game[0]._trade_nearby(state(game),'human-001','human-002')


def test_numbered_trade_has_concrete_terms_and_full_party_information(game):
    p1,p2,tid=trade_fixture(game)
    obs=game[0].observation_for(state(game),'human-002').to_dict()
    wire=build_decision_wire(obs)
    offered=next(o for o in wire.options if o['action']=='trade_accept')
    choice=wire.decode({'option':offered['option'],'text':'','decision_explanation':'Accept the actual offered individual'})
    assert choice['arguments']=={'trade_id':tid,'pokemon_id':p2['pokemon_id']}
    assert offered['known_consequences']['receives']['species']=='KADABRA'
    offers=[o for o in wire.options if o['action']=='trade_offer']
    assert offers and all(o['arguments']['wanted_species']=='ANY' for o in offers)


def test_traded_legendary_claim_tracks_same_owner(game):
    p1,p2,tid=trade_fixture(game)
    scenario(game,[{'op':'set','path':'world_facts.static_encounters.zapdos','value':{'pokemon_id':p1['pokemon_id'],'status':'caught','owner_id':'human-001'}}])
    act(game,'human-002','trade_accept',{'trade_id':tid,'pokemon_id':p2['pokemon_id']})
    s=act(game,'human-001','trade_accept',{'trade_id':tid})
    assert s.world_facts['static_encounters']['zapdos']['owner_id']=='human-002'
    assert game[1].replay('gameplay-test').state_hash==s.state_hash


def test_shop_sell_source_half_price_and_cannot_sell_key_item(game):
    locate(game,'human-001','ViridianCity_Mart',(5,5));hid='human-001'
    scenario(game,[{'op':'set','path':f'humans.{hid}.inventory','value':{'potion':{'quantity':4},'bicycle':{'quantity':1}}}])
    old=state(game).humans[hid]['money'];s=act(game,hid,'shop_sell',{'item':'potion','quantity':3})
    assert s.humans[hid]['money']==old+450 and s.humans[hid]['inventory']['potion']['quantity']==1
    before=s
    with pytest.raises(EngineError):act(game,hid,'shop_sell',{'item':'bicycle','quantity':1})
    assert state(game).state_hash==before.state_hash


def test_item_trade_offer_does_not_disclose_partner_private_resources(game):
    nearby_items(game);e,_=game
    baseline=[a.to_dict() for a in e.item_trade_actions(state(game),'human-001')]
    scenario(game,[{'op':'set','path':'humans.human-002.inventory','value':{}},{'op':'set','path':'humans.human-002.money','value':0}])
    assert [a.to_dict() for a in e.item_trade_actions(state(game),'human-001')]==baseline
    s=act(game,'human-001','item_trade_offer',{'human_id':'human-002','giving':{'potion':1},'requesting':{'antidote':1},'payment':150})
    tid=next(key for key in s.world_facts['trade_offers'] if key.startswith('item-trade'))
    assert not any(a.action=='item_trade_accept' for a in e.legal_actions(s,'human-002'))
    s=act(game,'human-002','item_trade_decline',{'trade_id':tid})
    assert s.world_facts['trade_offers'][tid]['phase']=='declined'


def test_box_name_wire_limit_and_held_item_complete_numbered_selection(game):
    mons=fixture_mons(game);at_pc(game)
    scenario(game,[{'op':'set','path':'humans.human-001.inventory','value':{'potion':{'quantity':1},'oran_berry':{'quantity':1}}}])
    wire=build_decision_wire(game[0].observation_for(state(game),'human-001').to_dict())
    rename=next(a for a in wire.options if a['action']=='store_rename_box')
    with pytest.raises(ValueError,match='limit'):wire.decode({'option':rename['option'],'text':'Too long a name','decision_explanation':'Organize'})
    choices={o['arguments']['item'] for o in wire.options if o['action']=='give_held_item' and o['arguments']['pokemon_id']==mons[0]['pokemon_id']}
    assert choices=={'potion','oran_berry'}


def test_shared_pc_and_trade_dependencies_refresh_inflight_decisions(game):
    from test_shared_clock_engine import activate,choose
    from living_kanto.simulation.engine import StaleActionError
    nearby_items(game);activate(game)
    e,_=game;s=choose(game,'human-001','item_trade_offer',{'human_id':'human-002','giving':{'potion':1},'requesting':{},'payment':0})
    tid=next(key for key in s.world_facts['trade_offers'] if key.startswith('item-trade'))
    obs,token=e.capture_decision_boundary(s,'human-002')
    scenario(game,[{'op':'set','path':f'world_facts.trade_offers.{tid}.phase','value':'superseded'}])
    before=state(game)
    with pytest.raises(StaleActionError):choose(game,'human-002','item_trade_accept',{'trade_id':tid},token=token,version=obs.state_version)
    assert state(game).state_hash==before.state_hash
    obs,token=e.capture_decision_boundary(state(game),'human-002')
    scenario(game,[{'op':'set','path':'humans.human-002.pc_items','value':{'potion':{'quantity':1}}}])
    with pytest.raises(StaleActionError):choose(game,'human-002','remember',{'text':'Old thought'},token=token,version=obs.state_version)


def test_mail_engine_trade_pc_preserves_text_author_and_exactly_one_letter(game):
    p1,p2,tid=trade_fixture(game);hid='human-001'
    # Supersede old proposal after writing so its terms include the actual mail.
    scenario(game,[{'op':'set','path':f'humans.{hid}.inventory','value':{'orange_mail':{'quantity':1}}}])
    s=act(game,hid,'write_mail',{'pokemon_id':p1['pokemon_id'],'item':'orange_mail','text':'Thank you for training with me.'})
    letter=copy.deepcopy(s.pokemon[p1['pokemon_id']]['mail'])
    s=act(game,hid,'trade_offer',{'human_id':'human-002','pokemon_id':p1['pokemon_id'],'wanted_species':'MACHOKE'})
    tid=next(key for key,row in s.world_facts['trade_offers'].items() if row['phase']=='offered')
    act(game,'human-002','trade_accept',{'trade_id':tid,'pokemon_id':p2['pokemon_id']})
    s=act(game,hid,'trade_accept',{'trade_id':tid})
    assert s.pokemon[p1['pokemon_id']]['mail']==letter and s.pokemon[p1['pokemon_id']]['owner_id']=='human-002'
    at_pc(game,'human-002');act(game,'human-002','store_open',{'mode':'mail'})
    s=act(game,'human-002','mail_to_pc',{'pokemon_id':p1['pokemon_id']})
    assert not s.pokemon[p1['pokemon_id']].get('mail') and s.humans['human-002']['mailbox'][letter['mail_id']]==letter
    s=act(game,'human-002','mail_attach',{'pokemon_id':p1['pokemon_id'],'mail_id':letter['mail_id']})
    assert s.humans['human-002']['mailbox']=={} and s.pokemon[p1['pokemon_id']]['mail']==letter
    assert game[1].replay('gameplay-test').state_hash==s.state_hash
