# Living Kanto

Primary development now lives on Jetson (`/home/jetson/projects/living-kanto`); Spark worker1 runs the live simulation and local inference. The Mac copy in `Desktop/Project/living-kanto` is a preserved mirror. Read [development locations and workflow](docs/DEVELOPMENT_HOME.md) before making changes. The local startup below is for isolated development worlds, not the existing production save.

This is the direct-build working application for the Pokémon FireRed world described in [the project guide](docs/PROJECT_GUIDE.md). OpenRig is stopped and is not required to launch this build. Human decisions use an explicitly configured local model. Without one, worlds remain paused and can be inspected; there is no scripted or cloud fallback.

## Run locally

Python 3.10+ and Node.js/npm are required. This build was exercised with Python 3.14 on macOS. From this directory:

```sh
bash tools/setup_local.sh
bash tools/run_local.sh
```

Open http://localhost:8877. Create a world, choose Observer, Survival, or Creative, and inspect the population. Each new world starts paused with exactly 100 AI humans. Survival adds one separately identified player. Configure the local endpoint and model in the viewer before stepping or resuming AI. Start with one mind at a time: the small live-worker benchmark selected 1, while the earlier read-only endpoint benchmark selected 2. These measurements cover different workloads. You can reopen a saved world directly with `/?world=its-world-name`. Endpoint settings are not included in exported saves.

The existing development environment is already installed in `.venv`. Data lives in `data/local`; each world has its own SQLite database. Pause a world before copying its database. Canonical event replay reconstructs state without inference.

For an OpenAI-compatible local server, a launch configuration can also use:

```sh
export LIVING_KANTO_MODEL_ENDPOINT=http://127.0.0.1:18080/v1
export LIVING_KANTO_MODEL=your-local-model
bash tools/run_local.sh
```

Ollama is supported through `LIVING_KANTO_MODEL_PROTOCOL=ollama`. The application accepts local/private network endpoints and rejects public model hosts. It does not start or restart a model server automatically.

## Verification

```sh
.venv/bin/python -m pytest -q server/tests
```

The reference data is derived from the pinned `pret/pokefirered` source revision `037335f4c725d7c9aecdac87066f2002b4bd7e14`. Setup fetches that reference if it is missing; mechanics currently read its source tables at runtime. The current workspace already contains it. Content receipts, imported assets, and tests record their source. Gen III battles run through the locally installed, pinned Pokémon Showdown simulator, with serialized decisions and deterministic seeds.

Actual local inference and capacity reports are in `evidence/direct-build`. The capacity experiment exercised concurrency 1, 2, 4, and 8 using everyday and battle observations. It was read-only and recommends 2 for that endpoint. A separate small live-worker benchmark recommends 1, the lowest setting within 10% of its best accepted throughput. Higher settings discarded more freely chosen responses after world changes. Both reports record their scopes; the live test shared resources with the soak and legal trial. The viewer supports 1–8 concurrent local requests. Only disjoint work/rest intentions from the identical baseline commit as a batch; general actions commit serially, and uncommitted responses are discarded for a fresh observation.

## Release status

This is a working development build, with the full guide's release gate open. Imported map inventory, population, battle/lifecycle mechanics, private local inference, atomic saves, and replay have implementation and test evidence. Source field puzzles, progression stations, items, individual ownership, activity timing and source graphics are implemented with focused verification. The complete legal mainland/league journey, exhaustive required-effect fidelity, a two-hour soak after the final service repair, and an autonomous zero-badge championship still have open acceptance gates. The earlier two-hour integrity soak and real-model repair recovery are preserved separately in the direct-build report. A configured model making one decision or a test trainer winning Brock is not proof of autonomous completion.

Use `tools/soak_runtime.py` for a bounded, auditable actual-model world run. It creates a fresh zero-event Observer world, records failures, separate model/engine counts, actor coverage and frozen runtime source fingerprints, checks replay, and stops after the requested duration. It never awards achievements or substitutes decisions. Its report explicitly distinguishes a soak from championship proof.

## Demonstration saves

The local `viewer-current-review` world is a clean Survival demonstration: a source starter, keyboard movement and an actual wild-battle victory, with no Creative changes. Its portable bundle is `evidence/direct-build/survival-demonstration-save.json`. Select the existing world in this workspace, or import the bundle in a fresh installation; importing never overwrites an existing world name.

The final real-model Observer world is `final-world-soak`. Its frozen-soak snapshot, focused continuation and repaired continuation are exported separately as `observer-soak-demonstration-save.json`, `observer-focused-demonstration-save.json` and `observer-repaired-demonstration-save.json` under `evidence/direct-build`. The existing local world includes the repaired continuation; it and the clean player demo are paused with the local Qwen38 connection configured. Creative Mansion, Seafoam and doubles worlds are explicitly marked UI fixtures. They are separate from legal progression and autonomous evidence.

For an offline save export, `tools/export_run.py --database PATH --run-id NAME --output FILE` uses a coherent read-only backup, checks replay and omits inference connection settings.
