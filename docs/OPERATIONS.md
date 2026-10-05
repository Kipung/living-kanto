# Living Kanto local operations

The current working application is the separate macOS checkout linked from README.md. OpenRig and its old dispatcher are stopped. Archived OpenRig instructions in docs/history are historical records and must not be used to restart it.

## Launch and model connection

Run `bash tools/setup_local.sh` once, then `bash tools/run_local.sh`; open http://localhost:8877. The service binds loopback by default. Worlds start paused. In “Local mind connection,” enter a local OpenAI-compatible endpoint and its actual model identifier. Ollama configuration is also supported through environment variables described in README.md. Start with one concurrent mind based on the small live-worker benchmark; increase only with measurements for your actual workload. The earlier read-only endpoint benchmark recommended two. No cloud or scripted fallback is supplied. Development agents are separate from the 100 runtime humans.

## Controls

Create a named world with Observer, Survival, or Creative. Each contains exactly 100 AI people. Survival adds one separately identified user trainer. “Switch mode” saves a mode-change event in the same world; it pauses AI at a safe decision boundary. Creative changes remain permanently marked after leaving Creative. Select a person to inspect their personality, interests, goals, relationships, memories, party, and badges. These personal beliefs are distinct from factual event history. Follow keeps the camera on the selected person. The source-based region overview changes the observer camera; it does not move anyone.

The trainer action list shows currently legal engine actions. Choose one and perform it; arrow keys use cardinal movement. Text actions accept a message, goal, or memory. Double battles show one choice for each active Pokémon, and the simulator validates the pair before committing it. Creative controls modify the selected person and always record authorship and changes. Requested speed changes pacing; actual throughput depends on inference.

## Save, restart, replay

Pause before copying a database. Data is stored under data/local as one SQLite database per world. Export provides a portable, hash-verified genesis and event history without connection settings or credentials. Import validates every event and final state in a temporary store before installing it; an existing world name is not replaced. Replay reconstructs a saved state without asking a model and shows only history up to the selected event. Action controls and keyboard movement are disabled during replay; choose Return to live to act.

Restarting the service preserves committed state. Configure the local connection again if required, then resume. A failed or invalid model decision pauses AI without inventing an action. One corrective retry is allowed; repeated invalid output is recorded as a failure. Missing local inference leaves the world available for inspection. Invalid, stale, or corrupted history is rejected. Never repair it by changing rows directly or deleting the evidence.

## Verification and acceptance

Run `.venv/bin/python -m pytest -q server/tests`. Tests use identified fixtures and scripted test minds where stated; their successes are not autonomous evidence. Real local inference, capacity measurements, traversal audit, legal test journeys, and soak reports are in evidence/. Read each report's scope and source fingerprint. A running soak is not a completed two-hour test. A first-gym victory is not a full regional or autonomous championship.

Use tools/soak_runtime.py for a bounded real-model run and tools/verify_legal_journey.py for an explicitly scripted legal reachability test. Keep the full PROJECT_GUIDE acceptance gate open until its evidence exists. No process should automatically restart OpenRig or its model guards.

## Current handoff

The loopback game and separate Qwen38 runtime-human endpoint remain available, with the clean player demo and actual-model world paused. The endpoint is currently forwarded to 127.0.0.1:18880/v1; its local settings stay outside portable saves. OpenRig's worker service is disabled, has no process/listener and its supervisor is paused. Unrelated terminal sessions and the standalone ResumeCompiler application are preserved. If the endpoint stops, reconnect a local model explicitly; the app will pause without a replacement action. The final queue repair and its source boundary are documented in DIRECT_BUILD_REPORT.md.
