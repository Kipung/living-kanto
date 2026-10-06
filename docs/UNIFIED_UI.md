# Unified world interface

Open `/` or the compatible `/client/live/index.html` URL. Both now show the live everyone grid with world selection, requested speed, Run/Pause, Watch/Play/Creative modes and everyone/occupied-areas/current-area views. Existing elapsed-time, accepted-update, AI-decision and measured-speed displays are preserved.

World tools mounts the existing detailed controls on demand in a drawer for person inspection, your trainer, world/model configuration, factual history and save import/export. Same-origin messages keep selected worlds and people synchronized. Changing modes uses the latest state version and creates your player when required. Opening the drawer does not pause the world.

The NPC drawer lists the actual saved population, with search and role filters. The original FireRed NPC catalog and workplace routines from the side branch are not yet integrated; the drawer says so explicitly. This UI integration does not install or replace those backend changes.

The location menu is a compact list of the256 original map metadata filenames under `content/maps`, rather than downloading the full region catalog. Regenerate `client/unified/locations.json` if supported map filenames change.

Validation:17 recorded-movement/shared-clock/progress tests and11 existing API tests passed. Browser checks on the running `fresh-kanto-20261005-152534` world verified100 people, live shared time and eight concurrent minds, preserved progress metrics, NPC list/gym filter and selected-person inspection. Location list loads all256 entries. No live-world modes, speed, model configuration or saved facts were changed during inspection, and no service restart was required.

## Activity indicators

Live cards now have prominent activity icons and a compact legend. Current saved activity identifies movement, battles, thinking, work, rest and service queues. Recorded `talk_to` receipts briefly show Talking for the speaker and Listening for the addressed person; recorded `catch` and Safari-ball actions briefly show a catch-attempt icon. Receipt effects expire after6.5display seconds and are not replayed as fresh activity when loading old history. They do not imply a successful capture or an unrecorded reply. Icons also appear in the current-area labels and occupied-area view.21 display/helper tests pass, including speaker/listener attribution, batch actor handling, Safari classification, expiry and battle interruption.

## On-map field effects

Readable screen-sized badges are drawn above map actors in Current area and occupied-area thumbnails. Field effects now use original FireRed sprite pixels, palettes and animation frames: Cut tree removal, Surf splash/platform, Strength boulder and Fly bird. Flash uses the original visibility-window progression. Initial history loading never replays old effects as fresh actions. The explicitly labelled `client/live/test-fixtures/field-effects.html` preview performs no world command or model call. See [PHYSICS_BOUNDARIES.md](PHYSICS_BOUNDARIES.md) for collision rules, source audit evidence, tests and remaining renderer limitations.
