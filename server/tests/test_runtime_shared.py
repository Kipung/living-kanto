"""Real engine shared-clock tests with explicitly identified TEST human minds."""
import json
import threading
import time
from pathlib import Path

import pytest

from living_kanto.runtime import RuntimeController
from living_kanto.simulation.world import WorldEngine
from living_kanto.store import RunStore
from test_simulation_m0 import write_fixture_map


def wait_until(predicate,seconds=10):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        if predicate():return
        time.sleep(0.01)
    raise AssertionError('Bounded asynchronous condition was not reached')


def response(action='wait',arguments=None):
    return json.dumps({'action':action,'arguments':arguments or {},
        'decision_explanation':'Identified TEST mind chooses its own offered action.'})


def create_fixture_run(engine,store,run_id,actors):
    # M0's declared roster uses its legacy map identifier. Normalize through a
    # recorded fixture event so source gameplay sees the actual Pallet header.
    (engine.content_root/'region.json').write_text(json.dumps({'encounters':[]}))
    maps=engine.maps;engine.maps={'pallet-town':maps['pallet-town']}
    engine.create_run(store,run_id=run_id,humans=[(actor,actor.title()) for actor in actors])
    engine.maps=maps
    engine.commit_changes(store,run_id,[{'op':'set','path':f'humans.{actor}.map_id','value':'PalletTown'} for actor in actors],
        kind='world.public_event',actor='engine',explanation='Recorded TEST fixture source-map identifier normalization',
        provenance={'kind':'engine'},expected_version=0)


class ConcurrentProvider:
    model_id='scripted-shared-runtime-test-only'
    protocol='test'
    test_provider=True

    def __init__(self,hold=None,moving=None):
        self.hold=hold;self.moving=moving
        self.release=threading.Event();self.lock=threading.Lock()
        self.joined=threading.Barrier(2) if hold else None
        self.calls=[];self.active=0;self.maximum_active=0

    def complete(self,observation,correction=None):
        actor=observation['human_id']
        with self.lock:
            count=sum(obs['human_id']==actor for obs,_ in self.calls)
            self.calls.append((observation,correction))
            self.active+=1;self.maximum_active=max(self.maximum_active,self.active)
        try:
            if self.joined is not None and count==0 and actor in {'alice','bob'}:
                self.joined.wait(timeout=10)
            if actor==self.hold and count==0:
                if not self.release.wait(25):raise RuntimeError('TEST barrier timed out')
            if actor==self.moving:
                if count==0:
                    return response('walk_to',{'direction':'south'})
                return response('rest')
            return response()
        finally:
            with self.lock:self.active-=1


@pytest.fixture
def shared_world(tmp_path):
    write_fixture_map(tmp_path,width=14,height=14)
    engine=WorldEngine(tmp_path)
    store=RunStore(tmp_path/'shared.db')
    create_fixture_run(engine,store,'shared',['alice','bob'])
    yield engine,store
    store.close()


def test_parallel_private_calls_and_movement_while_other_mind_blocked(shared_world):
    engine,store=shared_world;provider=ConcurrentProvider(hold='bob',moving='alice')
    controller=RuntimeController(engine,store,'shared',provider,concurrency=2)
    initial=store.load_run('shared')[1];y=initial.humans['alice']['y']
    try:
        controller.resume('1')
        wait_until(lambda:provider.maximum_active>=2)
        wait_until(lambda:store.load_run('shared')[1].humans['alice']['y']==y+1)
        assert not provider.release.is_set()
        observed_bob=next(obs for obs,_ in provider.calls if obs['human_id']=='bob')
        provider.release.set()
        wait_until(lambda:store.load_run('shared')[1].humans['bob'].get('last_decision',{}).get('action')=='wait')
        controller.pause();final=store.load_run('shared')[1]
        decision=final.humans['bob']['last_decision']
        assert decision['observation_version']==observed_bob['observation_version']
        assert decision['provenance']['validation_boundary_version']>observed_bob['state_version']
        assert controller.status()['stale_local_decisions']==0
        assert store.replay('shared').state_hash==final.state_hash
        for obs,_ in provider.calls:
            assert 'world_facts' not in obs and 'humans' not in obs
    finally:
        provider.release.set();controller.close()


def test_pause_discards_late_response_and_restart_preserves_shared_save(shared_world):
    engine,store=shared_world;provider=ConcurrentProvider(hold='bob',moving='alice')
    controller=RuntimeController(engine,store,'shared',provider,concurrency=2)
    try:
        controller.resume('1');wait_until(lambda:provider.maximum_active>=2)
        controller.pause();version=store.load_run('shared')[1].state_version
        provider.release.set();wait_until(lambda:provider.active==0)
        time.sleep(0.05)
        assert store.load_run('shared')[1].state_version==version
        controller.close()
        restarted=RuntimeController(engine,store,'shared',provider,concurrency=2)
        try:
            assert restarted.status()['phase']=='paused'
            assert restarted.status()['clock_mode']=='shared'
            assert restarted.status()['state_version']==version
        finally:restarted.close()
    finally:provider.release.set();controller.close()


