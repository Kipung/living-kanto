# Concurrent AI response strategy

The goal is 100 independent people acting at normal speed under one authoritative world clock. Inference runs asynchronously; movement continues from each person's accepted intention while another decision is pending. Each person retains private observations, memory and goals. Shared model weights do not imply a shared mind.

## Capacity and current evidence

The existing Qwen38 27B service delivered approximately 11 accepted decisions/minute in the earlier bounded real-world study. Increasing concurrency from 4 to 8 did not improve throughput and roughly doubled median response latency. Those samples used a changing live world and are development evidence, not a complete capacity gate.

100 people deciding once per minute require 100 decisions/minute; once every two minutes requires 50. At 11/minute, equal allocation gives each person a new decision about once every nine minutes. Long walking intentions help, but cannot solve fresh battle-turn decisions or responsive conversations alone.

## Proposed architecture

1. Keep one shared 1× simulation clock and independent private minds. Never make movement wait for all 100 models to finish a round.
2. Pool fast local inference on spare workers for frequent individual actions and battle turns. Use the larger model for less frequent personal planning or complex reasoning, passing only that person's authorized context.
3. Use short, strictly validated decisions selecting numbered legal options. Preserve private facts and exact canonical arguments. Validate again against current engine state before committing.
4. Let AI choose longer journeys and bounded intentions; the engine advances their physical effects. Reconsider when interrupted or when important private events arrive.
5. Schedule urgent battle/social decisions with bounded deadlines and fair aging. Allow at most one outstanding request per person. Limit GPU concurrency using measured throughput and latency, not population size.
6. Move expensive observation preparation off the clock's critical path with immutable snapshots and safe geography caching; retain canonical commit and freshness checks.

## Isolated fast-model pilot

An offline cached Gemma4 E2B model was launched on spare Spark-worker1 using a pinned existing vLLM image. The first GPU backend failed; native FlashInfer with TRTLLM attention disabled booted successfully. No live world provider was changed.

Five frozen private observation cases included a battle. Initial protocol warmup decoded 4/5 cases successfully, with three corrective retries. Tightening conditional text constraints yielded only 1/5 successful cases, including failures after the permitted corrective retry. Some responses reached the 128-token cap. One successful battle proposal took approximately 1.06 seconds, but this does not establish reliable throughput or behavior quality. Neither run advanced to the 1/2/4/8 load sweep. Preserve both outcomes; do not select this candidate for production.

The numbered-menu adapter passes 31 tests. Wire character counts fell about 8–11%; token savings and inference speed gains have not been demonstrated. The adapter is an experimental tool, not connected to live runtime. Battle option coverage requires further work before promotion.

## Next acceptance steps

Diagnose raw schema/response failures locally and test a less complex constrained format or a stronger small model. Require valid outputs across representative travel, dialogue, service and battle cases before load testing. Benchmark 1/2/4/8 with accepted decisions/minute, p95 queue/response latency, per-person coverage, invalid/stale decisions, memory and shared-clock pace. Then run an isolated 100-person actual-model world at 1× and check independent behavior, privacy, replay and sustained responsiveness. Only that evidence can justify a claim that all 100 have responsive AI.

Temporary pilot containers and its two SSH forwards were removed. Existing Qwen service and live world remain active at 1×, concurrency 8. Latest check: 325 accepted decisions, 8 pending, 51 ready, no runtime failure, measured clock 0.958×. This is a point-in-time status, not a new soak.

