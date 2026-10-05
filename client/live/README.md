# Separate live observer

Open `http://localhost:8877/client/live/index.html?world=final-world-soak` while the existing local service is running. The original application remains at `/`; its index, runtime and saved worlds are not changed by this component.

The page consumes coherent state/event WebSocket updates. It animates only routes recorded by accepted engine events, retaining their map boundaries and original character frames. It shows factual work/rest/service/battle indicators, an activity feed with actual recorded chat text, individual party HP, and single/double battle cards with actual move and damage logs. Select a person or feed item to follow them; “Follow new activity” switches to the actor of each new accepted event. Pan, zoom and location selection are observer camera controls.

“Replay last walk” is a labelled visual preview of a saved route, including cross-map segments. It never replays world actions, calls a model, or changes canonical state. A new live event cancels this preview. Current party/activity facts remain current during the visual preview. Creative history is displayed where present.

The page only issues GET requests and opens a read-only event socket. It does not resume or pause AI. Use “World controls” for those actions. Idle people remain still; conversation bubbles expire; no patrols, utterances, battles or progress are fabricated. Inference and server history validation can cause gaps between accepted events. Known-world loading is independent of the saved-world catalogue, with sequential reconnect/fallback handling.

Verify helpers with `node --test client/live/model.test.mjs`. These focused tests cover recorded map routes, rejection of invented teleport paths, simulated-time activity labels, split-log damage deduplication, real chat recipients and individual activity batches. Browser evidence is under `evidence/live-view/`. This component was created separately in the side conversation; integrating its features into the main viewer remains a separate change.

## Simultaneous views and smoothing

Everyone together is now the default. It renders every human in a stable grid and Fits all people to the available desktop viewport; smaller screens may require scrolling. Portraits use original walking frames only while their accepted recorded route is playing. Every card displays that person's real activity and location. All occupied areas draws a simultaneous map wall containing all humans, grouped by their current displayed map; no group is dropped. Map thumbnails fit the occupied positions and indicate every member's name. Personal puzzle terrain in each thumbnail uses its first member's current facts. All active battles are available outside the compact fit-all display. Current area remains available with optional following.

Legacy recorded journeys can play each accepted tile at360ms; this is visual replay speed, not the engine clock. The shared-clock viewer instead consumes every actor's explicit tile route in `world.shared_tick`, starts actors from the same received tick together, and interpolates only between recorded coordinates over the tick's elapsed time adjusted for requested speed. Transfers never invent a path between maps. The displayed position can trail the latest canonical facts. No future path is animated before the engine records it.

The live page now reads persisted movement intents, simulated activity countdowns, actual parallel thinking IDs, shared clock time, requested versus measured clock speed, and processing-limit status. The engine/runtime implementation is documented in [SHARED_CLOCK.md](../../docs/SHARED_CLOCK.md); this page remains a read-only observer. Ordinary conversations and actions remain visible separately from repetitive movement-only clock ticks. Everyone together and occupied-map views retain all100 humans.

Additional tests check100-human overview coverage without duplicates and preservation of long route playback duration.
