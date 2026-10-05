# Separate live observer

Open `http://localhost:8877/client/live/index.html?world=final-world-soak` while the existing local service is running. The original application remains at `/`; its index, runtime and saved worlds are not changed by this component.

The page consumes coherent state/event WebSocket updates. It animates only routes recorded by accepted engine events, retaining their map boundaries and original character frames. It shows factual work/rest/service/battle indicators, an activity feed with actual recorded chat text, individual party HP, and single/double battle cards with actual move and damage logs. Select a person or feed item to follow them; “Follow new activity” switches to the actor of each new accepted event. Pan, zoom and location selection are observer camera controls.

“Replay last walk” is a labelled visual preview of a saved route, including cross-map segments. It never replays world actions, calls a model, or changes canonical state. A new live event cancels this preview. Current party/activity facts remain current during the visual preview. Creative history is displayed where present.

The page only issues GET requests and opens a read-only event socket. It does not resume or pause AI. Use “World controls” for those actions. Idle people remain still; conversation bubbles expire; no patrols, utterances, battles or progress are fabricated. Inference and server history validation can cause gaps between accepted events. Known-world loading is independent of the saved-world catalogue, with sequential reconnect/fallback handling.

Verify helpers with `node --test client/live/model.test.mjs`. These focused tests cover recorded map routes, rejection of invented teleport paths, simulated-time activity labels, split-log damage deduplication, real chat recipients and individual activity batches. Browser evidence is under `evidence/live-view/`. This component was created separately in the side conversation; integrating its features into the main viewer remains a separate change.

## Simultaneous views and smoothing

Everyone together is now the default. It renders every human in a stable grid and Fits all people to the available desktop viewport; smaller screens may require scrolling. Portraits use original walking frames only while their accepted recorded route is playing. Every card displays that person's real activity and location. All occupied areas draws a simultaneous map wall containing all humans, grouped by their current displayed map; no group is dropped. Map thumbnails fit the occupied positions and indicate every member's name. Personal puzzle terrain in each thumbnail uses its first member's current facts. All active battles are available outside the compact fit-all display. Current area remains available with optional following.

Smooth walking plays each recorded tile at360ms and removes the former six-second duration cap. The rendered position can trail the latest canonical saved position. It does not make people take new actions, turn idle time into walking, or eliminate inference gaps. A genuinely continuous engine view requires the main simulation to execute validated ongoing intents on regular ticks and publish progress while local models decide independently. That scheduler/engine change is deliberately not made in this separate component during the main build's ongoing tests.

Additional tests check100-human overview coverage without duplicates and preservation of long route playback duration.
