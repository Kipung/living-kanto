

# Living Kanto — Local Agent Project Guideline

## 1. Project goal

Build **Living Kanto**, a local, persistent Pokémon world that the user can watch, influence, and optionally enter as a trainer.

The world uses **FireRed/LeafGreen-era Kanto geography and game mechanics**, presented as a classic top-down 2D pixel RPG. Approximately **100 humans are persistent AI individuals**. They make decisions about their daily lives, relationships, journeys, training, and battles.

The central experiment is:

> Can individual AI people develop distinct lives and trainer journeys within a shared Pokémon world, with some earning championship through their actual decisions and results?

There is no predetermined protagonist or future winner. Humans may pursue other interests, abandon training, develop rivalries, help one another, or fail repeatedly.

The complete deliverable includes the full Kanto region, eight gyms, the Pokémon League, autonomous humans, an observer interface, Creative and Survival player modes, persistence, and replay.

**A small prototype is an intermediate milestone. It does not satisfy the final project goal.**

“Living Kanto” is the working project name; renaming it must not delay implementation.

---

## 2. Scope and game fidelity

### Reference rules

Use English **FireRed as the mechanical baseline**, with LeafGreen encounter availability merged into the shared world where needed. Restrict the initial species roster to the original 151.

The [pret FireRed/LeafGreen reference repository](https://github.com/pret/pokefirered) documents a decompilation of those games. Pin the reference revision used and maintain a source manifest for mechanics and content.

Create a **fidelity matrix** listing each required mechanic, its reference, its implementation, and its verification status. Unknown mechanics must be researched, not guessed.

Preserve:

- Pokémon stats, types, levels, natures, IVs, EVs, abilities, and friendship.
- Generation III move behavior, including its type-based physical/special categories.
- Accuracy, priority, damage, critical hits, status conditions, stat stages, weather, and relevant held-item effects.
- Four move slots, PP, move learning, TMs, HMs, evolution, and trade evolution.
- Catching, encounter tables, experience, money, shops, healing, storage, and a six-Pokémon party.
- Gym teams and first-challenge difficulty, badges, traversal abilities, and league eligibility.
- Relevant single and double battles.

Implement all effects required by the supported species, obtainable moves, items, and encounters. A familiar battle interface with incomplete effects does not count as faithful mechanics.

### Deliberate simulation adaptations

This is a shared autonomous world, so some changes from a single-player cartridge are necessary. Record them explicitly:

- Many trainers may receive starters and pursue badges.
- FireRed and LeafGreen species availability coexist.
- People have persistent relationships, occupations, memories, and daily lives.
- Battles require encounters or accepted challenges; trainers are not permanent scripted obstacles.
- Progression permissions belong to each trainer, rather than a single global player.
- Important services support multiple customers through queues.
- Champion succession is persistent and can change over time.
- Story-related access conditions become individual achievements or repeatable local scenarios, rather than requiring one global protagonist to complete the plot.

Canonical places and recognizable residents may exist, but dialogue, relationships, and future achievements are not predetermined.

### Boundaries

Include mainland Kanto and its associated dungeons, sea routes, essential interiors, and progression locations. This includes the towns and cities, Routes 1–25, gyms, forests, caves, buildings, islands within mainland Kanto, and the Indigo Plateau journey.

Exclude Sevii Islands, breeding, later-generation species, online multiplayer, and a scripted Team Rocket campaign from this release.

Locations associated with the original story remain usable. Where access depends on story events, provide documented repeatable progression scenarios. Those adaptations must not trap later trainers behind another individual’s completed quest.

Support Pokédex tracking as a separate achievement. **League Champion** means earning eight badges and completing the league challenge. Do not introduce a custom numerical “Pokémon master” requirement. Mew is not required for normal championship progression.

---

## 3. Individual humans and Pokémon

### Human population

Start with exactly **100 persistent AI humans**, excluding an optional user trainer:

| Role | Count |
|---|---:|
| Aspiring trainers | 30 |
| Gym leaders | 8 |
| Elite Four | 4 |
| Initial champion | 1 |
| Professor | 1 |
| Healing and storage service staff | 20 |
| Shop staff | 10 |
| Other workers | 10 |
| Other residents | 16 |

Roles describe initial circumstances, not social tiers or shared minds.

Each human must have:

- Stable identity, appearance, name, location, and biography.
- Personality, interests, ambitions, preferences, and tolerances for risk.
- Current goals, an active plan, money, inventory, and responsibilities.
- Owned Pokémon, party, storage, badges, and Pokédex records.
- Private episodic memories and summaries.
- Relationships and beliefs about other people.
- Rest, energy, and social needs.
- Decision history and model provenance.

Give individuals meaningfully different starting circumstances. The aspiring trainers begin without badges; do not preassign the eventual champion.

Initial leader, Elite Four, and champion status are declared setup facts. Never present those initial conditions as achievements generated by the simulation.

Daily life should support working, resting, shopping, socializing, traveling, training, collecting, and competing. Avoid adding a detailed survival economy, reproduction, or civilization system to this release.

### Pokémon individuality

Pokémon do **not** receive separate language-model minds.

Every encountered Pokémon becomes a persistent individual with its own identity, stats, moves, condition, origin, ownership history, and bond with its trainer.

Wild encounters may generate individuals from seeded encounter tables when the encounter occurs. Unencountered wildlife does not require a permanently instantiated global population.

The engine controls wild Pokémon behavior and battle choices. Owned Pokémon follow game mechanics, including relevant obedience rules.

Trades transfer the same individual atomically. Catching, releasing, evolution, storage, and defeat must never duplicate or silently replace an individual.

Legendary encounters are world-unique. Their ownership and availability are persistent shared facts. This is a documented adaptation; ordinary trainer advancement must remain possible after someone else catches one.

---

## 4. AI decisions and authoritative mechanics

### Separation of responsibilities

**AI chooses intentions. The simulation engine determines what actually happens.**

Human AI chooses:

- Goals and changes of direction.
- Destinations and meaningful travel plans.
- Work, rest, purchases, conversations, and trades.
- Catching attempts and training activities.
- Party composition and move-learning decisions.
- Challenges, gym attempts, and league attempts.
- Every battle turn: moves, switches, permitted items, and other legal choices.

The engine owns:

- Pathfinding and individual walking steps.
- Time, movement, collision, and terrain permissions.
- Encounter generation and randomness.
- Item costs, inventory, money, and ownership.
- All battle calculations and rewards.
- Evolution conditions, badges, eligibility, and champion succession.
- Persistence and all authoritative state changes.

Do not call a model for every animation frame or walking tile. Execute an accepted intention until it completes or a meaningful interruption requires a new decision.

A trainer cannot request “win battle,” “get badge,” or “become champion.” Those are goals, not executable outcomes.

### Private observations

A human receives only information they could reasonably know:

- Their own state, party, inventory, goals, and memories.
- Visible surroundings and reachable interactions.
- Public information they have learned.
- Battle information revealed through normal play.
- Legal actions and their known consequences.

Do not expose hidden opponent move selections, unrevealed stats, global memories, private relationships, or future random outcomes.

An observer may inspect the whole world, but that inspection must not leak information into AI observations.

### Structured actions

Use versioned JSON action contracts with:

- Actor identity and observation/state version.
- Action type and validated arguments.
- A short decision explanation.
- Optional goal or plan updates.

Treat explanations as recorded statements, not proof of the person’s actual knowledge or correctness.

All state changes pass through engine validation. Models receive no arbitrary database, shell, or world-editing capability.

### Failure behavior

On malformed or illegal output, provide one corrective retry.

If the second response fails, or the endpoint becomes unavailable:

- Pause at the unresolved decision boundary.
- Preserve the last committed world state.
- Show the actor and failure reason.
- Allow retry after correction or reconnection.
- Never silently substitute a scripted human action or cloud model.

Production human actions must be attributable to accepted AI decisions, except user-controlled actions and explicit Creative interventions.

Scripted minds are allowed only in clearly identified tests.

---

## 5. Time, shared-world scheduling, and battles

Use an event-driven simulation with integer simulated time and deterministic recorded ordering.

A committed world step must atomically record accepted decisions, resolved actions, events, and the resulting state.

### Scheduling

- Request decisions when an individual becomes ready or their plan is interrupted.
- Batch independent decisions under a bounded inference queue.
- Avoid polling idle humans continuously.
- Advance needs and activities according to elapsed simulated time.
- Keep distant areas active; camera position must not determine whether people exist or progress.
- Resolve simultaneous claims on items, services, and encounters deterministically.

A human cannot be in two places or battles at once. Service staff cannot simultaneously serve unlimited customers.

Training must consume actual time and produce actual encounters or activities. AI cannot invent offscreen victories or experience gains.

### Battle privacy and synchronization

Collect opposing decisions from the same battle-turn observation before revealing either choice.

The engine then resolves the turn under the reference rules. This prevents one AI from seeing another trainer’s already-selected move.

For battles involving the user, pause simulation advancement while required player input is pending. Browsing the observer interface alone does not pause time.

Battle animations can run faster than their visual default without changing results.

### Continuity

Provide explicit Run, Pause, and Resume controls.

Closing the browser does not stop a running backend. Restarting the backend loads the last committed state and starts paused. Do not simulate elapsed real-world downtime.

Offer 1×, 5×, and 20× playback speeds plus a fastest-available mode. These are requested speeds: display when inference limits actual progress.

---

## 6. Gyms, league progression, and champion succession

Each trainer progresses independently.

- Record badges only after legitimate completed victories.
- Apply eligibility and traversal requirements to that trainer.
- Gym leaders use their reference first-challenge teams.
- Keep official challenge teams separate from ordinary personal training so leaders’ daily activities do not accidentally make every gym impossible.
- A trainer with eight badges may attempt the Elite Four sequence and current champion.
- A failed attempt follows the implemented game recovery rules.
- A completed victory records the Hall of Fame entry and transfers the current champion title.

The initial incumbent provides the first champion challenge. Later champion challenges use a recorded eligible team from the current champion’s championship victory. The current champion still makes their own battle decisions.

If a required AI participant is unavailable because of another activity, schedule the challenge. If they repeatedly decline or fail to attend, expose that as a visible simulation problem; do not award an automatic victory.

Record championship tenure, defenses, defeats, and former champions.

There must be no guaranteed win, hidden experience boost, scripted badge grant, or favored future champion.

---

## 7. Observer, Survival, and Creative modes

### Observer

The default interface opens in Observer mode.

Required capabilities:

- Pan and zoom the world and open the region map.
- Follow a selected human.
- Inspect current activity, goals, relationships, memories, party, and achievements.
- Watch battles and review their logs.
- See factual world events and trainer progression.
- Inspect previous events and replay saved history.
- Search and filter humans by location, occupation, badges, or activity.
- Compare a person’s stated intention with the resulting event.

Separate factual history from subjective beliefs. An AI saying it defeated Brock is not a badge record.

The interface should make the world enjoyable to watch, with readable sprites, movement, interiors, battle scenes, and concise character panels.

### Survival player

Create a separate user-controlled trainer with the same mechanical restrictions as AI trainers:

- Normal movement and traversal requirements.
- Normal money, items, encounters, party limits, and catching.
- Normal battles, experience, badges, and league progression.
- Direct control of the trainer’s decisions.
- Persistent identity and save state.

The player uses the same action-validation and battle engine as AI humans.

### Creative player/director

Creative mode allows:

- Free movement and teleportation.
- Spawning Pokémon or items.
- Editing money, Pokémon condition, and other supported individual values.
- Relocating individuals.
- Editing goals or initializing scenarios.
- Granting progression deliberately.

Every intervention requires an explicit action and creates a permanent event containing its author, affected entities, and before/after values.

No repeated approval dialogue is needed for routine Creative actions. Destructive world reset requires a clear confirmation.

Switching modes never hides earlier interventions. Runs touched by Creative changes remain visibly marked as modified. Achievements retain their intervention provenance.

Observer mode provides no world-editing capability.

---

## 8. Architecture, persistence, and interfaces

### Project structure

Create a separate repository. Do not modify Bob’s World as part of this project.

Reuse suitable Bob’s World foundations after inspecting them:

- Model-provider interfaces.
- Private observations and validated decisions.
- Event scheduling and atomic persistence.
- Append-only history, snapshots, state hashes, and replay.
- Local backend and browser communication.

Do not carry over its hex-map UI, reproduction mechanics, or unrelated world-creation systems.

Use the existing foundation’s general stack:

- Python simulation backend with FastAPI.
- SQLite database per run.
- Browser frontend using JavaScript modules and Canvas 2D.
- HTTP commands and WebSocket state/event updates.
- JSON data packs for mechanics, maps, encounters, and initial population.

The renderer displays authoritative backend state. It never calculates canonical battle outcomes.

### Required contracts

Define and version these interfaces before parallel implementation:

| Contract | Purpose |
|---|---|
| World definition | Maps, rules, content versions, seed, population |
| Human observation | Private information available at a decision |
| Human action | Validated semantic intention |
| Battle observation/action | Visible turn state and legal choices |
| Canonical event | Factual state changes and their causes |
| State update | Snapshot or ordered frontend delta |
| Intervention | Explicit Creative mutation and provenance |
| Run metadata | Rules, models, content, schema, and modification status |

API commands must support run creation, pause/resume, observation, player input, interventions, save/export, and replay. Include run identity and expected state version on mutations.

Reconnect the viewer through a fresh snapshot and event sequence. Reject stale or duplicate commands without duplicating their effects.

### Persistence

Store:

- Authoritative humans and Pokémon.
- Maps, progression, service queues, and pending activities.
- Accepted decisions and model provenance.
- Canonical events and deterministic random state.
- Subjective memories separately from factual events.
- Snapshots, state hashes, and content/schema versions.

Replay uses committed events and state patches without additional inference.

Export a portable world/run bundle without endpoint addresses or credentials. Keep local inference settings outside portable content.

Do not overwrite existing saves during resets or migration. Unsupported save versions must produce a clear explanation.

---

## 9. Local models and lab integration

Separate two workloads:

1. **Development agents** building and reviewing the project.
2. **Runtime human minds** living in Kanto.

They must have separate queues and configurations. Do not assume the lab can serve both at full load simultaneously.

### Default deployment

- Run the world backend and viewer locally.
- Use Spark-master as the initial runtime-human endpoint.
- Use the paired Spark workers primarily for development coordination.
- Make all assignments configurable through local settings.

Use the validated lab handoff’s existing serving recipes. Its previous smoke tests establish connectivity, not sustained project or simulation capacity.

Do not hard-code network addresses or assume current free memory. Inspect resource availability before launching workloads.

Support OpenAI-compatible local endpoints. Retain Ollama support if it can be adapted cleanly from Bob’s World.

Never silently fall back to a cloud model.

### Mandatory capacity experiment

Before a 100-human release run, benchmark representative observations and battle decisions at concurrency 1, 2, 4, and 8, stopping increases when resource or reliability limits appear.

Record:

- Model, runtime, context settings, and endpoint allocation.
- Median and p95 decision latency.
- Accepted decisions per minute.
- Invalid outputs, corrective retries, and failures.
- Queue wait time and memory use.
- Actual simulated time advanced per wall-clock minute.

Select the lowest concurrency within 10% of the best reliable throughput. Exclude configurations with unresolved requests or resource failures.

Use compact observations and bounded memory retrieval. Reduce unnecessary decision frequency before reducing human individuality.

Do not promise a simulated-day throughput until measured. The UI must expose actual progress and queue pressure.

---

## 10. Local-agent execution workflow

Begin with three development roles:

| Role | Responsibility |
|---|---|
| Lead/integrator | Architecture, contracts, task ownership, integration, milestone evidence |
| Implementer | Assigned engine, content, or interface work |
| Reviewer/tester | Independent verification, mechanics checks, regressions, release evidence |

Assign additional workers only after a complete task passes implementation, review, integration, and tests.

Use the separate lab/OpenRig handoff for actual serving and agent-launch procedures.

### Coordination rules

- Create an isolated project workspace and uniquely named test rig.
- Inspect existing services and preserve unrelated rigs, sessions, and model caches.
- Give each task a defined owner, contract dependencies, deliverable, and acceptance checks.
- Use separate worktrees for simultaneous code changes.
- Integrate through the lead after independent review.
- Keep shared contracts under one owner.
- Report evidence and remaining defects, not merely “done.”
- Do not substitute a different project or stop after producing planning documents.

Maintain a durable task board and session handoff containing completed work, current failures, next tasks, and exact reproduction instructions.

Suggested implementation workstreams are simulation/mechanics, AI/persistence, region/content, and viewer/player controls. Parallelize them only after shared contracts stabilize.

---

## 11. Milestones and acceptance gates

### M0 — Foundations and reference inventory

Deliver:

- Separate repository and working local application.
- Versioned contracts and initial database schema.
- Reference/source manifest and fidelity matrix.
- Full Kanto location and progression inventory.
- Deterministic test mind and local-model connectivity check.
- Asset manifest with source and usage terms.

Use original pixel artwork where no suitable supplied or usable asset exists. Keep familiar Pokémon identities and Kanto layout. Record placeholder artwork as unfinished presentation work.

**Gate:** launch a run, persist an event, reconnect the viewer, and replay the event without inference.

### M1 — Complete trainer loop in a small area

Implement Pallet Town, Route 1, and Viridian City with a small test population.

Demonstrate:

- Distinct human observations and AI decisions.
- Travel, conversations, rest, shopping, and healing.
- Persistent wild encounters, catching, and ownership.
- Turn-by-turn AI battles, experience, move learning, and storage.
- Observer follow/inspect controls.
- Survival input and recorded Creative interventions.

**Gate:** multiple humans complete different activities using real local inference; a restart preserves their exact committed state.

### M2 — Verified mechanics and first gym journey

Expand through Viridian Forest, Pewter City, and the Brock challenge.

Complete all mechanical systems required by the final content roster. Start the exhaustive mechanics suite before adding the remaining region.

**Gate:** an autonomous trainer travels, trains, challenges Brock, and receives a badge only through a valid battle victory. No manual progression assistance.

### M3 — Full Kanto content and progression

Complete the mainland region, required interiors, encounters, all gyms, traversal systems, and repeatable progression scenarios.

**Gate:** a deterministic test trainer can legally complete the full journey. Validate every map connection, progression condition, encounter table, and required mechanic.

This proves reachability, not autonomous success.

### M4 — League and champion succession

Implement the Elite Four sequence, current champion challenges, Hall of Fame, and championship succession.

**Gate:** deterministic end-to-end tests prove a valid champion victory, failed attempts, title transfer, and a later defense or defeat.

### M5 — Full autonomous world and release

Run all 100 AI humans across the full region. Complete observer tools, both player modes, replay, exports, presentation, and operational documentation.

Conduct a real-model soak test of at least two wall-clock hours, followed by autonomous progression trials.

**Final gate:**

- All 100 humans remain individually persisted and accounted for.
- Real AI produces visibly distinct journeys and non-training lives.
- At least one aspiring trainer earns league championship autonomously from its declared zero-badge starting state.
- No scripted-human fallback, Creative assistance, or fabricated achievement appears in that evidence run.
- Mechanics, persistence, browser, and progression suites pass.
- Capacity measurements and failure-recovery evidence are included.

Do not force championship to occur during the two-hour soak test. Continue the progression trial as needed. If the system cannot achieve it, report the actual behavioral or mechanical blocker and keep the release gate open.

---

## 12. Verification and final handoff

### Required test coverage

**Mechanics:** representative reference-backed cases for damage, rounding, typing, accuracy, priority, critical hits, status, abilities, items, switching, experience, catching, evolution, and move learning. Exhaustively validate content references and supported effects.

**Individuality:** memories remain private, identities persist, relationships differ, and humans cannot use hidden world knowledge.

**Shared world:** simultaneous trades, purchases, catches, service requests, and challenges cannot duplicate resources or ownership.

**Progression:** every gym and league requirement is reachable; another trainer’s progress cannot lock out later trainers.

**Battle integrity:** simultaneous observations, hidden opposing choices, legitimate outcomes, and no reward before completion.

**Recovery:** invalid output, endpoint outage, interrupted save, process restart, and viewer reconnect preserve committed state without replacement actions.

**Replay:** saved history reproduces state hashes without model calls.

**Player modes:** Survival respects engine rules; Creative mutations are explicit and recorded; switching modes preserves provenance.

**Presentation:** inspect the actual rendered towns, routes, interiors, character panels, and battles. Verify keyboard movement, collision, camera following, readable text, and consistent pixel scaling.

### Required deliverables

The local agents must hand back:

- Runnable application and complete source repository.
- Full versioned Kanto content pack.
- Setup and launch instructions.
- Local-model configuration examples without credentials.
- Mechanics fidelity matrix and documented adaptations.
- Automated test results and visual verification evidence.
- Benchmark and soak-test reports.
- An unmodified autonomous championship evidence run.
- A demonstration save for observer and player exploration.
- Known limitations and a precise session handoff.

Classify results separately as **implemented**, **automatically verified**, **verified with real models**, or **still incomplete**.

### Starting instruction for the lead agent

> Build Living Kanto according to this guideline. Read the current lab/OpenRig handoff and inspect Bob’s World before reusing its foundations. Create a separate project and preserve existing work and services. Establish contracts, the mechanics reference inventory, and milestone acceptance checks first. Coordinate isolated local-model development agents with explicit ownership and independent review. Deliver each milestone as working software with evidence, then continue through the full Kanto release. Preserve private human minds, engine-owned mechanics, persistent identities, recorded interventions, and inference-free replay. Do not claim completion until the final acceptance gates pass.

