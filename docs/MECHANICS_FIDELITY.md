# Mechanics coverage and fidelity boundaries

Pinned `reference/pokefirered` provides species, moves, learnsets, growth, evolution, encounter slots, item effects, machines, tutors, trainers, shops, field scripts and gift positions. Battle calculations use the locally installed pinned Pokémon Showdown 0.11.11 Gen3 simulator, with source cartridge hooks described below. Tests are explicit scripted or Creative fixtures; they do not demonstrate autonomous local-model trainers completing a journey.

## Cartridge hooks

Single trainer/wild/gym/league battles apply source player-side Boulder Attack, Soul Defense, Volcano Special Attack/Defense and Thunder Speed boosts. The hooks preserve individual base stats and apply the boost when calculating battle stats. Source traded-mon obedience uses original trainer identity, badge thresholds, alternate usable moves, sleeping/loafing/self-hit branches, illegal non-fateful Mew checks, and canonical seeded choices. Original trainer identity persists through trade and release, including trade back. Self-hit uses source Pound40 damage and relevant original 151 ability/held-item modifiers. Actual badge damage, obedience, original-trainer trade back, and state restart are regression tested. Exotic cross-effect damage-rounding interactions have not been exhaustively compared with ROM execution.

Source friendship covers walking, field poison fainting, battle fainting, level-ups, TM/HM learning, significant gym/league battle entry and item effects. Return/Frustration receive the persistent individual's friendship rather than a competitive simulator default. Walking poison checks every five non-forced steps, clears poison after fainting, and invokes the same canonical source whiteout recovery only when that poison check causes the party to become unusable.

The canonical simulator state and accepted intentions are saved with events. Restart restores that state; it does not rerun historical choices to replace recorded results. The engine and simulator's seeded random streams are **not a bit-identical reconstruction of the ROM's entire global RNG stream**.

## Explicit world adaptations

FireRed encounter slot probabilities and rates remain the baseline. Distinct LeafGreen species/level variants coexist within the corresponding source slot, chosen equally, so guide-required LeafGreen availability is reachable. Identical version rows are deduplicated.

Source one-time gift balls, tutor flags, ordinary Electrode/Snorlax encounters and environmental story progression are scoped per trainer in this shared world. Gift Eevee is level 25; the source Dojo master is Koichi with Hitmonlee37/Hitmonchan37, and a recorded victory permits exactly one Hitmonlee25 or Hitmonchan25. The office is an initial circumstance belonging to one of the 100 existing humans; the office supplies no earned achievements.

Articuno requires both actual Seafoam boulders/current-stop flags. Zapdos, Articuno and Mewtwo each reserve one persistent world individual. Release removes ownership and records the same identity as released; the source once-caught encounter stays unavailable. Mewtwo's individual Hall of Fame gate explicitly substitutes for the excluded Sevii Ruby/Sapphire quest. FireRed Moltres lives on excluded Mt Ember; no invented Victory Road placement exists. No source Mew wild encounter is provided.

## Doubles and items

Production personal doubles require an offer and explicit acceptance by two existing humans. Both participants submit two structured active-slot choices; exact simulator validation rejects invalid choices before storing a pending intention. Their choices remain private until resolution. These are offline personal battles with source-link-like exceptions: no badges, XP, prize money, whiteout loss or bag items. Persistent HP and PP consequences are a shared-world adaptation.

The callable nonlink battle core additionally supports a bag item with an explicit acting slot and a validated partner move/switch choice. Only the acting Pokémon loses its action; the partner still acts. Production currently does not generate source field double trainer encounters, so this item API is tested core coverage rather than an available field double journey feature.

Supported bag effects are parsed from the pinned source and limited to implemented effect families. Unsupported effects fail explicitly. Capturing, evolution, machine learning, reciprocal accepted trading, physical facing-PC storage, release, source shops and paid Safari use atomic canonical ownership/inventory changes. All151 source machine/tutor compatibility tables are extracted; their existence alone does not establish a complete autonomous acquisition route.

## Experience and held-item lifecycle

Source `Cmd_getexp` records participation separately for each opposing individual. Healthy Exp. Share holders receive their half-pool, including a participant holder receiving both portions; level 100 members count in pool denominators but receive neither experience nor EVs. Lucky Egg, trainer-battle and traded bonuses apply in source integer order. Original trainer identity determines the trade bonus, so a trade back does not retain it. Canonical battle receipts retain per-foe recipients and awarded amounts.

Owned held items can be given, taken and swapped outside battle, returning the old item atomically to inventory. Party members are available directly; boxed individuals require a physical PC. Source key-item and importance flags prevent holding HMs and key items. Ordinary medicines and TMs can be held without inventing a battle effect. Mail writing remains explicitly unsupported. The adapter preserves exact source item identifiers even when the competitive simulator has no effect entry, including Exp. Share.

Ordinary wild individuals receive source common/rare held items before capture, including Safari encounters. The pinned FireRed function uses45% none,50% common,5% rare, or100% when both source entries match, and has no Compound Eyes modifier. Capturing transfers that same individual's held item. Legend initialization retains its source exception. This makes rare source Chansey Lucky Eggs obtainable without a Creative grant.

Escape Rope and owned Dig use the recorded source outdoor-to-indoor entry warp only on maps whose source header permits escaping. Interior floor transfers do not replace that checkpoint, and the source Viridian Forest exception applies. Escape Rope consumes one inventory item; field Dig consumes no PP. Owned Teleport requires an outdoor source map and an actual completed healing checkpoint and uses that station's pinned outdoor heal-location coordinates. No destination is invented when the checkpoint is absent. These effects reset traversal/Flash/Strength state and retain canonical receipts and replay. Mail composition remains outside implemented coverage.

Level evolution opportunities are created only by an actual experience level-up or Rare Candy level-up; catching or initializing an individual already above its threshold does not create one. The explicit trainer decision is persisted as a deferred opportunity for that same species/level, and evolution consumes it. Item friendship applies the source current-region bonus using the trainer's actual map and the individual's origin region, together with source Soothe Bell/Luxury Ball order; Rare Candy applies that bond change once.

## Shared service cancellation repair

Every queued human may explicitly cancel their own request, using the existing canonical cancellation/refund receipt. A station's sole assigned staff member cannot open a new request at that same station. This prevents self-service deadlock without inventing checkout decisions or automatically serving a person. It is a declared shared-world staffing adaptation. Legacy requests recover through an accepted model or player cancellation; refunds occur once and history is preserved. Automatic regressions and an actual Qwen38 legacy recovery verify this repair separately from the earlier two-hour soak.
