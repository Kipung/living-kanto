# Local team operations

The user authorized autonomous local-model development through the complete project guide. Do not finish after planning or an intermediate prototype. The operator controller keeps serving leases alive and dispatches bounded tasks; it does not certify game mechanics or release completion.

Control root: `/home/jetson/csds-access/living-kanto-20261004-0300`.
Canonical repository: `/home/jetson/projects/living-kanto` (lead only).
Reference: `/home/jetson/projects/living-kanto/reference/pokefirered`.
Bob's World read-only foundations: control root `/bobs-foundations`.

Three initial seats, all Pi with isolated local provider configuration:

| Seat | Local inference | Ownership |
|---|---|---|
| main-lead@living-kanto-20261004-0300 | paired Spark-workers Flash-Next, 32768 context | contracts, canonical integration, task routing, milestone evidence |
| main-builder@living-kanto-20261004-0300 | PC-left Qwen27, 32768 context | assigned implementation in `/home/jetson/projects/living-kanto-worktrees/engine`, branch work/engine |
| main-reviewer@living-kanto-20261004-0300 | PC-right Qwen27, 32768 context | independent tests/review in `/home/jetson/projects/living-kanto-worktrees/review`, branch work/review |

The initial worktrees start at bootstrap. After shared contracts are committed and the first implementation has a bounded task, the worker must update its worktree to the exact specified commit while preserving its own changes. The lead integrates commits only after independent review. Only one writer owns each path during a task.

Task dispatch is file-backed and survives SSH/chat disconnects. The lead writes a bounded task prompt to a file, then submits it:

```
python3 /home/jetson/csds-access/living-kanto-20261004-0300/team.py submit --id m0-engine-001 --seat builder --file /absolute/task.md
```

Task IDs must be unique. Available seats initially: lead, builder, reviewer. Use `--depends task-a,task-b` for tasks that depend on successfully completed tasks. Prompts must include exact base commit, owned paths, contracts, output, acceptance checks and report path. Keep tasks small enough to finish and test one concrete deliverable. Agents should avoid dumping large files into their bounded context; use targeted reads and durable summaries. Automatic compaction is enabled with an 8192 reserve and 1024 recent tokens; validate behavior rather than assuming context safety.

The worker commits the artifact, writes its evidence report, and registers completion:

```
python3 /home/jetson/csds-access/living-kanto-20261004-0300/team.py finish --id m0-engine-001 --status completed --report /absolute/report.md --commit EXACT_COMMIT
```

Use blocked or failed truthfully when required. The controller forwards reports to the lead. A completed worker task never automatically means an acceptance gate passed. Review the actual artifact. Keep source test output in evidence and limitations in the handoff. `team.py status` shows durable records. Direct `rig send` is allowed for coordination, but durable assigned work should use this dispatcher.

Spark-master is reserved for runtime humans, reachable only through the local tunnel `http://127.0.0.1:18382/v1`. Read the discovered model ID from control root `fleet.json`. Runtime inference must be configured separately from development, outside portable data packs, with no cloud fallback. The mandatory representative world/battle benchmark at concurrency 1,2,4,8 precedes a 100-human release run. Do not replace it with the fleet arithmetic check.

After the first complete implemented/reviewed/integrated passing cycle, notify the operator via a durable report if extra PC-right/Mac-right workers would speed distinct engine/content/viewer streams. Do not start other services or alter the validated fleet recipes yourself.

Original assets and content are in the pinned reference checkout. Parse its maps, layouts, tile sets, palettes and sprite frames; do not redraw Kanto or generate artwork. A backend-owned pinned Pokémon Showdown gen3 simulator may be evaluated to reuse tested battle effects while keeping the Python/FastAPI/SQLite authority; cartridge-only catching, experience, traversal and ownership still need reference-backed implementations and verified adapters. Never assume competitive formats provide cartridge items or all adventure mechanics. Every deviation stays visible in the fidelity matrix.

The controller offers read-only progress at `http://127.0.0.1:23382`. It renews each project endpoint lease for one hour every five minutes. Guards stop at expiry, a project STOP file, or a 72-hour hard cap. No caches or unrelated processes are deleted. Long runs should be resumable from durable commits and evidence. Milestone and release statuses must be factual; preserve final gates until all guide evidence exists.

Stop/restart details belong in docs/SESSION_HANDOFF.md. Do not modify the operator controller, erase queue/evidence, push/publicly distribute artwork, or claim a release merely because tests with scripted minds passed.

## Measured startup adjustments

Native 16K contexts were too tight after startup reference reads; the builder produced an empty length-limited response. PC-left and PC-right now serve 32768 contexts with q8_0 KV cache and Flash Attention, matching provider metadata, 4096 response allowance and 8192 compaction reserve. The same builder/reviewer conversations and worktrees resumed. Mac-left was stopped after swap use rose from zero to about 1327 MiB. It remains available for a separately measured lighter workload; no model cache or unrelated service was removed. The Spark lead output allowance was reduced from 8192 to 4096 after a 32768-token context rejection. Actual errors and recovery are recorded in control/native-context-upgrade.json, lead-context-restart.json and operator-interventions.jsonl. These serving facts do not prove game acceptance or sustained runtime capacity.
