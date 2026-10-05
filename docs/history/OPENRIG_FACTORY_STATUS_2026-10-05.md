# FACTORY_STATUS — Living Kanto

Owner: `main-lead@living-kanto-20261004-0300`
Updated: 2026-10-05 ~09:00Z (Lead, autonomous operation)
Authority: this file is the single published factory picture. `docs/TASK_BOARD.md`
is historical (last written 2026-10-04 ~22:35Z) and is **materially wrong** about
two candidates — corrections are listed under "Board corrections" below.

---

## 1. Canonical state

| Item | Value | How verified |
| --- | --- | --- |
| Canonical `main` HEAD | `a2c430c` | `git rev-parse HEAD` in `/home/jetson/projects/living-kanto` |
| Accepted product baseline | `75cba50` | `git merge-base --is-ancestor 75cba50 main` → yes |
| Shared contracts | `0911c8a` | ancestor of `75cba50` |
| Working tree | **dirty** — `AGENTS.md`, `content/**`, `server/living_kanto/api/app.py`, `server/living_kanto/store/run_store.py`, `client/index.html` modified; `server/tests/test_api_ws_protocol.py` untracked | `git status --porcelain` |

The dirty tree is **not cleaned up**. Per operator instruction "retain WIP, no WIP
reset," it is preserved and listed in §5 with a named owner for each part.

## 2. Test status — measured today, not inherited

Two different numbers were circulating. Both are real; they measure different sets.

| Set | Result | Wall time | Command |
| --- | --- | --- | --- |
| **Tracked canonical suite** (7 files under `server/tests/`) | **110 passed, 0 failed** | **~9 s** | `pytest -q --ignore=tests/test_api_ws_protocol.py` |
| Untracked `tests/test_api_ws_protocol.py` (23 tests, added by Frontend, never committed) | 4 failures; **2 of them HANG indefinitely** | >400 s, killed | `pytest tests/test_api_ws_protocol.py` |

### The "repeated-unbounded-test-hang" incident is now root-caused

It is **not** an engine/store slowness problem and it is **not** a full-suite problem.

- The tracked suite completes in ~9 seconds. Proven twice.
- The hang is entirely inside one untracked file. `pytest -k far_behind` alone
  exits 124 under a 90 s `timeout` — a single test, isolated, hangs forever.
- Therefore every prior "full suite takes 7–8 minutes / appears to hang" report was
  this one file being swept in by a bare `pytest` collection.

The four affected tests:
- `test_connect_far_behind_does_not_stream_the_whole_backlog` — **hangs**
- `test_store_rewound_underneath_connection_repairs_to_snapshot` — **hangs**
- `test_unsafe_run_id_closes_4004_without_serving_anything[../escape]` — fails
- `test_unsafe_run_id_closes_4004_without_serving_anything[]` — fails

These tests assert WS backlog/resync behaviour in
`server/living_kanto/api/app.py` `_stream_events`. That code is **Lead-owned**
(shared-contract boundary). The file was excluded from the canonical suite rather
than deleted, so the evidence is retained.

**Gate to clear this:** Frontend commits the file to their worktree branch with the
two hanging tests bounded (explicit `asyncio.wait_for`, no unbounded receive loop),
plus the two unsafe-run-id expectations reconciled with actual server behaviour.
Lead then integrates and re-measures. Until then, `pytest` must be run with the
`--ignore` above and that exclusion is stated in every report, not hidden.

## 3. Candidate ledger

| Candidate | What | Real state | Gate |
| --- | --- | --- | --- |
| `0f6e8f0` | static root containment | **INTEGRATED** as `a2c430c` | done |
| `f84cd4b` | engine private goal/memory dotted-path repair | **INTEGRATED** as `77d9056` | done |
| `ba2f7e0` | prior engine review | APPROVE — **invalid scope** for the private-goal finding; does not cover `f84cd4b` | superseded |
| `537cfa9` | viewer run lifecycle (was `c60548b`) | **NOT integrated**, confirmed: `git merge-base --is-ancestor 537cfa9 HEAD` → false | blocked, see §4 |
| `ffa7a09` | runtime LocalProvider/ProviderConfig restore | **REJECTED** by StoreQA (`798f27c` verdict FAIL) | blocked, see §4 |

## 4. Open blockers (each with a named owner and one acceptance gate)

### B1 — Client lifecycle regression in `537cfa9` — owner: **Frontend**, reviewer: **Reviewer**
Operator-verified 08:36Z (`reports/operator-resume-20261005/client-lifecycle-regression.json`),
independent of 45 passing fixtures:
1. From page `http://localhost:8124/client/index.html`, the constructed socket is
   `ws://localhost:8124/client/index.html/ws/run-test` instead of origin-root
   `/ws/run-test`.
