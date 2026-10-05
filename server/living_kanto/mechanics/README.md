# Mechanics service

Run `tools/setup_battles.sh` once (Node.js required). The package lock pins
Pokémon Showdown 0.11.11. Its Gen III simulator supplies turn priority, accuracy,
damage, criticals, physical/special type split, stages, abilities, held items,
move effects and battle statuses. This is an imported simulator implementation;
passing representative tests does not independently prove every effect matches
English FireRed. Showdown's simulated link-battle rules can differ from cartridge
NPC/wild rules. Exhaustive differential verification remains a release gate.

`reference.py` reads all 151 species, base stats, types, catch rates, XP yields,
growth curves, abilities, gender ratios, level-up learnsets, moves and evolutions
from the pinned `reference/pokefirered` source. `progression.py` reads original
first-challenge gym, Elite Four and three champion team variants, including
cartridge fixed-IV conversion and trainer personality/nature hashing. It does
not grow official challenge teams when personal teams train.

The Python service is callable independently from HTTP. `BattleSession.start`
accepts two `{actor_id, party}` records and a four-uint16 seed. `observation(actor)`
returns the actor's request and public opponent state. `submit` accepts a one-based
move or switch slot at a matching battle version; first decisions are validated
without changing the canonical battle, and both choices remain hidden until
resolved. `to_dict()` is an **engine-private** serialized state including pending
choices. Reconstruct using `BattleSession(record)` after restart. Export compresses full simulator state with zlib/base64; public transcript windows retain the latest 200 lines and the redundant session history the latest 20 turns. Complete simulator transcripts remain in compressed state and authoritative engine events preserve all committed decisions. Saved events
must replay committed state patches, never call the simulator again.

`consume_trainer_turn` is engine-only orchestration for a failed catching/item
turn: the opponent still acts and residual effects execute, without the user's
Pokémon attacking or losing move PP. The caller applies item effects/inventory
atomically with the returned battle result.

Known incomplete coverage:

- Doubles core accepts exactly two ordered move/switch/pass choices with simulator-validated foe/ally targets and preserves simultaneous privacy. Production encounter/challenge orchestration currently generates singles only.
- Production bag medicine and single-battle X items validate source use conditions and consume inventory atomically; failed catches/flee attempts consume actual opponent turns. Obedience and Safari orchestration remain incomplete. Held-item consumption and swaps synchronize into persistent individuals.
- All 58 TM/HM compatibility and ordinary 15 tutor tables are source-backed. Production TM/HM learning consumes TMs and reuses owned HMs, protects existing HM moves, and preserves PP slots. Tutor core is callable with per-trainer usage provenance; production tutor services and field-move traversal remain incomplete.
- Per-knockout participation, ordinary experience, EV caps and in-battle level/stat reconciliation are integrated. Exp Share/Lucky Egg distribution remains incomplete.
- Creation does not yet track shiny original trainer IDs, origin locations or
  full friendship changes. Sleep counters across separate battles need lifecycle
  synchronization; ongoing battles persist complete simulator status state.
- Gym badges require a completed matching official challenge metadata tag and
  winning actor. The engine must bind that metadata to the actual reference
  challenge team. League stage results likewise require official role metadata.
- Autonomous championship, real-model soak, capacity and exhaustive fidelity
  gates have not been performed by these mechanics unit tests.

Tests exercise source inventory, stat rounding/nature, catching ownership,
evolution identity, progression losses/title succession, private simultaneous
choices, restart equivalence, PP, legitimate fainting and item-turn no-op.


Inventory and reciprocal trades
------------------------------
`item_rules.py` reads 308 source item records, 63 defined item-effect tables,
machine aliases, all 151 machine/tutor learnsets and evolution conditions. Pure
transactions return copied trainer/individuals plus factual effect data, so an
exception never consumes an item or changes ownership. Production decisions
support overworld medicine, evolution stones, Rare Candy, vitamins, PP restores,
PP Up/Max, TM/HM learning, and single-battle medicine/X-item turns. Full Heal
cures battle confusion through simulator synchronization. Red/Yellow flute and
Dire Hit/Guard Spec use corresponding Gen III volatile/side conditions.

Trades require a proposer offer, recipient selection of the counterpart, and
proposer confirmation of that exact individual. Pokemon hashes reject changed
terms. Both ownership containers and histories change in one canonical event;
trade evolution preserves PID/identity and source trade friendship resets to 70.
Offer history remains in replay; the live registry retains one active proposal
per proposer and the latest 100 closed offers. Source Everstone prevention is
respected. The original-151 restriction excludes later-generation evolution
targets even when present in the reference.

Remaining item/service coverage: Sacred Ash party-wide restoration, Escape Rope route
permissions, held-item equip/unequip inventory transfers, Move Deleter service,
repeatable gift/static legendary claims, special starter tutors, and mail. Unknown
items request another authoritative service instead of invented item behavior.
No autonomous or capacity release gate is implied by these integration tests.

