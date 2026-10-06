"""Bounded slow cognition beside the immediate decision queue."""
from concurrent.futures import ThreadPoolExecutor
import time
from ..simulation import cognition
from ..simulation.engine import StaleActionError


class DeliberationQueue:
    def _init_deliberation(self):
        self._thought_jobs = {}; self._thought_pool = None; self._thought_last = {}
        self._thought_accepted = 0; self._thought_stale = 0; self._thought_failure = None; self._thought_cursor = 0

    def _thought_capacity(self):
        # At least 75% of capacity remains reserved for immediate decisions.
        return min(4, self.concurrency // 4)

    def _cancel_deliberation(self):
        for job in self._thought_jobs.values(): job['future'].cancel()

    def _close_deliberation(self):
        self._cancel_deliberation()
        if self._thought_pool: self._thought_pool.shutdown(wait=False, cancel_futures=True)

    def _prepare_and_think(self, state, actor, generation):
        observation, token = cognition.capture(self.engine, state, actor)
        correction = None
        for attempt in range(2):
            try:
                choice = self._request_human(observation, correction, generation)
                cognition.validate_choice(choice, observation)
                return observation, token, choice, attempt
            except (ValueError, cognition.EngineError) as exc:
                if attempt or generation != self._generation or self._closed: raise
                correction = str(exc)

    def _pump_deliberation(self, state):
        drain_started = time.monotonic()
        for actor, job in list(self._thought_jobs.items()):
            if not job['future'].done(): continue
            self._thought_jobs.pop(actor)
            try:
                obs, token, choice, attempt = job['future'].result()
                if job['generation'] != self._generation or self._closed:
                    self._trace_outcome(obs, choice, 'cancelled', reason='Runtime generation changed'); continue
                provenance = {'kind': 'model', 'model_id': self.provider.model_id,
                    'protocol': getattr(self.provider, 'protocol', 'test'),
                    'test_provider': bool(getattr(self.provider, 'test_provider', False)),
                    'observation_hash': obs.observation_hash(), 'cognitive_channel': 'deliberation', 'corrective_retry': bool(attempt)}
                event, _ = cognition.build_event(self.engine, self.store, self.run_id, actor, choice, obs, token, provenance)
                self.engine.commit(self.store, event); self._trace_outcome(obs, choice, 'accepted', event=event)
                self._thought_accepted += 1; self._thought_failure = None
            except StaleActionError:
                self._thought_stale += 1; self._trace_outcome(obs, choice, 'stale', reason='Background context superseded')
            except Exception as exc:
                if job['generation'] != self._generation or self._closed: continue
                # Optional thinking has no unresolved physical decision.
                self._thought_failure = {'human_id': actor, 'reason': str(exc)}
            if time.monotonic() - drain_started >= 0.1:
                self._wake.set()
                break
        capacity = self._thought_capacity()
        if not capacity or not self._running: return
        if self._thought_pool is None:
            self._thought_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='kanto-deliberation')
        state = self.store.load_run(self.run_id)[1]
        origin = self._thought_cursor
        for offset in range(len(self.actor_ids)):
            if len(self._thought_jobs) >= capacity or len(self._async_jobs) + len(self._thought_jobs) >= self.concurrency: break
            index = (origin + offset) % len(self.actor_ids)
            actor = self.actor_ids[index]; h = state.humans[actor]
            last_wall, last_sim = self._thought_last.get(actor, (-1e9, -1000000))
            if actor in self._thought_jobs or h.get('battle_id') or h.get('role') == 'user_trainer': continue
            if not (h.get('movement_intent') or h.get('activity')): continue
            if time.monotonic() - last_wall < 30 or state.simulated_time - last_sim < 300: continue
            self._thought_last[actor] = (time.monotonic(), state.simulated_time)
            future = self._thought_pool.submit(self._prepare_and_think, state, actor, self._generation)
            future.add_done_callback(lambda future: self._wake.set())
            self._thought_jobs[actor] = {'generation': self._generation, 'future': future}
            self._thought_cursor = (index + 1) % len(self.actor_ids)
