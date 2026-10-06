"""Explicit scripted scheduling fixtures, not actual autonomy evidence."""
import json
from living_kanto.runtime import RuntimeController
from test_gameplay import game,state,act

class WorkProvider:
    model_id='scripted-batch-test-only'
    protocol='test'
    test_provider=True
    def complete(self, observation, correction=None):
        return json.dumps({'action':'work','arguments':{},'decision_explanation':'I choose my declared work responsibility.'})


def test_atomic_two_worker_intents_and_restart_cursor(game):
    engine,store=game
    workers=sorted(h['human_id'] for h in state(game).humans.values() if h['role']=='worker')[:3]
    before=state(game)
    runtime=RuntimeController(engine,store,'gameplay-test',WorkProvider(),actor_ids=workers,concurrency=2)
    try:
        result=runtime.step()
        assert result['accepted_decisions']==2 and result['atomic_activity_batch']
        current=state(game)
        assert current.state_version==before.state_version+1
        assert current.simulated_time==before.simulated_time
        assert runtime.status()['concurrency']==2
        for hid in workers[:2]:
            assert current.humans[hid]['money']==before.humans[hid]['money']
            assert current.humans[hid]['activity']['kind']=='work'
            assert current.humans[hid]['last_decision']['explanation'].startswith('I choose')
        event=store.iter_events('gameplay-test')[-1]
        assert len(event.causation['decisions'])==2
        assert store.replay('gameplay-test').state_hash==current.state_hash
    finally:runtime.close()
    restarted=RuntimeController(engine,store,'gameplay-test',WorkProvider(),actor_ids=workers,concurrency=2)
    try:
        assert restarted.actor_ids[restarted._cursor]==workers[2]
    finally:restarted.close()


def test_hundred_actor_elapsed_needs_and_deferred_pay_replay(game):
    engine,store=game
    before=state(game);hid=next(hid for hid,h in sorted(before.humans.items()) if h['role']=='worker')
    started=act(game,hid,'work')
    assert started.simulated_time==before.simulated_time
    assert started.humans[hid]['money']==before.humans[hid]['money']
    event=engine.advance_activities(store,'gameplay-test',allow_future=True)
    assert event
    completed=state(game)
    assert completed.simulated_time==3600
    assert completed.humans[hid]['money']==before.humans[hid]['money']+100
    assert completed.humans[hid]['activity'] is None
    other='human-001'
    assert completed.humans[other]['status']['energy']==before.humans[other]['status']['energy']-1
    assert completed.humans[other]['status']['social']==before.humans[other]['status']['social']-2
    assert len(json.dumps(store.iter_events('gameplay-test')[-1].to_dict()).encode())<262144
    assert store.replay('gameplay-test').state_hash==completed.state_hash


def test_pause_cancels_entire_two_response_batch(game):
    import threading
    engine,store=game
    workers=sorted(h['human_id'] for h in state(game).humans.values() if h['role']=='worker')[:2]
    barrier=threading.Barrier(3);release=threading.Event()
    class Blocking(WorkProvider):
        def complete(self, observation, correction=None):
            barrier.wait(timeout=10);release.wait(timeout=10)
            return super().complete(observation,correction)
    runtime=RuntimeController(engine,store,'gameplay-test',Blocking(),actor_ids=workers,concurrency=2)
    result=[];before=state(game).state_hash
    thread=threading.Thread(target=lambda:result.append(runtime.step()));thread.start()
    try:
        barrier.wait(timeout=10);runtime.pause();release.set();thread.join(timeout=15)
        assert not thread.is_alive() and not result[0]['accepted']
        assert store.event_count('gameplay-test')==0
        assert state(game).state_hash==before
    finally:release.set();runtime.close()


def test_due_engine_continuation_uses_no_fabricated_model_choice(game):
    engine,store=game;before=state(game);hid=next(hid for hid,h in sorted(before.humans.items()) if h['role']=='worker')
    act(game,hid,'work')
    runtime=RuntimeController(engine,store,'gameplay-test',WorkProvider(),actor_ids=[hid])
    try:
        result=runtime.step()
        assert result['accepted'] and result['engine_continuation']
        assert runtime.status()['accepted_decisions']==0
        assert runtime.status()['engine_continuations']==1
        assert state(game).humans[hid]['money']==before.humans[hid]['money']+100
        assert store.iter_events('gameplay-test')[-1].causation['provenance']['kind']=='engine'
    finally:runtime.close()


def test_source_acquisition_world_receipt_is_private_and_replays(game):
    from living_kanto.mechanics.acquisition import source_catalog,quantity
    from test_gameplay import locate
    engine,store=game;hid='human-001'
    station=source_catalog()['stations']['coin_case']
    locate(game,hid,station['map_id'],(station['x'],station['y']))
    assert any(a.action=='acquire_key_gift' for a in engine.legal_actions(state(game),hid))
    after=act(game,hid,'acquire_key_gift',{'gift_id':'coin_case'})
    assert quantity(after.humans[hid],'COIN_CASE')==1
    obs=engine.observation_for(after,hid)
    assert 'coin_case' in obs.self_state['acquisition']['claims']
    assert obs.self_state['last_acquisition']['adaptation']
    assert not any(a.action=='acquire_key_gift' and a.arguments=={'gift_id':'coin_case'} for a in engine.legal_actions(after,hid))
    assert store.replay('gameplay-test').state_hash==after.state_hash


def test_hundred_simultaneous_due_receipts_remain_bounded(game):
    engine,store=game;current=state(game)
    for offset in range(0,100,8):
        current=state(game)
        choices=[{'human_id':hid,'action':'rest','arguments':{},'observation_version':current.state_version,'expected_state_version':current.state_version,'provenance':{'kind':'model','model_id':'scripted-payload-test','test_provider':True},'decision_explanation':'x'*2000} for hid in sorted(current.humans)[offset:offset+8]]
        event,_=engine.build_activity_batch_event(store,'gameplay-test',choices)
        previous=store.get_status('gameplay-test');store.set_status('gameplay-test','running')
        try:engine.commit(store,event)
        finally:store.set_status('gameplay-test',previous)
    event=engine.advance_activities(store,'gameplay-test',allow_future=True)
    assert event
    assert len(json.dumps(event.to_dict()).encode())<262144
    completed=state(game)
    assert all(h['activity'] is None for h in completed.humans.values())
    assert completed.simulated_time==300
    assert store.replay('gameplay-test').state_hash==completed.state_hash


def test_external_change_rejects_entire_batch_without_rebase(game):
    import threading
    from test_gameplay import scenario
    engine,store=game;workers=sorted(h['human_id'] for h in state(game).humans.values() if h['role']=='worker')[:2]
    entered=threading.Barrier(3);release=threading.Event()
    class Blocking(WorkProvider):
        def complete(self,observation,correction=None):
            entered.wait(timeout=10);release.wait(timeout=10)
            return super().complete(observation,correction)
    runtime=RuntimeController(engine,store,'gameplay-test',Blocking(),actor_ids=workers,concurrency=2)
    results=[];thread=threading.Thread(target=lambda:results.append(runtime.step()));thread.start()
    try:
        entered.wait(timeout=10)
        external=scenario(game,[{'op':'set','path':f'humans.{workers[1]}.money','value':123}])
        release.set();thread.join(timeout=15)
        assert not thread.is_alive() and not results[0]['accepted']
        assert state(game).state_hash==external.state_hash
        assert store.event_count('gameplay-test')==1
        assert runtime.status()['accepted_decisions']==0
    finally:release.set();runtime.close()
