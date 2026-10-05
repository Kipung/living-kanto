"""Human-controlled service queues; Creative scenarios are identified test setup."""
import copy
import random
import pytest
from living_kanto.mechanics import create_pokemon
from living_kanto.simulation.engine import EngineError,StaleActionError
from test_gameplay import game,state,scenario,act,locate


def test_two_healing_customers_fifo_and_real_staff_time(game):
    engine,store=game;current=state(game)
    staff=next(h for h in current.humans.values() if h['role']=='service_staff')
    customers=['human-001','human-002'];mid=staff['map_id']
    for index,hid in enumerate(customers):
        mon=create_pokemon('PIDGEY',5,hid,random.Random(index),identifier=f'pokemon-service-{index}')
        mon['hp']=1;mon['moves'][0]['pp']=0
        scenario(game,[{'op':'set','path':f'pokemon.{mon["pokemon_id"]}','value':mon},
                       {'op':'set','path':f'humans.{hid}.party','value':[mon['pokemon_id']]}])
        locate(game,hid,mid)
        act(game,hid,'heal_party')
    queued=state(game);queue=engine.service_queue(queued,mid)
    assert [request['human_id'] for request in queue]==customers
    assert all(queued.pokemon[f'pokemon-service-{i}']['hp']==1 for i in range(2))
    assert [a.action for a in engine.legal_actions(queued,customers[0])]==['cancel_service']
    assert engine.service_private_info(queued,staff['human_id'])['next_customer']['human_id']==customers[0]
    request=engine.service_actions(queued,staff['human_id'])[0]
    first=act(game,staff['human_id'],request.action,request.arguments)
    assert first.simulated_time==queued.simulated_time+60
    assert first.pokemon['pokemon-service-0']['hp']==first.pokemon['pokemon-service-0']['stats']['hp']
    assert first.pokemon['pokemon-service-1']['hp']==1
    assert first.humans[customers[0]]['service_request'] is None
    assert first.humans[customers[1]]['service_request']
    request=engine.service_actions(first,staff['human_id'])[0]
    second=act(game,staff['human_id'],request.action,request.arguments)
    assert second.simulated_time==first.simulated_time+60
    assert engine.service_queue(second,mid)==[]
    assert len(second.world_facts['service_receipts'])==2
    assert store.replay('gameplay-test').state_hash==second.state_hash


def test_shop_reservation_no_double_purchase_and_no_scripted_service(game):
    engine,store=game;current=state(game)
    staff=next(h for h in current.humans.values() if h.get('service_assignment',{}).get('kind')=='shop' and 'poke_ball' in engine.shop_prices(h['map_id']) and h['map_id']=='CeruleanCity_Mart');hid='human-001'
    locate(game,hid,staff['map_id'])
    before=state(game);quantity=before.humans[hid]['inventory']['poke_ball']['quantity']
    queued=act(game,hid,'shop_buy',{'item':'poke_ball','quantity':1})
    assert queued.humans[hid]['money']==before.humans[hid]['money']-200
    assert queued.humans[hid]['inventory']['poke_ball']['quantity']==quantity
    with pytest.raises(EngineError):act(game,hid,'shop_buy',{'item':'poke_ball','quantity':1})
    with pytest.raises(EngineError):act(game,'human-002','serve_customer',{'request_id':queued.humans[hid]['service_request']['request_id']})
    request=engine.service_actions(queued,staff['human_id'])[0]
    completed=act(game,staff['human_id'],request.action,request.arguments)
    assert completed.humans[hid]['inventory']['poke_ball']['quantity']==quantity+1
    assert completed.humans[hid]['money']==queued.humans[hid]['money']
    assert completed.simulated_time==queued.simulated_time+30
    assert completed.humans[hid]['last_service']['staff_id']==staff['human_id']
    with pytest.raises(EngineError):act(game,staff['human_id'],request.action,request.arguments)
    assert store.replay('gameplay-test').state_hash==completed.state_hash


def test_insufficient_funds_queue_rejection_leaves_state_unchanged(game):
    engine,store=game;staff=next(h for h in state(game).humans.values() if h.get('service_assignment',{}).get('kind')=='shop' and 'poke_ball' in engine.shop_prices(h['map_id']) and h['map_id']=='CeruleanCity_Mart')
    locate(game,'human-001',staff['map_id'])
    scenario(game,[{'op':'set','path':'humans.human-001.money','value':0}]);before=state(game)
    with pytest.raises(EngineError):act(game,'human-001','shop_buy',{'item':'potion','quantity':1})
    assert state(game).state_hash==before.state_hash