2. Raw `humansCache` was moved onto exported `Run.state`, exposing `private_mind`.
   The accepted `ebbd8c0` kept that cache module-private. The `publicHumans` filter
   still passes but does not prevent the raw exposure — a privacy-contract violation.
Action: Reviewer reproduces against source, rejects or routes a bounded local
Frontend repair and re-reviews. **Do not integrate as accepted.**

### B2 — Runtime decision receipt `ffa7a09` — owner: **Runtime builder**, verdict owner: **StoreQA**
StoreQA FAIL (`798f27c`) stands, and the operator's independent probe
(`actual-engine-synthetic-receipt.json`) agrees:
- `explanation_in_saved_event` = **false**, `explanation_in_saved_state` = **false**
  → the decision rationale is validated in memory but never persisted.
- `returned_new_state_hash_is_state_hash` = **false** while
  `returned_new_state_hash_is_event_head` = **true** → `SimulationEngine.commit()`
  returns `store.append_event(...)`, which `run_store.append_event` documents as
  "Returns the new head hash." The field is **misnamed**, not merely mistyped.
- `visible_in_own_observation_after_commit` = true, `visible_in_event_log` = true,
  `visible_in_other_humans` = false → privacy and log visibility are sound.
Root cause for the persistence half is already identified: `build_action_event`
puts only `action/action_hash/target/args` into `payload`, so a top-level
`decision_explanation` is dropped before it reaches the store. The Lead-owned
partial fix (`action_arguments` in `causation`) is sitting **uncommitted** in the
engine worktree and is *not* the explanation fix.
Action: Runtime builder lands explanation persistence + renames the return to
`event_head_hash` (or returns both explicitly), with a receipt that asserts
`explanation_in_saved_event AND explanation_in_saved_state AND
returned_event_head_hash_is_event_head`. StoreQA re-verifies. Lead integrates only
after that.

### B3 — Board says "ready", reality says otherwise — owner: **Lead** (this file)
See "Board corrections."

## 5. Preserved WIP (nothing reset)

| Location | Content | Disposition |
| --- | --- | --- |
| canonical `main` tree | `app.py`, `run_store.py`, `client/index.html`, `content/**`, `AGENTS.md` modified; `test_api_ws_protocol.py` untracked | leave in place; classify before any future commit |
| engine worktree (`m0/runtime-adapter-001` @ `798f27c`) | uncommitted one-line `causation.action_arguments` in `build_action_event`; untracked `control/reports/m0-runtime-decision-receipt-004/`, `m0-engine-private-review-002/server/` | retain; fold into B2 candidate |
| stashes | `stash@{0}` "wip-agents-md", `stash@{1}` "AGENTS.md openrig managed block (pre-rebase)" | retain |

## 6. Board corrections (`docs/TASK_BOARD.md` is stale/wrong)

- `m0-viewer-run-lifecycle-reviewed` is recorded **READY**. It is not: `537cfa9`
  has two operator-verified regressions (B1). Status → **BLOCKED**.
- `m0-runtime-decision-receipt-004` is recorded **READY**. It is not: StoreQA
  verdict is **FAIL** at `798f27c` (B2). Status → **BLOCKED**.
- `m0-service-launch-002` is recorded **IN REVIEW** for `0f6e8f0`; that candidate
  was integrated as `a2c430c`. Status → **LANDED** for the root-containment part.

## 7. Honest classification

- **Implemented + automatically verified:** contracts, canonical hashing, store
  chain, replay, engine private-visibility repair, static root containment —
  110 tracked tests pass in ~9 s.
- **Real-model verified:** nothing at this moment. The earlier "actual engine
  PASS" claim was retracted by the operator and is contradicted by
  `actual-engine-synthetic-receipt.json`.
- **Incomplete:** WS backlog/resync protocol (B-two hanging tests), runtime
  decision-receipt persistence (B2), client lifecycle + privacy exposure (B1),
  and everything downstream — 100 persistent humans, gyms, league, Observer /
  Survival / Creative modes, history/replay/export UI, capacity benchmark,
  two-hour soak, autonomous championship evidence run.

## 8. Next acceptance gates, in order

1. **B2** runtime receipt: persisted explanation + honest hash naming → StoreQA PASS.
2. **B1** client lifecycle: correct origin-root WS URL + raw private cache restored
   module-private → Reviewer APPROVE on a *new* candidate.
3. Re-measure the tracked suite plus the repaired WS file; publish the real number.
4. Only then resume feature scope toward `lk-native-autonomous-full-project`.