Source encounters and environmental services
-------------------------------------------
`encounters.py` reads the pinned JSON slot weights for land, Surf and each rod;
rod bite is the source 50% parity test. Choosing `train` on a qualifying source
terrain tile intentionally requests an encounter rather than reproducing every
cartridge walking RNG check. Fishing does not reproduce the reflex minigame.
`gameplay.py` requires Surf in the owned party and Soul Badge on water tiles.

`safari.py` implements copied admission transactions (500,30 balls,600 steps),
source bait/rock factor changes and counters, pre-action wild flee decisions,
ball shake arithmetic, individual capture and party/420-slot storage limits.
Safari decisions use a separate engine encounter state and do not create a wild
human mind. World orchestration must decrement actual walking steps, enforce
paid navigation and expose only `safari_observation`; pure tests alone do not
prove those hooks. Ball exhaustion returns to the source entrance after its
scripted two steps. Paid encounter/run/replay has an integration test.

The Pokémon Tower ghost uses source female Serious Marowak30 with31IVs and a
consistent PID. Silph Scope is required, balls unavailable, and only actual
simulator victory records the progression flag. Mainline tutor stations derive
15 NPC coordinates and moves from pinned scripts, require compatible species
and preserve individuals. Copycat requires/consumes Poké Doll. Source global
one-use tutor flags are explicitly scoped per trainer for this persistent world;
these environmental services do not introduce extra human minds. Special
starter ultimate-move tutor and Move Deleter remain outside this layer.

Accepted personal duels and official money
-----------------------------------------
Personal trainer challenges require explicit proposer consent and recipient
acceptance near each other. Each supplies the current owned personal party;
doubles require two healthy individuals each. The model receives one
`battle_turn` intention and two lists of structured active-slot choices. The
simulator validates the chosen pair before persisting either hidden choice.
There is no network transport: these are offline world humans. Their economy
is an explicit source-link-like adaptation (no XP, prize money or blackout),
while persistent individuals retain actual damage/PP as world consequences.
Neither official title nor badge changes in such a personal duel.

Official victory payouts read pinned trainer classes and the money table:
four times the original last party member's level and class value, with source
doubles/participating Amulet Coin multipliers and999999wallet cap. Payout occurs
only after canonical completed victory, not before an accepted choice. Blackout monetary loss reads FireRed's badge-count/maximum-party-level table,
capped at current money. Respawn/heal orchestration remains the world's responsibility.

Source static Zapdos50 is available at its Power Plant object, with one world
individual reserved atomically for an active battle. Capture/KO closes the claim;
flee/loss releases it and a later encounter heals that same persistent individual
without changing its PID. Source Articuno50 requires both source boulders to have reached B4F and
revealed their source flags, stopping the current in the private traversal map. Mewtwo70 explicitly substitutes that individual
trainer's recorded Hall of Fame entry for the excluded Sevii Ruby/Sapphire
completion gate, as required by mainland scope. This adaptation is recorded
in the canonical battle metadata. Source FireRed Moltres is on excluded Mt Ember;
there is no invented Victory Road Moltres or mainland Mew encounter.

Guide-required LeafGreen availability coexistence is an explicit adaptation:
each FireRed slot retains its exact source weight, then picks equally among
distinct FireRed/LeafGreen species/level variants of that same source slot.
Identical variants are deduplicated; walking rate/cooldown remain FireRed.
This makes LG-only species reachable without inventing encounters on new maps.

Source Route12/Route16 Poké Flute interactions start a real Snorlax30 battle.
The reusable owned flute wakes it, and its source blocker clears per trainer
at battle start (source hides the object before battle, including flee/loss).
Normal captures accept each supported owned source ball, consume only the
selected item and retain captured ball/origin map on the same individual.

Source walking helper now persists individual cooldown/previous-terrain/rate
buff and ISO_RANDOMIZE2 rate RNG. It uses FireRed slot weights/rates as baseline, rate*16/1600,
5% cooldown bypass,60% changed-terrain gate and source Stench/Illuminate,
Cleanse Tag, bicycle and black/white flute modifiers. It selects the actual
slot/level once so movement can stop on the trigger tile before battle. The
world's accepted path adapter must call it per walked tile; these pure tests
alone do not prove that wiring. Main RNG uses canonical seeded world input
rather than reproducing every unrelated cartridge RNG call. Roaming legendary
encounters remain excluded because source Sevii postgame setup is outside scope.

Source Repel/Super Repel/Max Repel consume one owned item for100/200/250
walking steps, reject replacement while active, and filter below first healthy
party member level. Reusable owned Black/White Flutes switch source encounter
modifiers. Source shop tables are read from18 pinned map scripts;12 current
mainland shop maps are available, including Indigo's shared center/shop and
Celadon TM/stone/vitamin floors. The30 existing service/clerical humans staff
all12 healing centers and12 shops without changing their20/10 role counts.
Purchases remain human-served canonical queue transactions.
