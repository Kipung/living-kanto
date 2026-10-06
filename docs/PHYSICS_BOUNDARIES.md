# FireRed movement boundaries

Living Kanto uses the pinned FireRed source revision `037335f4c725d7c9aecdac87066f2002b4bd7e14`. Movement permission belongs to the simulation, including when the LLM requests a journey. The viewer displays accepted routes; it cannot grant traversal permission.

| Boundary | Allowed | Blocked / required condition | Source |
|---|---|---|---|
| Ground | Cardinal movement onto clear source tiles | Collision-marked walls, cliffs, out-of-bounds cells | `event_object_movement.c:GetCollisionAtCoords` |
| Directional barriers | Source-permitted entry and exit direction | Both current tile's exit and destination tile's opposite edge are checked | `IsMetatileDirectionallyImpassable`, `metatile_behavior.c` |
| Ledges | Two-tile jump in the ledge's exact direction, onto a clear landing | Wrong direction or blocked landing; no arbitrary two-tile walking | `field_player_avatar.c`, source ledge behaviors `0x38..0x3B` |
| Water | Explicit Surf state and field permission, including source forced Surf | Walking onto Surfable water; Surf does not disable elevation checks | `field_player_avatar.c:CheckForObjectEventCollision`, `metatile_behavior.c` |
| Shoreline | Surf dismount onto bank elevation 3 | Occupied bank, wall, other incompatible elevation | `CheckForObjectEventCollision` |
| Elevation / bridges | Equal elevations; source wildcard 0; destination 15 retains the actor's plane | Jumping between incompatible planes; carried elevation is saved for later steps | `IsElevationMismatchAt`, `ObjectEventUpdateElevation` |
| People | Different incompatible bridge planes can coexist | Compatible-plane humans and represented visible NPCs occupy solid tiles | `DoesObjectCollideWithObjectAt`, `AreElevationsCompatible` |
| Shared clock | Different available destinations can move on the same boundary | One destination cannot be claimed by two actors; starting positions and accepted destinations are reserved | Adaptation of source current/previous object coordinates |
| Animated doors | Enter from the south, moving north; leave the landing southward | Sideways access through a closed wall | `field_control_avatar.c:TryDoorWarp` |
| Warps / edges | Exact source warp index or connection-offset landing | Occupied arrival, unavailable destination, wrong exit; no nearest-open-tile substitution | `overworld.c:WarpIntoMap` |
| Warp landing markers | Land at the exact source position and step out | A landing marker does not turn a wall into ordinary traversable floor | Source warp coordinates plus tile collision data |
| Trees / boulders / Snorlax | Per-trainer recorded Cut, Strength push, or clearance | Present obstacle, obstructed boulder landing, missing field permission | Source object events and field-move scripts |
| Puzzle geometry | Recorded card doors, pressure switches, Mansion switch and Seafoam layout changes | Closed private barriers; another person's progress does not open yours | Imported source scripts; deliberate per-human progression adaptation |
| Currents / spinners | Follow source directional momentum to its valid stopping point | Choosing an intervening destination, obstructed forced movement, infinite cycles | Source behaviors `0x50..0x58` |

An occupied step waits on the shared clock. After eight blocked boundaries its intention ends so the model can choose again. It does not teleport, overlap, or receive a fabricated model decision. Existing overlapping saves may step apart; implementation does not silently rewrite their history or relocate them.

The renderer interpolates ordinary cardinal steps and recognizes source ledges for the original high-jump offset sequence. Diagonal updates, large position changes, and unidentified two-tile changes snap to their recorded destination instead of inventing a shortcut through scenery. Map transfers do not interpolate across maps.

## Native field effects

`tools/import_field_effects.py` imports eight original sprite sheets, their bound source palettes, transparency and 60Hz animation commands. The live map uses the original Cut tree removal frames, Surf splash and directional Surf platform, Strength boulder, and Fly bird. Flash uses the original circular visibility-window radius progression. Effects follow recorded actions and private puzzle state.

This is not a complete port of the GBA renderer: Fly's full player/Pokémon choreography, camera effects and every ground-effect callback remain separate work. All sprites use original pixels; Surf/Fly use the original player palette for shared trainers. Map PNGs currently flatten original background layers, so sprite occlusion behind roofs/foreground tiles still needs a layer-aware renderer. Logical tile collision and visual occlusion are different checks.

## Verification and scope

`tools/audit_collision_boundaries.py` compiles the original directional-block, elevation-mismatch and elevation-compatibility function bodies with host-side map access stubs. It checks ordinary cardinal edges on all 256 imported maps. The report records 249,866 checked edges, zero predicate disagreements and 218 collision-marked warp coordinates. Door, ledge and water exceptions are classified separately and exercised by focused tests. This is a terrain predicate audit, not an emulator comparison or proof of every source callback.

Regression coverage includes exact warp landings, door direction, safe ledge landings, Surf elevation and occupied-bank checks, retained bridge elevations, solid objects, conflicting simultaneous destinations, encounter outcomes, canonical replay, source forced motion, field scripts and original sprite pixels/palettes.

The complete original NPC cast is still a separate integration. Visible item balls, fossils and represented legendary encounters also block movement until their recorded collection/clearance. Only NPCs actually represented with visible sprites are treated as dynamic objects; invisible source placements must not create unexplained blockers. Original NPC roaming ranges apply to that cast, rather than restricting autonomous travelling humans. Full source background/OAM priority, NPC visibility-script parity and unsupported field callbacks need their own integration tests before claiming full cartridge physics. The imported mainland maps contain no elevation-15 ordinary walking edges in this audit; synthetic tests cover retained-plane behavior.

Audit evidence: `evidence/physics/source-collision-audit.json`.

Verified runs: 58 movement/field/forced-motion/viewer regression tests; after the final collision refinements, 34 shared-clock/field-travel/boundary tests, 23 shared-clock/field-script tests and 14 route/field tests passed. The original-pixel verification passed, along with 36 JavaScript display/effect/geometry tests. Some suites overlap. The game service was reloaded while all worlds were paused.

The saved-world position audit found zero blocked positions and 14 pre-existing same-tile groups in the 100-person fresh world. These existing overlaps were preserved; no world reset or automatic relocation was performed.