def test_fair_queue_reaches_all_hundred_people(tmp_path):
    write_fixture_map(tmp_path,width=14,height=14);engine=WorldEngine(tmp_path)
    store=RunStore(tmp_path/'hundred.db');actors=[f'human-{i:03}' for i in range(100)]
    create_fixture_run(engine,store,'hundred',actors)
    provider=ConcurrentProvider();controller=RuntimeController(engine,store,'hundred',provider,concurrency=4)
    try:
        controller.resume('fastest')
        wait_until(lambda:set(obs['human_id'] for obs,_ in provider.calls)==set(actors),seconds=30)
        controller.pause()
        assert provider.maximum_active<=4
        assert set(obs['human_id'] for obs,_ in provider.calls[:100])==set(actors)
        assert controller.status()['failure'] is None
    finally:controller.close();store.close()


def test_slow_ticks_at_requested_twenty_do_not_starve_completed_decisions(shared_world,monkeypatch):
    engine,store=shared_world;provider=ConcurrentProvider()
    tick=engine.tick_shared_time
    def slow_tick(*args):
        time.sleep(0.08)
        return tick(*args)
    monkeypatch.setattr(engine,'tick_shared_time',slow_tick)
    controller=RuntimeController(engine,store,'shared',provider,concurrency=2)
    try:
        controller.resume('20')
        wait_until(lambda:controller.status()['accepted_decisions']>=6)
        controller.pause();status=controller.status()
        assert status['clock_reanchors']>0
        assert status['actual_simulated_seconds_per_wall_second']<20
        assert store.load_run('shared')[1].simulated_time>0
    finally:controller.close()


def test_local_change_refreshes_only_that_human(shared_world):
    engine,store=shared_world;provider=ConcurrentProvider(hold='bob',moving='alice')
    controller=RuntimeController(engine,store,'shared',provider,concurrency=2)
    try:
        controller.resume('1');wait_until(lambda:provider.maximum_active>=2)
        with controller.shared_lock:
            state=store.load_run('shared')[1]
            engine.commit_changes(store,'shared',[{'op':'set','path':'humans.bob.money','value':3001}],
                kind='world.public_event',actor='bob',explanation='Explicit TEST fixture local change',
                provenance={'kind':'user'},expected_version=state.state_version)
        provider.release.set()
        wait_until(lambda:controller.status()['stale_local_decisions']==1)
        wait_until(lambda:store.load_run('shared')[1].humans['bob'].get('last_decision',{}).get('action')=='wait')
        controller.pause()
        assert controller.status()['failure'] is None
        assert sum(obs['human_id']=='bob' for obs,_ in provider.calls)>=2
        assert store.load_run('shared')[1].humans['alice'].get('last_decision')
    finally:provider.release.set();controller.close()


def test_manual_step_in_activated_save_accepts_then_ticks_movement(shared_world):
    engine,store=shared_world;provider=ConcurrentProvider(moving='alice')
    engine.activate_shared_clock(store,'shared')
    controller=RuntimeController(engine,store,'shared',provider,actor_ids=['alice'])
    try:
        initial=store.load_run('shared')[1];y=initial.humans['alice']['y']
        assert controller.step('alice')['accepted']
        accepted=store.load_run('shared')[1]
        assert accepted.simulated_time==initial.simulated_time
        assert accepted.humans['alice']['y']==y
        assert accepted.humans['alice']['movement_intent']
        result=controller.step('alice')
        assert result['accepted'] and result['engine_continuation']
        final=store.load_run('shared')[1]
        assert final.humans['alice']['y']==y+1
        assert final.simulated_time==initial.simulated_time+1
        assert store.replay('shared').state_hash==final.state_hash
    finally:controller.close()


def test_slow_observation_preparation_yields_to_clock_and_completed_minds(tmp_path,monkeypatch):
    write_fixture_map(tmp_path,width=14,height=14);engine=WorldEngine(tmp_path)
    store=RunStore(tmp_path/'slow-preparation.db')
    actors=['alice','bob','carol','dave']
    create_fixture_run(engine,store,'slow-preparation',actors)
    captures=[];capture=engine.capture_decision_boundary
    def slow_capture(state,actor):
        captures.append({'actor':actor,'simulated_time':state.simulated_time,
            'accepted_before':sum(h.get('last_decision',{}).get('provenance',{}).get('kind')=='model' for h in state.humans.values())})
        time.sleep(0.06)
        return capture(state,actor)
    monkeypatch.setattr(engine,'capture_decision_boundary',slow_capture)
    provider=ConcurrentProvider()
    controller=RuntimeController(engine,store,'slow-preparation',provider,concurrency=4)
    try:
        controller.resume('20')
        wait_until(lambda:len(captures)>=4)
        controller.pause()
        assert [row['actor'] for row in captures[:4]]==actors
        assert captures[1]['simulated_time']>captures[0]['simulated_time']
        assert captures[1]['accepted_before']>=1
        assert captures[3]['accepted_before']>=2
        assert provider.maximum_active<=4
        final=store.load_run('slow-preparation')[1]
        assert store.replay('slow-preparation').state_hash==final.state_hash
    finally:controller.close();store.close()
