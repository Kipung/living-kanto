# Task Board — Living Kanto (main-lead, 2026-10-04 ~20:20Z, operator fact-repair)

Authoritative task grid. Facts: `…/living-kanto-20261004-0300/VERIFIED_FACTS_CURRENT.json` + direct source inspection; supersedes earlier boards. All seat tools execute on the Jetson; model machines are inference-only; all worktrees locally readable here.

## Canonical state (verified)

- Repo `/home/jetson/projects/living-kanto` `main` HEAD `f77526d`.
- Accepted product `75cba50` — cumulative 7-file backend from approved candidate `8f63907` onto approved contracts `0911c8a` (RunStore + FastAPI app + tests; purely additive; no AGENTS). Combined suite 82 PASS (reviewer + operator independently: `…/reports/operator-integrated-backend-1940.json`).
- Contracts `0911c8a`: `StateUpdate.prior_state_hash` (world content-hash staleness gate) + `StateUpdate.apply_to`; strict-int clock seconds; present-non-dict path intermediates rejected. `previous_head` = event-chain hash, not world hash. **No `PatchOp`/`ActionProposal` exists.** Actual classes: `Contract`/`ContractError`; `WorldState`/`StateUpdate`; `CanonicalEvent`; `LegalAction`/`HumanObservation`/`HumanAction`; `LegalBattleAction`/`BattleObservation`/`BattleAction`; `Intervention`/`ModelUsageRecord`/`RunMetadata`; `ContentSource`/`MapRef`/`WorldDefinition`.
- venv `…/venv/bin/python3`: fastapi 0.142.2, pydantic 2.13.5, httpx 0.28.1, uvicorn 0.54.0.
- Reference: pret/pokefirered pinned `037335f4c725d7c9aecdac87066f2002b4bd7e14` at `/home/jetson/projects/living-kanto/reference/pokefirered`. `d2d6646d5e93bd5016248bf41e760434e092e554` is an assets **candidate** commit, not the pin.
- Inventory 005 = report-only research (reviewer) at `…/worktrees/review/control/reports/m0-reference-inventory-provenance-005`; 425 known; **not fully accepted; mechanics not implemented**. `evidence/m0-asset-provenance-005`, LICENSES/14-asset acceptance never verified — do not cite.

## Completed — independently verified

- Contracts: `0911c8a`; `…/review/control/reports/m0-contract-review-003.md` (36 tests + 16 native probes).
- Backend: `8f63907`; `…/review/control/reports/m0-store-review-001.md` (66 tests); integrated 82 PASS.


## Active

| ID | Seat (inference host) | Paths | Notes |
|---|---|---|---|
| m0-integrate-browser-001 | lead (spark-worker1, 32k) | docs, canonical integration | Integrate reviewed service-002 + frontend-001 commits; browser preview pending; own slice `server/living_kanto/simulation/**` + `test_simulation_m0.py` |
| m0-service-002 | builder (pcright, 32k) | `server/living_kanto/api/**`, `server/tests/**`, tools/launch | Phase 1 `6f8803c` (static content/client) lead-verified: 13 new + 79 total PASS, live smoke own instance :8878 (bytes-identical PNG, traversal 404); `evidence/m0-service-002-001/`. Pending independent review; phase 2 (WS/resync/replay) in progress |
| m0-viewer-001 | frontend (macright, 16k) | `client/**` only | Real work: `/home/jetson/projects/living-kanto-worktrees/frontend/client` (index.html, js/maps.js, js/run.js, js/main.js), uncommitted/in-progress. Claimed `6832624` does not exist |
| assets | assets (spark-master, 16k) | asset extraction | Bounded extraction from pin |
| reviewer standing | reviewer (spark-master, 16k) | own reports | Waiting on service-002 / viewer-001 candidates |

## Remaining gates (none complete)

Real local-model legal action + atomic receipt/event/state + reconnect + inference-free replay (M0); separate runtime adapter; faithful Gen III, mainland Kanto, 151 species, 100 persistent private-humans, hidden battle choices, atomic Pokémon ownership, Survival/Creative, M1–M5, benchmark 1/2/4/8, 2h GAME soak, zero-badge champion. `POST /test_append` is synthetic harness — never game/AI evidence. No cloud, fallback humans, or fabrication.

## Lead update 10-04 23:50Z (appended)

| Task | Owner | Status | Evidence/notes |
|---|---|---|---|
| m0-integrate-browser-001 | lead | in_progress | Static `6f8803c` -> main `88cc7a9`, 103/103, content/traversal checks pass. Client `c60548b` integration pending acceptance-hold resolution. | evidence/m0-integrate-browser-001/ |
| m0-engine-private-repair-001 | lead (engine author) | completed | Slash->dot path repair + memories surfacing + 3 positive tests; 11/11, 106/106. Candidate `f84cd4b`, report `cf951b0`. | evidence/m0-engine-private-repair-001/ |
| m0-engine-private-review-002 | reviewer | pending | DISTINCT review of `f84cd4b`; prior assets APPROVE `ba2f7e0` invalid for this finding. | - |
| m0-root-containment-repair-004 | backend | completed | Root-only fix `0f6e8f0` (work/engine); WS preserved separately as unverified WIP `f7fec28`. Awaits `m0-service-review-002` (dep now satisfied). | /tmp/m0-root-containment-repair-004-report.md |
| WS/reconnect ownership | lead | queued | Transferred to lead post-004 per operator. Starts only after `0f6e8f0` review verdict + integration (no concurrent app.py writer). Material: reports/backend-handover-2345. | - |