References: [Gemma4 model card](https://ai.google.dev/gemma/docs/core/model_card_4), [vLLM attention backends](https://github.com/vllm-project/vllm/blob/main/docs/design/attention_backends.md), [SGLang structured outputs](https://docs.sglang.io/docs/advanced_features/structured_outputs). Model support and constrained syntax do not prove game decision quality.

## Follow-up: successful E4B throughput experiment

The next cached local model, Gemma4 E4B revision fee6332c1abaafb77f6f9624236c63aa2f1d0187, booted on spare Spark-worker1 using the same pinned vLLM image/native FlashInfer workaround. A flat JSON schema and 384-token ceiling retained exact decoder checks. These changes were tested together; the experiment does not isolate whether model size, grammar simplification or token budget explains improved reliability.

Five representative warmups and 64 subsequent proposals all decoded successfully without retries. With 16 requests per level, 1/2/4/8 concurrency delivered approximately35/67/131/238 valid proposals/minute. Repeated five-case prefix caching limits that sample's generality.

A stronger follow-up captured all100 people's private observations at identical paused world version6341.56 had legal choices, including13 battle cases; the other44 were in states without an offered new decision. All56 warmups passed with two corrective retries. A100-request load sample across the56 eligible cases at concurrency8 completed in23.84seconds:100 valid proposals,251.69/minute, median1.46seconds, p95 3.145seconds, three corrective retries (unused text). All raw private observations stayed in ignored work files; receipts contain safe metadata only.

This exceeds the100 decisions/minute target for **read-only offered proposals**, not engine-accepted actions. Frozen observations, prefix reuse and no world mutations mean queue fairness, stale-world handling, independent behavioral quality and full100-person response times remain unverified. Observed actions included battle moves, walking, conversations, journeys and services; action variety alone does not establish quality. The adapter's battle option coverage caveat remains.

Next implementation step: put this validated wire protocol behind a configurable local provider adapter, finish battle option coverage, preserve one corrective retry then pause, and test in an isolated100-person actual-model world at1×. Measure canonical accepted throughput, per-person decision waits and behavior before changing the user's provider. Multi-worker routing and larger-model planning tiers remain proposals.

Temporary E4B container and pilot-only forwards were removed after the test. The live Qwen world remains at1×/8,488 accepted decisions and no failure at final check. Its unrelated battle pause was repaired by hydrating467 cloud-evicted Showdown dependency files; readonly battle probes and copied turn resolution passed before resume. No engine timeout increase or backend restart was used. See battle-timeout-diagnosis.json.

Receipts: evidence/ai-strategy/e4b-flat-384.json, e4b-diverse-100.json,100-case-preparation.json,e4b-launch.json. Benchmark diagnostics/tool compile and31 wire tests passed. This is not a full release capacity gate or a sustained live-world soak.

## Visible actual-model world (2026-10-05 follow-up)

Live URL: http://localhost:8878/?world=fast-ai-live-20261005-v2&view=wall . Separate data/fast-live database,100 original individuals, requested1×,concurrency8, Gemma4 E4B on Spark-worker1. Existing8877 world/provider were not changed. Services deliberately remain running so the user can watch; restart keeps saved state paused and requires explicit resume.

Numbered adapter now lives in runtime, with local settings persisted through API. It expands doubles active-slot alternatives and retains exact decoder and engine freshness validation. First live flat-format run paused after15 decisions because its corrective envelope yielded a misleading canonical-format error. Exact-reason retry fix then accepted61 more decisions before another unused-text failure. Both failed observations remain preserved. Conditional grammar check failed all8 cases and was not adopted.

Final protocol chooses option+explanation first, then requests AI-authored text only when that selected action requires text. Both stages reject duplicate keys, extra fields and invalid types. No action is scripted or substituted. One corrective retry applies to the whole decision, then pause. Provenance is openai:numbered-staged. Both formerly failing people passed8/8 actual-model first-attempt probes. Dedicated17provider checks and39runtime/provider/shared checks passed; API configuration restart/export check passed separately.

The staged actual-model observation accepted10 choices in42.57wallseconds (~14.09/min), with no retries in that bounded interval. This is far below the frozen response-only benchmark and does not satisfy100freshchoices/minute. Current world preparation/commit/clock processing is a remaining performance bottleneck; detailed attribution still needs profiling. Requested1× is not guaranteed measured1×. All100 are visible, several move concurrently, conversations and work are actual model choices; not all100 move continuously.

Frozen replay atversion239 verified withzero inferencecalls. Latest coverage and current status are in fast-live-handoff.json, with source fingerprints and service handles. The earlier14/min result must not be reported as252engine-accepted choices/minute. No new soak, sustained capacity orchampionship gate was completed.

Startup uncovered widespread macOS cloud eviction of map/reference/source/cache files. Restored pinned public FireRed revision037335f4c725d7c9aecdac87066f2002b4bd7e14 placeholders from its archive, comparing resident reference files; discarded regenerated bytecode caches and used a temporary local bytecode directory. All256 map PNGs are resident. The last4 PNGs were restored from existing work copies with exact size/SHA256 manifest checks. No artwork edits or unrelated UI changes were made. Initial empty world stub fast-ai-live-20261005 is not a valid saved world; use the -v2 ID.

## User-requested32-concurrency trial

API/controller cap and asynchronous worker pool now permit32; defaults unchanged. Model server was relaunched withmax_num_seqs32 as living-kanto-e4b-live32, using the same weights/image/private port and0.35memory fraction. User world/save unchanged; resumed explicitly1× after startup.43targeted checks passed, including32simultaneous unique-actor workers, retired requests remaining within32across pause/resume, API32 persistence and33/bool rejection. Source65514da.

Read-only staged protocol test:64/64valid proposals from56private cases, peak32concurrent client decisions,29.04seconds(~132.23/min), median12.43s,p95 24.52s. This is inference/decoder evidence, not live acceptance, and differs in protocol/requestmix from the earlierflat8sample.

Changing live world baseline8:38accepted/40.12s(~56.83/min). Later32-limit observation:46accepted/48.85s(~56.50/min), sampledpeak15pending/queued,31simsecondsadvanced. No failure in that observation. This does not establish faster throughput with32 or that all32slots stayed busy; cold state/load and changing activity limit comparison. Preparation/commit processing remains the likely throughput bottleneck; detailed profiling is still needed.

The first32run paused with StoreError: run is paused; append rejected, after36accepted decisions. Cause not verified; no pause request appears in that server log. Save remained intact; after resume the bounded sample stayed running. Preserve this limitation rather than claim sustained reliability. No new full capacity gate/soak.

32configuration deliberately remains running for user experiment. Lateststate/modelcontainer/servicehandles in concurrency32-handoff.json. Screenshot ../../concurrency-32-live.png shows32capacity. The UI speed selector was showing20× while runtime requested1×; user/otherUIchat owns that UI and it was not changed by this trial.

### Background private preparation (2026-10-05)

Commits 6f4d64f and b5334b4 move private observation preparation off the canonical pump into four bounded preparation workers. The configured concurrency caps the combined preparation/inference jobs, including retiring generations; each actor owns at most one slot. Workers receive detached, read-only snapshots and never the canonical store. The pump alone advances the shared clock and validates/commits model answers. Runtime status separates `preparing_requests` from inference-only `pending_requests` and reports the last preparation duration. No human choices or private facts were removed.

Read-only profiling of 12 actual ready actors at version 1545 found 89% of instrumented preparation time in geographic journey planning. Threads free the canonical pump from synchronous capture, but Python CPU work still shares the interpreter; this implementation does not establish multi-core scaling. Commit 758d981 omits unrelated identity/history from internal route search copies and hashes each unchanged routing node once. All 40 frozen actual route results/unavailable outcomes matched the prior implementation, with 13.270s versus 11.817s sequential timing. This is an approximately 11% route benchmark improvement, not an engine-accepted throughput claim.

Verification: 16 preparation/shared-runtime checks pass, including blocked four-way preparation with continuing canonical clock, unchanged worker snapshots, pause responsiveness, retirement bounds, fair scheduling, failure without a provider call, replay integrity, and 32 concurrent inference calls. The broader field/runtime/API regression had 37 passing checks and one obsolete serial-preparation assertion; that assertion was updated to verify the new parallel boundary behavior and the shared suite then passed. Eight focused routing/journey tests pass. Independent review found no blocking race or privacy issue.

The initial thread-backed live sample at requested 1× accepted 63 decisions in 64.017 seconds (59.05/min), compared with 46 in 55.562 seconds (49.67/min) before the change. These are successive changing-world samples, not a controlled matched benchmark. Peak sampled inference requests fell from 12 to 8 and clock progress fell from 31 to 15 simulated seconds. This is a mixed result, motivating opt-in separate process preparation rather than claiming all 32 slots are fed or normal-speed clock throughput is solved. Receipts: `prep-live-before.json` and `prep-live-after.json`.

Separate CPU processes are now available with `LK_PREPARATION_MODE=process` (thread remains the default). Four spawned workers load content once; each task serializes a detached world snapshot and actor ID, returning only the private observation and dependency token. Spawn prevents inheriting the canonical SQLite connection, controller, or model provider. A broken process pool pauses with an explicit controller/server restart requirement; no thread or scripted fallback occurs. Running bounded preparation tasks finish after nonblocking shutdown.

Commit 23bff31 also avoids calculating all local and inter-map route choices while validating a non-route selected action. Observation menus still contain the full route choices. Validation retains dynamic mechanics checks, rejects unavailable actions, and conservatively falls back to the full menu near its 128-entry truncation boundary. Legacy custom legal-action overrides retain their old behavior. Twelve isolated route/validation checks pass, and 41 combined isolated preparation/shared-runtime/API/validation checks pass (46.03s). Other uncommitted movement/collision changes from another workstream were excluded from this verification and live trial.

The final process-backed live sample (`prep-live-process.json`) accepted 87 real-model decisions in 42.143 seconds: **123.86 accepted/minute**, with **32 simultaneous inference requests observed**. The shared clock advanced **41 simulated seconds** in that interval (0.973× measured interval speed) at requested 1×. All nine sampled statuses were running without a failure; the later handoff was also running with 29 inference requests and two preparations outstanding. This demonstrates full utilization of the configured 32 slots in this bounded run, not 100 simultaneous fresh model decisions or a sustained release-capacity/soak claim. The successive changing-world baseline was 49.67/min; the ratio is approximately 2.49× and is not an isolated causal benchmark.

`prep-process-handoff.json` records source 23bff31, 100 persisted humans, actual-model coverage of all 100, 1499 accepted model events with zero identified scripted-provider events at handoff, four preparation processes, the unchanged local Gemma4 E4B staged provider, and the live service/session. The committed server code is copied into `work/ai-strategy/prep-runtime/server` with content/reference/dependency links so concurrent uncommitted movement work cannot alter this trial. The visible client and existing save remain at the original project paths. The live model container and SSH forwards remain running.

### Further concurrency work (2026-10-05)

Commits 4305f3f, 5876274 and 65336e2 retain the detached preparation design and add three changes: remove one redundant full-world JSON round trip during `with_advanced_version` (source verification, candidate validation and full final hash remain); allow two explicitly configured private/local inference lanes with a strict runtime maximum of 64; and yield a backlog of completed answers after a 100ms drain budget following at least one atomic completion. Each staged decision stays on one lane. Least-outstanding scheduling uses rotating ties; failures propagate without endpoint failover or extra retries. Local endpoint lists persist outside portable saves; safe status exposes numbered lane counters only.

84 contract/store/replay/tampering checks pass. Frozen advancement and action/event results are identical in 12 comparisons. Detached clock advancement median fell from 0.167s to 0.130s; wait timings were inconclusive under concurrent host load. An isolated provider/numbered/shared/API suite passed 53 checks, including 64 simultaneous identified test-provider requests and persistent two-lane settings. A final isolated completion/shared/process/state-copy slice passed 27 checks. The slow-commit test shows clock progress before all eight completed answers commit, responsive pause, no writes after pause and identical replay.

The single-server model-only probe offered 128 frozen private decisions at concurrency 32, all valid/no corrections, in 30.659s (250.50/min). Two servers at 64 completed 128/128 in 13.666s (561.97/min). These are offered proposals, not engine acceptance, and prompt-cache warming is a major confound: a repeat gave 677.29/min at 32 versus 748.78/min at 64, only 10.56% higher, with p95 latency 4.375s versus 6.273s. Both repeats remained 128/128 valid/no corrections. Do not claim a 2.24× live or isolated hardware speedup from the first comparison. The live world was paused during these probes.

The final two-server live sample (`further-live64.json`) accepted 86 real-model decisions in 42.255s (**122.11/min**). Peak sampled inference concurrency was **49**, above the former 32 limit, and the shared clock advanced 42 simulated seconds (0.994× interval progress) at requested 1×. All sampled statuses were running without a failure. Both lanes handled real decisions. This establishes increased simultaneous thinking, while accepted throughput remains approximately the earlier best 122–124/min. The intervening 34.46/min baseline was a different evolving state under concurrent profiling/testing and must not be used to claim a clean 3.54× speedup. Canonical world validation/commit remains a scaling limit.

`further-handoff.json` records current source 65336e2, server 33837/session 10221,100 persisted humans, actual model coverage 100, zero scripted-provider events, paired GPU servers and the second lane forwards. The current source copy is `work/ai-strategy/further-runtime/server`, with explicit original client/content/data paths and linked dependencies; other workstream's uncommitted collision source remains excluded. The older `prep-runtime` copy/server 28793 is superseded. Model weights and runtime image are pinned identically across lanes. Full release capacity/soak/championship gates remain open.
