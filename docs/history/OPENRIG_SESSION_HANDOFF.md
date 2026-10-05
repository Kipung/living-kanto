# Session Handoff — Living Kanto (main-lead, 2026-10-04 ~23:50Z)

Supersedes the 21:00Z handoff below. Canonical `main` HEAD `b90d16f`. Accepted product remains `75cba50`; contracts `0911c8a` retained.

## State as of 23:50Z

- Integrated into main: static serving `6f8803c` -> cherry-pick `88cc7a9` (103/103 pass; content 200, traversal 404 verified over real HTTP). NOT accepted: symlink escape defect — repair candidate `0f6e8f0` (root-only, work/engine) completed by backend, awaits `m0-service-review-002` (dep now satisfied).
- Engine private-goal/memory repair done by lead: candidate `f84cd4b` (slash->dot StateUpdate paths for goal/memories/last_entry, memories surfaced in private obs with numeric slot sort, 3 positive tests; 11/11 + 106/106). Report `cf951b0`, evidence/m0-engine-private-repair-001/. DISTINCT review submitted: `m0-engine-private-review-002` (reviewer). Prior assets APPROVE `ba2f7e0` is invalid for this finding; `m0-engine-review-correction-002` remains assets-owned.
- Client `c60548b` APPROVE (map-viewer scope, `c69b1da`) — integration of `client/**` still pending acceptance-hold correction (`m0-viewer-review-correction-002`, reviewer-owned).
- WS/reconnect ownership transferred to lead post-004 per operator. Queued: begins only after `0f6e8f0` verdict + integration (no concurrent app.py writer). Material: reports/backend-handover-2345; rejected phase2 `d5c4305` NOT integrated.
- Next after engine review passes: freeze engine interface, route separate local-runtime-adapter task, then real local-model action + atomic receipt/event/state + reconnect + inference-free replay.

# Session Handoff — Living Kanto (main-lead, 2026-10-04 ~21:00Z)

Supersedes all earlier handoffs. Authoritative facts: `/home/jetson/csds-access/living-kanto-20261004-0300/VERIFIED_FACTS_CURRENT.json`; task grid: `docs/TASK_BOARD.md`; full spec: `docs/PROJECT_GUIDE.md`. All seat tools execute on the Jetson; model machines are inference-only; every seat worktree (including frontend) is locally accessible here.

## Verified state

- Canonical `main` HEAD `f77526d`. Approved contracts `0911c8a`; backend `8f63907` integrated `75cba50`, 82 PASS independently. Service-002 **phase 1** `6f8803c` (branch `work/engine`): lead-verified — 13 new + 79 total PASS (rig venv), live smoke on lead-owned :8878 (bytes-identical PNG, traversal/symlink 404, health ok); `evidence/m0-service-002-001/lead-verification-phase1.json`. NOT accepted: reviewer seat inactive (supervisor 20:40Z). Phase 2 (WS/resync/replay) in progress.
- Contracts reality: `StateUpdate.prior_state_hash` (world content-hash staleness gate) + `StateUpdate.apply_to`; `previous_head` = event-chain hash. `PatchOp`/`ActionProposal` never existed — earlier docs were wrong.
- venv `…/venv/bin/python3`: fastapi 0.142.2, pydantic 2.13.5, httpx 0.28.1, uvicorn 0.54.0.
- pret pin `037335f4c725d7c9aecdac87066f2002b4bd7e14` at `/home/jetson/projects/living-kanto/reference/pokefirered`; `d2d6646d…` is an assets candidate commit, not the pin; no `.cache` pret path.
- Inventory 005: report-only research (425 known) at `…/worktrees/review/control/reports/m0-reference-inventory-provenance-005`; not accepted; mechanics not implemented; no LICENSES/14-asset/evidence-folder acceptance exists.

## Corrected this repair

Removed invented `PatchOp`/`ActionProposal`, wrong pret pin/path, wrong venv versions, fabricated inventory acceptance, nonexistent frontend commit `6832624`. Frontend work real/local: `…/worktrees/frontend/client` (index.html, js/maps.js, js/run.js, js/main.js), uncommitted.

## Active seats (operator 20:16Z)

lead spark-worker1 32k (this seat, shared contracts + integration); builder pcright 32k (m0-service-002: API/launcher owner — no duplicate API/static implementation anywhere else); reviewer spark-master 16k (queued service/viewer reviews); assets spark-master 16k; frontend macright 16k (`client/**` only).

## Next (order) — updated 22:40Z

1. DONE: engine slice committed `5da8a5a` (simulation/** + test_simulation_m0.py; 8/8 engine + 90/90 suite PASS on operator venv). Classified *implemented + auto-verified, awaiting independent review*. Tested signatures published to builder; independent review requested of reviewer seat (candidate 5da8a5a).
2. AWAITING verdicts: API static `6f8803c` (frontend, m0-api-static-review-002, 13 static tests PASS), client `c60548b` (reviewer, m0-viewer-review-001 + browser proof), engine `5da8a5a`. Integrate only accepted paths, retain `0911` contracts, no AGENTS, no whole-branch merges. Rejected service phase2 `d5c4305` NOT integrated; controller queued m0-service-cursor-repair-003.
3. After reviewed engine: freeze interface, give builder a separate real-local-runtime adapter task (no dependency cycle with integration parent), then demonstrate real local-model action + atomic receipt/event/state + reconnect + inference-free replay. Map-only viewer is not accepted M0.
4. Assets m0-assets-repair-003 stalled-blocked: diagnosis + 4-step re-dispatch scope at `evidence/m0-assets-repair-003-lead-diagnosis.md` (correct 2-line portable `--out` fix sits uncommitted in assets worktree). Controller is sole dispatcher.
5. Canonical `content/` WIP and assets `311494d` remain unaccepted; preserve.

## Boundaries

M0–M5 goal stands: 100 private persistent humans, mainland Kanto, 151 species, hidden battle choices, atomic ownership, Survival/Creative, benchmark 1/2/4/8, 2h GAME soak, zero-badge champion — none started. No cloud implementation/fallback humans/grants/fabrication. Simulation slice ≠ faithful-complete mechanics. Preserve files/transcripts.
