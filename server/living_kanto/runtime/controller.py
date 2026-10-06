"""Private human decisions, legacy manual steps and an asynchronous shared clock."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..simulation.engine import EngineError, StaleActionError
from .providers import ProviderError, NumberedDecisionError
from .async_queue import AsyncHumanQueue, MAX_RUNTIME_CONCURRENCY


class RuntimeController(AsyncHumanQueue):
    def __init__(self, engine, store, run_id: str, provider=None, actor_ids=None, concurrency=1):
        if type(concurrency) is not int or not 1<=concurrency<=MAX_RUNTIME_CONCURRENCY:raise ValueError(f"Runtime concurrency must be 1 through {MAX_RUNTIME_CONCURRENCY}")
        self.concurrency=concurrency
        self._discarded=0
        self._inflight_actors=()
        self.engine, self.store, self.run_id, self.provider = engine, store, run_id, provider
        self.shared_lock = threading.RLock()
        self._decision_lock = threading.Lock()
        self._wake = threading.Event()
        self._thread = None
        self._closed = False
        self._generation = 0
        self._running = False
        self._cursor = 0
        self._speed = "fastest"
        self._failure = None
        self._inflight = None
        self._accepted = 0
        self._continued = 0
        self._retries = 0
        self._latencies = []
        _, state, _ = store.load_run(run_id)
        self.actor_ids = tuple(sorted(actor_ids if actor_ids is not None else state.humans))
        if not self.actor_ids or any(actor not in state.humans for actor in self.actor_ids):
            raise ValueError("Runtime requires existing human actors")
        # Recover deterministic ordering from accepted, atomic model receipts.
        # User/Creative commands never advance the human scheduling cursor.
        for event in reversed(store.iter_events(run_id)):
            cause = event.causation
            actor = cause.get("human_id")
            decisions=cause.get('decisions',[])
            order=cause.get('runtime_order',[d.get('human_id') for d in decisions])
            models={d.get('human_id') for d in decisions if d.get('provenance',{}).get('kind')=='model'}
            recent=next((hid for hid in reversed(order) if hid in models and hid in self.actor_ids),None)
            if recent:
                self._cursor=(self.actor_ids.index(recent)+1)%len(self.actor_ids);break
            if cause.get("provenance", {}).get("kind") == "model" and actor in self.actor_ids:
                self._cursor = (self.actor_ids.index(actor) + 1) % len(self.actor_ids)
                break
        store.set_status(run_id, "paused")
        self._shared_runtime = False
        self._init_async_queue()

    def status(self):
        with self.shared_lock:
            _, state, _ = self.store.load_run(self.run_id)
            return {"run_id": self.run_id, "running": self._running, "phase": "running" if self._running else "paused",
                    "speed": self._speed, "failure": dict(self._failure) if self._failure else None,
                    "inflight_actor": self._inflight, "accepted_decisions": self._accepted, "engine_continuations": self._continued,
                    "corrective_retries": self._retries, "queue_depth": len(self._inflight_actors), "concurrency":self.concurrency, "discarded_uncommitted_responses":self._discarded,
                    "clock_mode": "shared" if self._shared_enabled(state) else "legacy",
                    "inflight_actors": list(self._inflight_actors),
                    "pending_requests": sum(not job['future'].done() for job in self._async_jobs.values()),
                    "ready_queue_depth": self._ready_queue_depth,
                    "stale_local_decisions": self._stale_local_decisions,
                    "cancelled_requests": self._cancelled_requests,
                    "clock_lag_seconds": self._clock_lag_seconds,
                    "clock_processing_limited": self._clock_processing_limited,
                    "clock_reanchors": self._clock_reanchors,
                    "actual_simulated_seconds_per_wall_second": self._actual_clock_speed(state),
                    "state_version": state.state_version,
                    "simulated_time": state.simulated_time,
                    "last_decision_seconds": self._latencies[-1] if self._latencies else None,
                    "model": getattr(self.provider, "model_id", None)}

    def start(self, speed="fastest"):
        return self.resume(speed)

    def resume(self, speed=None):
        with self.shared_lock:
            if self._closed:
                raise RuntimeError("Runtime controller is closed")
            if self.provider is None:
                raise ProviderError("No local human model configured")
            if speed is not None and speed not in {"1", "5", "20", "fastest", 1, 5, 20}:
                raise ValueError("Speed must be 1, 5, 20 or fastest")
            if speed is not None:
                self._speed = str(speed)
            if self._shared_supported():
                if speed is None and not self._shared_runtime:
                    self._speed = "1"
                self._start_shared_queue()
                self._shared_runtime = True
            self._failure = None
            self._running = True
            self.store.set_status(self.run_id, "running")
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, name="living-kanto-runtime", daemon=True)
                self._thread.start()
            self._wake.set()
        return self.status()

    def pause(self):
        with self.shared_lock:
            self._generation += 1
            self._running = False
            self._cancel_shared_queue()
            self.store.set_status(self.run_id, "paused")
            self._wake.set()
        return self.status()

    def close(self):
        # Shutdown must remain possible even when integrity reads reject a save.
        with self.shared_lock:
            self._generation += 1
            self._running = False
            self._closed = True
            self._close_shared_queue()
            try:
                self.store.set_status(self.run_id, "paused")
            except (RuntimeError, sqlite3.Error):
                pass
            self._wake.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=0.2)

    def step(self, human_id=None):
        """One accepted action atomically, or pause without changing committed state."""
        if self._shared_runtime and self._running:
            self.pause()
        if not self._decision_lock.acquire(blocking=False):
            raise RuntimeError("A human decision is already in flight")
        try:
            return self._step(human_id)
        finally:
            self._decision_lock.release()

    def _step(self, human_id):
        if self._shared_enabled(self.store.load_run(self.run_id)[1]):
            return self._manual_shared_step(human_id)
        with self.shared_lock:
            if self._closed:
                raise RuntimeError("Runtime controller is closed")
            _, state, _ = self.store.load_run(self.run_id)
            blocker_fn = getattr(self.engine, "runtime_blocker", None)
            blocker = blocker_fn(state) if blocker_fn else None
            if blocker:
                self._failure = dict(blocker)
                self.pause()
                return {"accepted": False, "failure": dict(self._failure)}
            if human_id is not None and human_id not in self.actor_ids:
                raise ValueError("Actor is not scheduled by this runtime")
            advance=getattr(self.engine,'advance_activities',None)
            completed=advance(self.store,self.run_id,allow_future=False) if advance else None
            if completed:
                self._continued+=1;self._failure=None
                return {"accepted":True,"engine_continuation":True,"event_id":completed.event_id,"state_version":completed.state_version}
            candidates = [human_id] if human_id is not None else [
                self.actor_ids[(self._cursor + offset) % len(self.actor_ids)]
                for offset in range(len(self.actor_ids))]
            observation = None
            for candidate in candidates:
                candidate_observation = self.engine.observation_for(state, candidate)
                if candidate_observation.legal_actions:
                    human_id, observation = candidate, candidate_observation
                    break
            if observation is None:
                pending_battle=any(state.humans[candidate].get('battle_id') for candidate in candidates)
                completed=advance(self.store,self.run_id,allow_future=True) if advance and not pending_battle else None
                if completed:
                    self._continued+=1;self._failure=None
                    return {"accepted":True,"engine_continuation":True,"event_id":completed.event_id,"state_version":completed.state_version}
                self._failure = {"human_id": human_id, "reason": "No ready human decision; pending activity or battle input required"}
                self.pause()
                return {"accepted": False, "failure": dict(self._failure)}
            plan = state.humans[human_id].get("active_plan")
            continuation = plan if isinstance(plan, dict) and plan.get("kind") == "journey" and not state.humans[human_id].get("battle_id") else None
            batch_observations=[observation]
            if self.concurrency>1 and not continuation and hasattr(self.engine,'build_activity_batch_event') and any(a.action=='work' for a in observation.legal_actions):
                for candidate in candidates[candidates.index(human_id)+1:]:
                    candidate_observation=self.engine.observation_for(state,candidate)
                    if not candidate_observation.legal_actions:continue
                    if state.humans[candidate].get('active_plan') or not any(a.action=='work' for a in candidate_observation.legal_actions):break
                    batch_observations.append(candidate_observation)
                    if len(batch_observations)>=self.concurrency:break
            generation = self._generation
            self._inflight = human_id
            self._inflight_actors=tuple(obs.human_id for obs in batch_observations)
        started = time.monotonic()
        error = None
        try:
            if self.provider is None and not continuation:
                raise ProviderError("No local human model configured")
            if len(batch_observations)>1:return self._batch_step(batch_observations,generation)
            for attempt in range(1 if continuation else 2):
                try:
                    raw = None if continuation else self.provider.complete(observation.to_dict(), correction=error)
                    choice = {"action": "journey_to", "arguments": {"map_id": continuation["destination_map"]}, "decision_explanation": continuation["explanation"]} if continuation else self._parse(raw, observation)
                    provenance = {**continuation["provenance"], "engine_continuation": True, "continuation_of_state_version": continuation["accepted_state_version"]} if continuation else {"kind": "model", "model_id": self.provider.model_id, "protocol": getattr(self.provider, "protocol", "test"), "observation_hash": observation.observation_hash(), "corrective_retry": attempt == 1, "test_provider": bool(getattr(self.provider, "test_provider", False))}
                    with self.shared_lock:
                        if generation != self._generation or self._closed:
                            return {"accepted": False, "cancelled": True}
                        event, _ = self.engine.build_action_event(
                            self.store, self.run_id, human_id, **choice,
                            observation_version=observation.observation_version,
                            expected_state_version=observation.state_version,
                            decision_provenance=provenance)
                        previous_status = self.store.get_status(self.run_id)
                        self.store.set_status(self.run_id, "running")
                        try:
                            self.engine.commit(self.store, event)
                        finally:
                            self.store.set_status(self.run_id, previous_status)
                        if continuation:self._continued += 1
                        else:self._accepted += 1
                        self._cursor = (self.actor_ids.index(human_id) + 1) % len(self.actor_ids)
                        self._failure = None
                    return {"accepted": True, "engine_continuation": bool(continuation), "event_id": event.event_id, "state_version": event.state_version}
                except StaleActionError:
                    raise
                except (ValueError, EngineError, NumberedDecisionError) as exc:
                    error = str(exc)
                    if continuation:
                        raise EngineError("Accepted journey blocked: " + error) from exc
                    if attempt == 0:
                        self._retries += 1
            raise ProviderError("Local model action rejected after one corrective retry: " + str(error))
        except Exception as exc:
            with self.shared_lock:
                if generation != self._generation or self._closed:
                    return {"accepted": False, "cancelled": True}
                if generation == self._generation:
                    self._failure = {"human_id": human_id, "reason": str(exc),
                                     "observation_version": observation.observation_version}
                    self._running = False
                    self.store.set_status(self.run_id, "paused")
            return {"accepted": False, "failure": self.status()["failure"]}
        finally:
            with self.shared_lock:
                self._inflight = None
                self._inflight_actors=()
                if not continuation:
                    self._latencies.append(time.monotonic() - started)
                    self._latencies = self._latencies[-100:]

    def _batch_step(self,observations,generation):
        def request(obs):
            error=None
            for attempt in range(2):
                try:
                    raw=self.provider.complete(obs.to_dict(),correction=error)
                    choice=self._parse(raw,obs)
                    provenance={'kind':'model','model_id':self.provider.model_id,'protocol':getattr(self.provider,'protocol','test'),'observation_hash':obs.observation_hash(),'corrective_retry':attempt==1,'test_provider':bool(getattr(self.provider,'test_provider',False))}
                    with self.shared_lock:
                        if generation!=self._generation or self._closed:raise RuntimeError('Runtime request cancelled')
                        event,_=self.engine.build_action_event(self.store,self.run_id,obs.human_id,**choice,observation_version=obs.observation_version,expected_state_version=obs.state_version,decision_provenance=provenance)
                    return {'human_id':obs.human_id,**choice,'provenance':provenance,'observation_version':obs.observation_version,'expected_state_version':obs.state_version},event
                except StaleActionError:raise
                except (ValueError,EngineError,NumberedDecisionError) as exc:
                    error=str(exc)
                    if attempt==0:
                        with self.shared_lock:self._retries+=1
            raise ProviderError('Local model batch choice rejected after one corrective retry: '+str(error))
        with ThreadPoolExecutor(max_workers=len(observations),thread_name_prefix='local-human-batch') as pool:
            futures=[pool.submit(request,obs) for obs in observations]
            proposals=[future.result() for future in futures]
        with self.shared_lock:
            if generation!=self._generation or self._closed:return {'accepted':False,'cancelled':True}
            current=self.store.load_run(self.run_id)[1]
            if current.state_version!=observations[0].state_version:raise StaleActionError('Batch observation boundary changed; no proposals committed')
            choices=[proposal[0] for proposal in proposals]
            if all(c['action'] in {'rest','work'} for c in choices):
                event,_=self.engine.build_activity_batch_event(self.store,self.run_id,choices)
                accepted=len(choices);last_actor=choices[-1]['human_id']
            else:
                # General game actions use their original exact baseline; later
                # proposals remain unaccepted and must be observed again.
                event=proposals[0][1];accepted=1;last_actor=choices[0]['human_id'];self._discarded+=len(choices)-1
            status=self.store.get_status(self.run_id);self.store.set_status(self.run_id,'running')
            try:self.engine.commit(self.store,event)
            finally:self.store.set_status(self.run_id,status)
            self._accepted+=accepted;self._cursor=(self.actor_ids.index(last_actor)+1)%len(self.actor_ids);self._failure=None
            return {'accepted':True,'accepted_decisions':accepted,'event_id':event.event_id,'state_version':event.state_version,'atomic_activity_batch':accepted>1}

    @staticmethod
    def _parse(raw: str, observation) -> dict[str, Any]:
        if not isinstance(raw, str) or len(raw) > 32_768:
            raise ValueError("Action response must be a bounded JSON string")
        choice = json.loads(raw)
        if not isinstance(choice, dict) or set(choice) != {"action", "arguments", "decision_explanation"}:
            raise ValueError("Return exactly action, arguments, decision_explanation")
        if not isinstance(choice["decision_explanation"], str) or not 1 <= len(choice["decision_explanation"].strip()) <= 2000:
            raise ValueError("A non-empty explanation of at most 2000 characters is required")
        if not isinstance(choice["arguments"], dict):
            raise ValueError("Action arguments must be an object")
        if not isinstance(choice["action"], str):
            raise ValueError("Action must be a string")
        # Engine validates dynamic text/arguments and current state; reject invented action names here.
        if choice["action"] not in {action.action for action in observation.legal_actions}:
            raise ValueError("Action was not offered by the engine")
        return choice

    def _loop(self):
        while not self._closed:
            if not self._running:
                self._wake.wait(timeout=0.5)
                self._wake.clear()
                continue
            started = time.monotonic()
            if self._shared_runtime:
                self._parallel_iteration()
                self._wake.wait(timeout=self._parallel_wait_delay())
                self._wake.clear()
                continue
            try:
                self.step()
            except RuntimeError:
                self._wake.wait(timeout=0.05)
            if self._speed != "fastest":
                self._wake.wait(timeout=max(0, 1 / int(self._speed) - (time.monotonic() - started)))
                self._wake.clear()
