"""Opt-in local endpoint capacity experiment. Does not mutate the world or start models.

Run through benchmark_provider(provider, observations, requests_per_level=16).
Observations must be representative *private* engine observations; battle coverage
must be supplied separately before this can establish a release capacity gate.
"""
from concurrent.futures import ThreadPoolExecutor
import math
import statistics
import time

from .controller import RuntimeController
from ..simulation.engine import EngineError


def benchmark_provider(provider, observations, requests_per_level=16, *, engine=None, store=None):
    if not observations or requests_per_level < 8:
        raise ValueError("Supply representative observations and at least eight requests per level")
    levels = []
    for concurrency in (1, 2, 4, 8):
        queued_at = time.monotonic()
        def request(index):
            started = time.monotonic()
            observation = observations[index % len(observations)]
            invalid = retries = 0
            correction = None
            for attempt in range(2):
                try:
                    raw = provider.complete(observation.to_dict(), correction=correction)
                    choice = RuntimeController._parse(raw, observation)
                    if engine is not None:
                        if store is None:
                            raise ValueError("Engine validation requires a store")
                        engine.build_action_event(store, observation.run_id, observation.human_id,
                            **choice, observation_version=observation.observation_version,
                            expected_state_version=observation.state_version,
                            decision_provenance={"kind":"model", "model_id":provider.model_id,
                                "benchmark_dry_run":True})
                    return {"accepted": True, "latency_seconds": time.monotonic() - started,
                            "queue_wait_seconds": started - queued_at, "invalid_outputs": invalid,
                            "corrective_retries": retries}
                except (ValueError, EngineError) as exc:
                    invalid += 1
                    correction = str(exc)
                    if attempt == 0:
                        retries += 1
                except Exception:
                    break
            return {"accepted": False, "latency_seconds": time.monotonic() - started,
                    "queue_wait_seconds": started - queued_at, "invalid_outputs": invalid,
                    "corrective_retries": retries}
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            results = list(pool.map(request, range(requests_per_level)))
        duration = time.monotonic() - queued_at
        latencies = sorted(result["latency_seconds"] for result in results)
        accepted = sum(result["accepted"] for result in results)
        levels.append({"concurrency": concurrency, "requests": requests_per_level, "accepted": accepted,
                       "failures": requests_per_level - accepted,
                       "invalid_outputs": sum(result["invalid_outputs"] for result in results),
                       "corrective_retries": sum(result["corrective_retries"] for result in results),
                       "median_seconds": statistics.median(latencies),
                       "p95_seconds": latencies[math.ceil(len(latencies) * .95) - 1],
                       "accepted_per_minute": accepted * 60 / duration,
                       "mean_queue_wait_seconds": statistics.mean(result["queue_wait_seconds"] for result in results),
                       "memory_usage": None, "simulated_time_per_wall_minute": None})
        if accepted != requests_per_level:
            break
    reliable = [level for level in levels if level["failures"] == 0]
    best = max((level["accepted_per_minute"] for level in reliable), default=0)
    selected = next((level["concurrency"] for level in reliable if level["accepted_per_minute"] >= best * .9), None)
    return {"model": provider.model_id, "protocol": getattr(provider, "protocol", "unknown"),
            "levels": levels, "recommended_concurrency": selected,
            "engine_arguments_validated": engine is not None,
            "observation_count": len(observations),
            "battle_observation_count": sum(bool(observation.revealed_battle_info) for observation in observations),
            "max_observation_characters": max(len(__import__('json').dumps(observation.to_dict())) for observation in observations),
            "scope": "Read-only inference capacity experiment; engine arguments validated when engine/store supplied. Resource memory and live simulated throughput remain separate gates",
            "release_capacity_verified": False}
