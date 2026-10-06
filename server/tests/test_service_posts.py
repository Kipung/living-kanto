"""Source nurse counters and staff decisions; explicit Creative test fixtures."""
from collections import defaultdict

import pytest
from test_gameplay import game, state, scenario, act, locate
from living_kanto.simulation import workplaces
from living_kanto.simulation.engine import EngineError, StaleActionError


def pair(game):
    groups=defaultdict(list)
    for h in state(game).humans.values():
        if h.get('workplace',{}).get('service_post'):
            groups[h['map_id']].append(h['human_id'])
    return next((mid,ids) for mid,ids in groups.items() if len(ids)==2)


def test_initial_nurses_use_unique_source_counter_floor_cells(game):
    engine,_=game;current=state(game);used=set();nurses=0
    for h in current.humans.values():
        if h.get('service_assignment',{}).get('kind')!='healing':continue
        nurses+=1;w=h['workplace'];post=w['service_post'];gm=engine.maps[w['map_id']]
        anchor=next(o for o in gm.events['object_events'] if o['graphics_id']=='OBJ_EVENT_GFX_NURSE')
        assert (post['x'],post['y']) in [(anchor['x'],anchor['y']),(anchor['x']+1,anchor['y'])]
        assert (h['map_id'],h['x'],h['y'])==(w['map_id'],post['x'],post['y'])
        assert h['facing']=='south' and gm.can_stand(h['x'],h['y'])
        key=(h['map_id'],h['x'],h['y']);assert key not in used;used.add(key)
    assert nurses>0
    all_cells=[(h['map_id'],h['x'],h['y']) for h in current.humans.values()]
    assert len(all_cells)==len(set(all_cells))


def test_sole_nurse_duty_blocks_walk_turn_and_counter_departure(game):
    engine,_=game;mid,ids=pair(game);hid,relief=ids
    locate(game,relief,'PalletTown')
    current=state(game);h=current.humans[hid]
    assert workplaces.duty_info(current,hid)['on_duty']
    assert not any(a.action in {'walk_to','travel_to','turn_to','leave_service_post'} for a in engine.legal_actions(current,hid))
    for action,args in [('turn_to',{'direction':'east'}),('walk_to',{'x':h['x']+1,'y':h['y']}),('leave_service_post',{})]:
        with pytest.raises(EngineError):act(game,hid,action,args)
    assert state(game).state_hash==current.state_hash
    assert any(a.action=='rest' for a in engine.legal_actions(current,hid))


def test_counter_passage_requires_assigned_staff_and_nearby_customer_side(game):
    engine,_=game;mid,ids=pair(game);hid=ids[0]
    post=state(game).humans[hid]['workplace']['service_post'];side=post['customer_side']
    locate(game,'human-001',mid,(side['x'],side['y']))
    assert workplaces.post_action(engine,state(game),'human-001',True) is None
    with pytest.raises(EngineError):act(game,'human-001','take_service_post')
    locate(game,'human-001','PalletTown')
    left=act(game,hid,'leave_service_post')
    assert (left.humans[hid]['x'],left.humans[hid]['y'])==(side['x'],side['y'])
    assert left.humans[hid]['facing']=='south'
    returned=act(game,hid,'take_service_post')
    assert workplaces.at_service_post(returned.humans[hid])
    locate(game,hid,mid,(side['x'],side['y']+3))
    assert workplaces.post_action(engine,state(game),hid,True) is None
    with pytest.raises(EngineError):act(game,hid,'take_service_post')
    assert game[1].replay('gameplay-test').state_hash==state(game).state_hash


def test_relief_in_lobby_does_not_count_as_counter_coverage(game):
    engine,_=game;mid,ids=pair(game);hid,relief=ids
    side=state(game).humans[relief]['workplace']['service_post']['customer_side']
    locate(game,relief,mid,(side['x'],side['y']))
    assert workplaces.coverage(state(game),hid)==[]
    assert workplaces.post_action(engine,state(game),hid,False) is None
    with pytest.raises(EngineError):act(game,hid,'leave_service_post')


def test_healing_can_only_be_served_from_assigned_post(game):
    engine,_=game;mid,ids=pair(game);hid=ids[0]
    locate(game,'human-001',mid)
    queued=act(game,'human-001','heal_party')
    option=engine.service_actions(queued,hid)[0]
    side=queued.humans[hid]['workplace']['service_post']['customer_side']
    locate(game,hid,mid,(side['x'],side['y']))
    before=state(game)
    assert not engine.service_actions(before,hid)
    with pytest.raises(EngineError):act(game,hid,option.action,option.arguments)
    assert state(game).state_hash==before.state_hash
    post=before.humans[hid]['workplace']['service_post']
    locate(game,hid,mid,(post['x'],post['y']))
    served=act(game,hid,option.action,option.arguments)
    assert served.humans['human-001']['service_request'] is None
    assert served.humans['human-001']['last_service']['staff_id']==hid


def test_shared_counter_departure_refreshes_when_relief_leaves_post(game):
    engine,store=game;mid,ids=pair(game);hid,relief=ids
    engine.activate_shared_clock(store,'gameplay-test')
    current=state(game);obs,token=engine.capture_decision_boundary(current,hid)
    assert any(a.action=='leave_service_post' for a in obs.legal_actions)
    act(game,relief,'leave_service_post')
    choice={'action':'leave_service_post','arguments':{},'decision_explanation':'Explicit stale relief test'}
    with pytest.raises(StaleActionError,match='workplace duty or relief'):
        engine.build_revalidated_action_event(store,'gameplay-test',hid,choice,obs.state_version,token,{'kind':'user','author':'test'})
    assert workplaces.at_service_post(state(game).humans[hid])


def test_post_passage_refreshes_if_destination_became_occupied(game):
    engine,store=game;mid,ids=pair(game);hid=ids[0]
    engine.activate_shared_clock(store,'gameplay-test')
    current=state(game);obs,token=engine.capture_decision_boundary(current,hid)
    assert any(a.action=='leave_service_post' for a in obs.legal_actions)
    side=current.humans[hid]['workplace']['service_post']['customer_side']
    locate(game,'human-001',mid,(side['x'],side['y']))
    choice={'action':'leave_service_post','arguments':{},'decision_explanation':'Explicit stale passage occupancy test'}
    with pytest.raises(StaleActionError):
        engine.build_revalidated_action_event(store,'gameplay-test',hid,choice,obs.state_version,token,{'kind':'user','author':'test'})


def test_idle_migration_normalizes_source_counter_facing(game):
    engine,_=game;_,ids=pair(game);hid=ids[0]
    scenario(game,[{'op':'set','path':f'humans.{hid}.facing','value':'east'}])
    current=state(game)
    changes=workplaces.migration_changes(engine,current)
    after=current.with_advanced_version(changes)
    assert after.humans[hid]['facing']=='south'


def test_return_to_counter_survives_crowded_inventory_menu(game,monkeypatch):
    from living_kanto.contracts import LegalAction
    engine,_=game;mid,ids=pair(game);hid=ids[0]
    side=state(game).humans[hid]['workplace']['service_post']['customer_side']
    locate(game,hid,mid,(side['x'],side['y']))
    monkeypatch.setattr(engine,'entity_inventory_actions',lambda current,actor:[LegalAction(action='pc_rename_box',arguments={'box':1,'text':'<message, <=200 chars>'},known_consequences={}) for _ in range(200)])
    options=engine.legal_actions(state(game),hid)
    assert len(options)<=128
    assert options[0].action=='take_service_post'
    after=act(game,hid,'take_service_post')
    assert workplaces.at_service_post(after.humans[hid])
