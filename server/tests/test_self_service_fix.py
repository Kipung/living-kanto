"""Shared-world queue adaptation recovery; Creative setup is not autonomy evidence."""
import copy
import pytest
from test_gameplay import game,state,scenario,act,locate
from living_kanto.simulation.engine import EngineError

def clerk(game):
 return next(h for h in state(game).humans.values() if h.get('service_assignment')=={'kind':'shop','map_id':'CinnabarIsland_Mart'})

def test_legacy_self_queue_can_cancel_once_and_replay(game):
 engine,store=game;h=clerk(game);hid=h['human_id'];mid=h['map_id'];before=state(game);price=engine.shop_prices(mid)['great_ball']
 request={'request_id':'legacy-self-request','human_id':hid,'map_id':mid,'kind':'shop','arguments':{'item':'great_ball','quantity':1},'reserved_payment':price,'requested_at':before.simulated_time}
 scenario(game,[{'op':'set','path':f'humans.{hid}.money','value':h['money']-price},{'op':'set','path':f'humans.{hid}.service_request','value':request},{'op':'set','path':f'humans.{hid}.status.activity','value':'queued_service'},{'op':'set','path':f'world_facts.service_queues.{mid}','value':[request]}])
 queued=state(game);assert [a.action for a in engine.legal_actions(queued,hid)]==['wait_for_service','cancel_service']
 after=act(game,hid,'cancel_service');assert after.humans[hid]['money']==h['money'];assert after.humans[hid]['inventory']==h['inventory'];assert after.humans[hid]['service_request'] is None;assert engine.service_queue(after,mid)==[]
 assert after.world_facts['service_receipts']['legacy-self-request']['refund']==price
 assert after.world_facts['service_receipts']['legacy-self-request']['outcome']=='cancelled'
 with pytest.raises(EngineError):act(game,hid,'cancel_service')
 assert state(game).state_hash==after.state_hash
 assert store.replay('gameplay-test').state_hash==after.state_hash

def test_sole_clerk_self_request_rejected_before_charge(game):
 engine,store=game;h=clerk(game);before=state(game)
 assert not any(a.action=='shop_buy' for a in engine.legal_actions(before,h['human_id']))
 with pytest.raises(EngineError):engine.service_changes(before,h['human_id'],'shop_buy',{'item':'great_ball','quantity':1})
 assert state(game).state_hash==before.state_hash

def test_normal_fifo_customers_cancel_or_receive_no_duplicate_goods(game):
 engine,store=game;h=clerk(game);mid=h['map_id'];customers=['human-001','human-002']
 for hid in customers:locate(game,hid,mid)
 first=act(game,customers[0],'shop_buy',{'item':'great_ball','quantity':1});second=act(game,customers[1],'shop_buy',{'item':'great_ball','quantity':1})
 assert [r['human_id'] for r in engine.service_queue(second,mid)]==customers
 assert [a.action for a in engine.legal_actions(second,customers[1])]==['wait_for_service','cancel_service']
 cancelled=act(game,customers[1],'cancel_service');assert len(engine.service_queue(cancelled,mid))==1
 choice=engine.service_actions(cancelled,h['human_id'])[0];after=act(game,h['human_id'],choice.action,choice.arguments)
 assert after.humans[customers[0]]['inventory']['great_ball']['quantity']==first.humans[customers[0]]['inventory'].get('great_ball',{}).get('quantity',0)+1
 assert after.humans[customers[1]]['money']==second.humans[customers[1]]['money']+600
 assert not engine.service_queue(after,mid);assert store.replay('gameplay-test').state_hash==after.state_hash

def test_player_cancel_behavior_remains_available(game):
 engine,store=game;engine.add_player(store,'gameplay-test',state(game).state_version);h=clerk(game);locate(game,'player',h['map_id']);before=state(game)
 queued=act(game,'player','shop_buy',{'item':'great_ball','quantity':1});assert [a.action for a in engine.legal_actions(queued,'player')]==['wait_for_service','cancel_service']
 after=act(game,'player','cancel_service');assert after.humans['player']['money']==before.humans['player']['money'];assert not engine.service_queue(after,h['map_id'])
 assert store.replay('gameplay-test').state_hash==after.state_hash

def test_sole_healing_staff_cannot_queue_own_healing(game):
 engine,store=game;current=state(game)
 staff=next(h for h in current.humans.values() if h.get('service_assignment',{}).get('kind')=='healing' and sum(o.get('service_assignment')==h.get('service_assignment') for o in current.humans.values())==1)
 assert not any(a.action=='heal_party' for a in engine.legal_actions(current,staff['human_id']))
 with pytest.raises(EngineError):engine.service_changes(current,staff['human_id'],'heal_party',{})
 assert state(game).state_hash==current.state_hash
