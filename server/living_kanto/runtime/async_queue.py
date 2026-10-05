"""Independent private human requests with one engine-owned shared clock.

Workers perform inference only. A single pump records completed proposals and
ticks deterministically; no worker reads or changes the canonical store.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import time

from ..simulation.engine import EngineError, StaleActionError
from .providers import ProviderError


class AsyncHumanQueue:
    def _init_async_queue(self):
        self._async_pool = None
        self._async_jobs = {}
        self._async_sequence = 0
        self._dispatch_cursor = self._cursor
        self._ready_queue_depth = 0
        self._stale_local_decisions = 0
        self._cancelled_requests = 0
        self._clock_anchor_wall = time.monotonic()
        self._clock_anchor_time = 0
        self._clock_measure_wall = None
        self._clock_measure_time = 0
        self._clock_lag_seconds = 0
        self._clock_processing_limited = False
        self._clock_reanchors = 0
        self._last_parallel_time = 0
        self._last_shared_due = None

    def _shared_supported(self):
        return all(callable(getattr(self.engine, name, None)) for name in (
            'activate_shared_clock', 'shared_clock_enabled', 'shared_actor_ready',
            'capture_decision_boundary', 'build_revalidated_action_event',
            'next_shared_due', 'tick_shared_time'))

    def _shared_enabled(self, state):
        return self._shared_supported() and self.engine.shared_clock_enabled(state)

    def _start_shared_queue(self):
        self.engine.activate_shared_clock(self.store, self.run_id)
        state = self.store.load_run(self.run_id)[1]
        self._clock_anchor_time = state.simulated_time
        self._clock_anchor_wall = time.monotonic()
        self._clock_measure_wall = self._clock_anchor_wall
        self._clock_measure_time = state.simulated_time
        if self._async_pool is None:
            # The hard worker cap remains bounded across pause/resume. Old HTTP
            # calls retire in the same pool and still occupy dispatch capacity.
            self._async_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix='kanto-human')

    def _cancel_shared_queue(self):
        for job in self._async_jobs.values():
            job['future'].cancel()
        self._inflight = None
        self._inflight_actors = ()

    def _close_shared_queue(self):
        self._cancel_shared_queue()
        if self._async_pool is not None:
            self._async_pool.shutdown(wait=False, cancel_futures=True)

    def _request_human(self, observation, correction):
        # The worker has a private observation, never a world state or store.
        raw = self.provider.complete(observation.to_dict(), correction=correction)
        return self._parse(raw, observation)

    def _submit_human(self, observation, token, *, prior=None, correction=None):
        if prior is None:
            self._async_sequence += 1
            job = {'sequence': self._async_sequence, 'generation': self._generation,
                   'observation': observation, 'token': token,
                   'attempt': 0, 'started': time.monotonic()}
        else:
            job = prior
            job['attempt'] += 1
        job['future'] = self._async_pool.submit(self._request_human, observation, correction)
        job['future'].add_done_callback(lambda future: self._wake.set())
        self._async_jobs[observation.human_id] = job

    def _update_async_status(self):
        active = sorted((job for job in self._async_jobs.values()
                         if job['generation'] == self._generation), key=lambda job: job['sequence'])
        self._inflight_actors = tuple(job['observation'].human_id for job in active)
        self._inflight = self._inflight_actors[0] if self._inflight_actors else None

    def _shared_failure(self, actor, reason, observation_version=None, details=None):
        self._failure = {**(details or {}), 'human_id': actor, 'reason': str(reason)}
        if observation_version is not None:
            self._failure['observation_version'] = observation_version
        self._generation += 1
        self._running = False
        self.store.set_status(self.run_id, 'paused')
        self._cancel_shared_queue()
        self._wake.set()

    def _complete_human_requests(self):
        completed = sorted((job for job in self._async_jobs.values() if job['future'].done()),
                           key=lambda job: job['sequence'])
        for job in completed:
            obs = job['observation']
            actor = obs.human_id
            self._async_jobs.pop(actor, None)
            if job['generation'] != self._generation or self._closed:
                self._cancelled_requests += 1
                continue
            try:
                choice = job['future'].result()
                provenance = {'kind': 'model', 'model_id': self.provider.model_id,
                    'protocol': getattr(self.provider, 'protocol', 'test'),
                    'observation_hash': obs.observation_hash(),
                    'original_observation_version': obs.observation_version,
                    'dispatch_order': job['sequence'],
                    'corrective_retry': job['attempt'] == 1,
                    'test_provider': bool(getattr(self.provider, 'test_provider', False))}
                event, _ = self.engine.build_revalidated_action_event(
                    self.store, self.run_id, actor, choice,
                    original_observation_version=obs.observation_version,
                    dependency_token=job['token'], provenance=provenance)
                # Generation/closed cannot change here: the pump owns shared_lock.
                self.engine.commit(self.store, event)
                self._accepted += 1
                self._cursor = (self.actor_ids.index(actor) + 1) % len(self.actor_ids)
                self._failure = None
                self._latencies.append(time.monotonic() - job['started'])
                self._latencies = self._latencies[-100:]
            except StaleActionError:
                # Only this individual's dependency changed. Rejoin the fair
                # queue with a fresh observation, without rejecting other minds.
                self._stale_local_decisions += 1
                self._discarded += 1
            except ProviderError as exc:
                self._shared_failure(actor, exc, obs.observation_version)
                break
            except (ValueError, EngineError) as exc:
                if job['attempt'] == 0:
                    self._retries += 1
                    self._submit_human(obs, job['token'], prior=job, correction=str(exc))
                else:
                    self._shared_failure(actor, 'Local model action rejected after one corrective retry: '+str(exc), obs.observation_version)
                    break
            except Exception as exc:
                self._shared_failure(actor, exc, obs.observation_version)
                break
        self._update_async_status()

    def _actual_clock_speed(self, state):
        if self._clock_measure_wall is None:return None
        elapsed=time.monotonic()-self._clock_measure_wall
        return round((state.simulated_time-self._clock_measure_time)/elapsed,3) if elapsed>0 else None

    def _parallel_wait_delay(self):
        if self._speed=='fastest':return 0.001 if self._last_shared_due is not None else 0.5
        next_wall=self._clock_anchor_wall+(self._last_parallel_time+1-self._clock_anchor_time)/int(self._speed)
        return min(0.5,max(0.001,next_wall-time.monotonic()))

    def _tick_parallel_clock(self, state):
        fastest=self._speed=='fastest'
        desired=self.engine.next_shared_due(state) if fastest else int(
            self._clock_anchor_time+(time.monotonic()-self._clock_anchor_wall)*int(self._speed))
        if desired is None:return
        if desired<state.simulated_time:
            self._clock_anchor_time=state.simulated_time;self._clock_anchor_wall=time.monotonic()
            return
        started=time.monotonic();steps=0
        while True:
            due=self.engine.next_shared_due(state)
            target=min(desired,state.simulated_time+10)
            if due is not None and state.simulated_time<due<target:target=due
            if target<=state.simulated_time and not (due is not None and due<=state.simulated_time):break
            event=self.engine.tick_shared_time(self.store,self.run_id,target)
            if event:self._continued+=1
            state=self.store.load_run(self.run_id)[1];steps+=1
            if fastest or state.simulated_time>=desired or not event:break
            # A requested speed must not starve completed minds when hashing/
            # mechanics run slower. Drop wall-clock backlog, begin responses at
            # the current canonical time, and report the measured speed/lag.
            if steps>=10 or time.monotonic()-started>=0.05:break
        self._clock_lag_seconds=max(0,desired-state.simulated_time)
        self._clock_processing_limited=not fastest and self._clock_lag_seconds>0
        if self._clock_processing_limited:
            self._clock_anchor_time=state.simulated_time;self._clock_anchor_wall=time.monotonic()
            self._clock_reanchors+=1

    def _dispatch_ready_humans(self, state):
        capacity = max(0, self.concurrency - len(self._async_jobs))
        waiting = []
        for offset in range(len(self.actor_ids)):
            index = (self._dispatch_cursor + offset) % len(self.actor_ids)
            actor = self.actor_ids[index]
            if actor not in self._async_jobs and self.engine.shared_actor_ready(state, actor):
                waiting.append((index, actor))
        self._ready_queue_depth = len(waiting)
        dispatched = 0
        for index, actor in waiting:
            if dispatched >= capacity:
                break
            observation, token = self.engine.capture_decision_boundary(state, actor)
            self._dispatch_cursor = (index + 1) % len(self.actor_ids)
            if not observation.legal_actions:
                continue
            self._submit_human(observation, token)
            dispatched += 1
        self._ready_queue_depth = max(0, self._ready_queue_depth - dispatched)
        self._update_async_status()

    def _manual_shared_step(self, human_id):
        """A paused shared save accepts one intention or advances one due tick."""
        with self.shared_lock:
            if self._closed:raise RuntimeError('Runtime controller is closed')
            if human_id is not None and human_id not in self.actor_ids:
                raise ValueError('Actor is not scheduled by this runtime')
            state=self.store.load_run(self.run_id)[1]
            blocker=getattr(self.engine,'runtime_blocker',lambda state:None)(state)
            if blocker:
                self._failure=dict(blocker)
                return {'accepted':False,'failure':dict(blocker)}
            candidates=[human_id] if human_id else [self.actor_ids[(self._cursor+i)%len(self.actor_ids)] for i in range(len(self.actor_ids))]
            observation=None
            for actor in candidates:
                if self.engine.shared_actor_ready(state,actor):
                    candidate,token=self.engine.capture_decision_boundary(state,actor)
                    if candidate.legal_actions:observation=candidate;break
            if observation is None:
                due=self.engine.next_shared_due(state)
                if due is not None:
                    prior=self.store.get_status(self.run_id);self.store.set_status(self.run_id,'running')
                    try:event=self.engine.tick_shared_time(self.store,self.run_id,min(due,state.simulated_time+10))
                    finally:self.store.set_status(self.run_id,prior)
                    if event:
                        self._continued+=1
                        return {'accepted':True,'engine_continuation':True,'event_id':event.event_id,'state_version':event.state_version}
                return {'accepted':False,'failure':{'human_id':human_id,'reason':'No ready human or accepted shared-clock boundary'}}
            # Cancelled HTTP calls still count against the configured capacity.
            retiring=sum(not job['future'].done() for job in self._async_jobs.values())
            if retiring>=self.concurrency:
                return {'accepted':False,'pending_requests':retiring,'reason':'Paused human requests are still retiring; no replacement choice was requested'}
            generation=self._generation
            self._inflight=observation.human_id;self._inflight_actors=(observation.human_id,)
        started=time.monotonic();error=None
        try:
            if self.provider is None:raise ProviderError('No local human model configured')
            for attempt in range(2):
                raw=self.provider.complete(observation.to_dict(),correction=error)
                try:
                    choice=self._parse(raw,observation)
                    provenance={'kind':'model','model_id':self.provider.model_id,'protocol':getattr(self.provider,'protocol','test'),
                        'observation_hash':observation.observation_hash(),'original_observation_version':observation.observation_version,
                        'corrective_retry':attempt==1,'test_provider':bool(getattr(self.provider,'test_provider',False))}
                    with self.shared_lock:
                        if generation!=self._generation or self._closed:return {'accepted':False,'cancelled':True}
                        event,_=self.engine.build_revalidated_action_event(self.store,self.run_id,observation.human_id,choice,
                            original_observation_version=observation.observation_version,dependency_token=token,provenance=provenance)
                        prior=self.store.get_status(self.run_id);self.store.set_status(self.run_id,'running')
                        try:self.engine.commit(self.store,event)
                        finally:self.store.set_status(self.run_id,prior)
                        self._accepted+=1;self._cursor=(self.actor_ids.index(observation.human_id)+1)%len(self.actor_ids);self._failure=None
                    return {'accepted':True,'event_id':event.event_id,'state_version':event.state_version}
                except StaleActionError:raise
                except (ValueError,EngineError) as exc:
                    error=str(exc)
                    if attempt==0:self._retries+=1
            raise ProviderError('Local model action rejected after one corrective retry: '+str(error))
        except Exception as exc:
            with self.shared_lock:
                if generation!=self._generation or self._closed:return {'accepted':False,'cancelled':True}
                self._failure={'human_id':observation.human_id,'reason':str(exc),'observation_version':observation.observation_version}
            return {'accepted':False,'failure':dict(self._failure)}
        finally:
            with self.shared_lock:
                self._inflight=None;self._inflight_actors=()
                self._latencies.append(time.monotonic()-started);self._latencies=self._latencies[-100:]

    def _parallel_iteration(self):
        # A manual step and the asynchronous commit pump cannot mutate together.
        if not self._decision_lock.acquire(blocking=False):
            return
        try:
            with self.shared_lock:
                if not self._running or self._closed:
                    return
                state = self.store.load_run(self.run_id)[1]
                blocker = getattr(self.engine, 'runtime_blocker', lambda state: None)(state)
                if blocker:
                    self._shared_failure(blocker.get('human_id'), blocker.get('reason', str(blocker)), details=blocker)
                    return
                # Retire cancelled generations even when they completed after a
                # previous pause. Capacity remains bounded until they retire.
                for actor, job in list(self._async_jobs.items()):
                    if job['generation'] != self._generation and job['future'].done():
                        self._async_jobs.pop(actor)
                        self._cancelled_requests += 1
                self._tick_parallel_clock(state)
                self._complete_human_requests()
                if self._running:
                    current=self.store.load_run(self.run_id)[1]
                    self._dispatch_ready_humans(current)
                    self._last_parallel_time=current.simulated_time
                    self._last_shared_due=self.engine.next_shared_due(current)
        except Exception as exc:
            with self.shared_lock:
                if not self._closed:
                    self._shared_failure(None, exc)
        finally:
            self._decision_lock.release()
