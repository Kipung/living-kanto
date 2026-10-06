# Living Kanto

A persistent Pokémon world where 100 AI-driven people live their own lives: travelling, working, talking, caring for Pokémon, and pursuing ambitions in a shared Kanto.

Living Kanto explores what happens when local language models make individual decisions inside a world with consistent rules and lasting consequences. Trainers can pursue badges, residents can build relationships, and everyday routines continue alongside battles and journeys. The long-term goal is to observe distinct lives and trainer careers emerge through the agents' own choices.

## From Bob's World to Living Kanto

Living Kanto grew out of my earlier work on Bob's World, a world simulator where a creator defines the environment and its laws, introduces living individuals, and observes what follows. Each creature makes decisions from its own private observations, while the simulation engine handles time, needs, and consequences.

Living Kanto brings that experiment into Pokémon's Kanto region. Its familiar geography, towns, services, battles, and trainer progression give the agents a concrete world to inhabit. A journey toward the Pokémon League is one possible life; working in a shop, helping others, exploring, or changing direction can be part of the same simulation.

This is a separate project that carries forward Bob's World's ideas about individual agency, private memories, validated actions, and persistent history, with systems built around Pokémon gameplay and a shared human society.

## What is in the simulation?

- **Kanto and the original 151 Pokémon:** FireRed-based maps and Generation III mechanics, with LeafGreen encounter availability included.
- **Individual people:** 100 persistent AI humans with roles, goals, needs, relationships, inventories, and owned Pokémon.
- **Everyday life:** work, rest, conversations, service queues, commitments, and concrete next steps.
- **Trainer systems:** exploration, encounters, catching, battles, training, healing, items, PC storage, trading, gyms, and League challenges.
- **Inspectable history:** person profiles show Pokémon, possessions, memories, plans, and searchable event history.
- **Persistent worlds:** atomic saves, compressed event history, recovery checkpoints, portable exports, and replay without additional inference.

## How it works

Each person receives a private observation containing what they can perceive, their own relevant memories, and the actions currently available to them. A local model proposes an intention. The simulation engine validates it, resolves movement or gameplay, and records the resulting changes.

Models choose actions; the engine owns the rules and outcomes. Accepted decisions have recorded provenance, and Creative interventions are recorded in the history. Shared world time supports ongoing activities alongside asynchronous decisions and background deliberation.

The application uses a **Python/FastAPI backend**, **SQLite persistence**, and a **JavaScript/Canvas browser interface**. Inference connects to a separately running local model server through an OpenAI-compatible API or Ollama.

## Ways to experience the world

- **Observer:** watch the simulation and inspect people's lives.
- **Survival:** enter the world as a player trainer.
- **Creative:** make explicit, recorded changes to the world.

## Getting started

You will need Python 3.10 or newer, Node.js/npm, and a local model server for autonomous decisions.

```sh
git clone https://github.com/Kipung/living-kanto.git
cd living-kanto
bash tools/setup_local.sh
bash tools/run_local.sh
```

Open [http://localhost:8877](http://localhost:8877). Create a world, choose a mode, and configure your local model connection in the interface. New worlds start paused. Without a configured model, you can inspect a world; autonomous decisions require local inference.

Setup installs Python and battle-simulator dependencies and fetches the pinned FireRed reference sources. Saves and machine-specific runtime settings are kept outside Git.

For an OpenAI-compatible local server, you can also supply the connection before launch:

```sh
export LIVING_KANTO_MODEL_ENDPOINT=http://127.0.0.1:18080/v1
export LIVING_KANTO_MODEL=your-local-model
bash tools/run_local.sh
```

The endpoint above is an example; use the address of your own local server. Ollama connections use `LIVING_KANTO_MODEL_PROTOCOL=ollama`.

## Current stage

Living Kanto is an experimental development build. The world, local-model decisions, gameplay systems, and persistence are implemented and have test evidence. Continued work focuses on reliable long-running behavior, meaningful social interactions, distinct goals, and autonomous trainer progression.

An autonomous badge journey or championship remains a milestone to demonstrate. Implemented mechanics and passing tests alone do not establish that agents can complete those journeys independently.

For more detail, see the [project guide](docs/PROJECT_GUIDE.md), [fidelity matrix](docs/FIDELITY_MATRIX.md), [entity systems](docs/ENTITY_SYSTEMS.md), and [storage architecture](docs/STORAGE_ARCHITECTURE.md).

To run backend checks:

```sh
.venv/bin/python -m pytest -q server/tests
```

## Acknowledgements

- Bob's World, the earlier simulation experiment behind this project.
- [pret/pokefirered](https://github.com/pret/pokefirered), the reference for FireRed/LeafGreen mechanics, maps, and source content.
- [Pokémon Showdown](https://github.com/smogon/pokemon-showdown), used for Generation III battle simulation.

This is an unofficial fan and research project, with no affiliation to the Pokémon rights holders. Pokémon names, characters, and original game assets belong to their respective owners.
