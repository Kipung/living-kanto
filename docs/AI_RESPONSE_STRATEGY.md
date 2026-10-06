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