def test_competing_staff_same_request_cannot_duplicate_completion(game):
    from collections import defaultdict
    from living_kanto.store import StoreError
    engine,store=game;groups=defaultdict(list)
    for human in state(game).humans.values():
        if human['role']=='service_staff':groups[human['map_id']].append(human['human_id'])
    mid,staff=next((mid,people) for mid,people in groups.items() if len(people)>1)
    locate(game,'human-001',mid);queued=act(game,'human-001','heal_party')
    args=engine.service_actions(queued,staff[0])[0].arguments
    events=[]
    for actor in staff[:2]:
        event,_=engine.build_action_event(store,'gameplay-test',actor,action='serve_customer',arguments=args,
            observation_version=queued.state_version,expected_state_version=queued.state_version,
            decision_explanation='Explicit competing staff test input',decision_provenance={'kind':'user','author':'test'})
        events.append(event)
    engine.commit(store,events[0])
    with pytest.raises(StoreError):engine.commit(store,events[1])
    after=state(game)
    assert after.simulated_time==queued.simulated_time+60
    assert len(after.world_facts['service_receipts'])==1
    assert store.replay('gameplay-test').state_hash==after.state_hash

def test_interrupted_purchase_can_be_explicitly_cancelled_and_refunded(game):
    engine,store=game;staff=next(h for h in state(game).humans.values() if h.get('service_assignment',{}).get('kind')=='shop' and 'poke_ball' in engine.shop_prices(h['map_id']) and h['map_id']=='CeruleanCity_Mart')
    locate(game,'human-001',staff['map_id']);before=state(game)
    queued=act(game,'human-001','shop_buy',{'item':'poke_ball','quantity':1})
    locate(game,'human-001','PalletTown')
    cancelled=act(game,'human-001','cancel_service')
    assert cancelled.humans['human-001']['money']==before.humans['human-001']['money']
    assert cancelled.humans['human-001']['service_request'] is None
    assert engine.service_queue(cancelled,staff['map_id'])==[]
    receipt=cancelled.world_facts['service_receipts'][queued.humans['human-001']['service_request']['request_id']]
    assert receipt['outcome']=='cancelled' and receipt['refund']==200
    assert store.replay('gameplay-test').state_hash==cancelled.state_hash

def test_source_pickup_once_per_trainer_preserves_other_progress(game):
    from living_kanto.simulation.pickups import source_items
    engine,store=game
    selected=None
    for mid,game_map in engine.maps.items():
        for obj in game_map.events.get('object_events',[]):
            if obj.get('graphics_id')=='OBJ_EVENT_GFX_ITEM_BALL' and obj.get('script') in source_items():
                selected=(mid,obj);break
        if selected:break
    assert selected,'No source-backed item ball found'
    mid,obj=selected
    for hid in ['human-001','human-002']:
        locate(game,hid,mid,(obj['x'],obj['y']))
        current=state(game)
        pickup=next(a for a in engine.legal_actions(current,hid) if a.action=='pick_up_item')
        item=pickup.known_consequences['item'];previous=current.humans[hid]['inventory'].get(item,{}).get('quantity',0)
        after=act(game,hid,pickup.action,pickup.arguments)
        assert after.humans[hid]['inventory'][item]['quantity']==previous+pickup.known_consequences['quantity']
        with pytest.raises(EngineError):act(game,hid,pickup.action,pickup.arguments)
        assert after.humans[hid]['badges']==[]
    assert store.replay('gameplay-test').state_hash==state(game).state_hash

def test_repeatable_environment_station_engine_receipt_and_replay(game):
    from living_kanto.simulation.scenarios import definitions
    engine,store=game
    row=next(row for row in definitions() if not row.get('required_items') and not row.get('required_scenarios') and not row.get('caught_species'))
    for hid in ['human-001','human-002']:
        locate(game,hid,row['map_id'],(row['x'],row['y']))
        before=state(game)
        choice=next(a for a in engine.legal_actions(before,hid) if a.action=='use_scenario' and a.arguments['scenario_id']==row['id'])
        after=act(game,hid,choice.action,choice.arguments)
        assert row['id'] in after.humans[hid]['scenarios']['completed']
        assert after.humans[hid]['scenarios']['receipts'][row['id']]['source']==row['source']
        assert after.humans[hid]['badges']==[]
        assert after.simulated_time==before.simulated_time+row['duration_seconds']
        with pytest.raises(EngineError):act(game,hid,choice.action,choice.arguments)
    assert store.replay('gameplay-test').state_hash==state(game).state_hash


def test_custom_lift_key_is_source_ball_not_fabricated_rocket_victory(game):
    engine,store=game
    mid='RocketHideout_B4F'
    obj=next(o for o in engine.maps[mid].events['object_events']
             if o['script']=='RocketHideout_B4F_EventScript_LiftKey')
    locate(game,'human-001',mid,(obj['x'],obj['y']))
    before=state(game)
    offered=next(a for a in engine.legal_actions(before,'human-001')
                 if a.action=='pick_up_item' and a.known_consequences['item']=='lift_key')
    after=act(game,'human-001',offered.action,offered.arguments)
    assert after.humans['human-001']['inventory']['lift_key']['quantity']==1
    assert after.humans['human-001']['badges']==before.humans['human-001']['badges']
    assert not after.humans['human-001'].get('progression_battles')
    with pytest.raises(EngineError):act(game,'human-001',offered.action,offered.arguments)
    assert store.replay('gameplay-test').state_hash==after.state_hash
