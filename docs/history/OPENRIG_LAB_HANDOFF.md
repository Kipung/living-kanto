# Handoff: larger OpenRig test using local models

## Objective and current instruction

Run a larger, project-based OpenRig test using the validated local-model fleet. The user is preparing a separate project guide. Read that guide before choosing tasks, assigning roles, or launching the test. The current request is to prepare this handoff; the larger test has not started.

The user wants a meaningful project test of planning, tool use, coordination, and finished work. Once the guide is provided, use its success criteria to define the test. Do not substitute an invented project or claim the larger test has already passed.

## Validated allocation

| Serving machine | Model | Runtime |
|---|---|---|
| Spark-master | Qwen3.8-27B NVFP4 | Existing pinned SGLang Docker image |
| Spark-worker1 + Spark-worker2 together | Qwen3.8-Flash-Next NVFP4 | Existing pinned vLLM Docker image, tensor parallel 2, existing GB10 compatibility patches |
| PC-left, RTX 4090 | Qwen3.8-27B Q4_K_M | Portable native llama.cpp CUDA |
| PC-right, RTX 4090 | Qwen3.8-27B Q4_K_M | Portable native llama.cpp CUDA |
| Mac-left, M2 Max, 32GB | Qwen3.8-27B Q4_K_M | Native llama.cpp Metal |
| Mac-right, M2 Max, 32GB | Qwen3.8-27B Q4_K_M | Native llama.cpp Metal |

Seven machines provide six independent model endpoints because the two Spark workers jointly serve one model. All Sparks are connected through the existing ring/switch topology; the user has used all three together previously. The requested test allocation keeps master independent and workers paired. The pair passed actual distributed inference over its existing 200 Gb/s link. No network rewiring is needed.

Do not start Gemma on the Sparks. The Qwen embedding container `ember-embedding` on master was stopped at the user's request; preserve its cached data and leave it stopped.

## What has passed

All seven machines passed endpoint readiness, model listing, arithmetic (17 × 23 = 391), valid multiply-tool arguments, and shutdown/closed-endpoint checks. All missing GGUF models were downloaded and SHA256 verified. Existing Spark weights were verified and reused. Models remain cached; pilot servers were stopped.

The first OpenRig integration passed on Mac-left: OpenRig 0.6.3 launched a Pi 1.0.2 agent through an SSH tunnel to Qwen3.8-27B. The agent completed startup identity lookup, wrote `391` to `serving-proof.txt`, read it back with its read tool, and replied `CSDS_SERVING_OK`. The isolated rig, daemon, and serving process were stopped after the test. Existing OpenRig rigs were retained.

These results establish short serving and one-agent integration only. Concurrent agents, longer project conversations, throughput, failure recovery, and project quality remain untested. Windows Docker/WSL remains unavailable; the Windows results certify native CUDA serving, not Docker readiness.

## Critical configuration lesson

The successful OpenRig test used a 16,384-token serving context and matching provider metadata. An 8,192-token configuration left only one output token because Pi subtracts a 4,096-token safety allowance from its prompt estimate. Do not launch project agents with the old 2,048-token smoke-test context.

The isolated Pi settings disabled automatic compaction for the short test and set reserveTokens and keepRecentTokens to 1,024. Treat these as test settings, not a proven long-project policy. Validate the intended context and compaction settings against real project prompts before broad launch. Check RAM/GPU capacity as context grows.

OpenRig already has a Pi adapter and custom OpenAI-compatible provider support. No central routing layer was deployed. The next test can use explicit endpoint/provider assignments. The generic `lab serve` command does not yet launch the tested dual-Spark recipe or native Windows recipe automatically.

## Access and locations

Control host: Jetson, reached from the Mac with `ssh -i ~/.ssh/jetson_codex jetson@100.67.203.65`.

On Jetson:

- Control scripts and results: `/home/jetson/csds-access/model-controls`.
- Lab wrapper: `/home/jetson/csds-access/lab`.
- SSH machine aliases: `spark-master`, `spark-worker1`, `spark-worker2`, `pcleft`, `pcright`, `macleft`, `macright`.
- Existing OpenRig CLI: `/home/jetson/.local/npm-global/bin/rig`.
- Installed isolated Pi 1.0.2: `/home/jetson/csds-access/model-controls/runtime/node_modules/.bin/pi`.
- Previous isolated OpenRig workspace: `/home/jetson/csds-access/model-controls/openrig-smoke`.
- Previous isolated state: `/home/jetson/csds-access/model-controls/openrig-smoke/state`.
- Previous isolated daemon port: 23371; it is stopped. Inspect before reuse.
- Spark recipe: `spark_pilots.py`; expiry guard: `container_expiry.py`.
- Mac test: `mac_pilots.py`; controls: `serve`, `worker.py`, `profiles.json`.
- Windows test: `pc_pilot.ps1`, `run_pc_pilots.py`.
- Passing OpenRig test recipe: `openrig_smoke.py`. Read and adapt it; it is a smoke-test script, not a fleet service.

Model locations:

- Mac-left: `/Users/csdsstudent/.local/share/csds-serving/models/Qwen3.8-27B-Q4_K_M.gguf`.
- Mac-right: `/Users/cbulabmac/.local/share/csds-serving/models/Qwen3.8-27B-Q4_K_M.gguf`.
- PC-left: `D:\csds-serving-student\models\Qwen3.8-27B-Q4_K_M.gguf`.
- PC-right: `D:\csds-serving-student2\models\Qwen3.8-27B-Q4_K_M.gguf`.
- Spark models: existing Hugging Face caches under `/home/kip`; use the exact snapshot paths in `spark_pilots.py` and its reports.
- Existing dual-Spark deployment: `/home/kip/qwen38-dual-spark`.

Pinned artifacts:

- Mac llama.cpp: `/opt/homebrew/Cellar/llama.cpp/0.5.0/bin/llama-server`.
- Windows portable llama.cpp: build b11384, CUDA 12.4, under each serving root's `runtime-b11384`.
- GGUF revision: `71bc7b627595dc8a91039addd9c791ae548d6747`; size 18,973,870,528 bytes; SHA256 `c600de0300ae8a0eb3a6c0b8b5561b8b96f16bd2c863c2a66c42de29d391a747`.
- Master NVFP4 revision: `319f741cce68d7914884900c138a1fbb70a42f30`.
- Flash-Next NVFP4 revision: `fc694b54fb0174e0913e6adf86691ef85a4ead47`.
- SGLang image digest: `sha256:febfb971c7352570fc445c466ebd6ffc9d896024958e544a60f2137fd85856b1`.
- vLLM image digest: `sha256:fc120ece0a388cc0aa1caad4a9f1cd92113484ab7ec2fd0efadd62585be05bf8`.

## Proposed larger test, subject to the project guide

1. Read the guide and identify the concrete deliverable, permitted workspace, dependencies, constraints, and acceptance checks. Ask only for genuinely missing requirements.
2. Inspect current users, memory, GPU load, running services, and port availability. Previous idle-state evidence is not a guarantee of current availability.
3. Create a fresh, isolated project test workspace and OpenRig instance with a unique name, state directory, and port. Start the daemon with `--no-kernel` to avoid automatically booting unrelated kernel seats.
4. Bring up the Spark pair and Spark-master first with bounded shutdown guards. Start selected native endpoints and validate project-sized contexts. Keep endpoints on localhost and reach them through explicit SSH tunnels.
5. Configure a seat-scoped Pi `models.json` for each endpoint. Match context metadata to the actual server and select the declared local provider/model explicitly. Keep cloud credentials out of the isolated configuration.
6. Start with three agents: Flash-Next for planning/coordination, one 27B implementation agent, and a different 27B reviewer/tester. These roles are a proposal; change them to suit the guide. Scale to the other endpoints after a successful coordinated task.
7. Give agents non-overlapping ownership and an explicit integration procedure. Use separate worktrees or directories where simultaneous edits would conflict. Define how agents exchange tasks, results, and review feedback.
8. Test a full project cycle: plan, implement, use tools, hand work to another agent, review, repair, integrate, and run the guide's acceptance checks. Judge the actual artifact, not just the agents' completion messages.
9. Exercise concurrent requests, a bounded agent restart or reconnect, and graceful shutdown. Record errors rather than silently switching to a cloud model.
10. Save evidence, stop only test rigs/processes/containers, verify closed endpoints and recovered memory, and preserve downloaded models.

Do not run all six endpoints simply to maximize agent count. Start with the smallest useful project team, then expand to test fleet capacity. The proposed role allocation and agent count have not been decided by the user.

## Evidence and success criteria

Capture exact runtime/model/context settings, seat-to-endpoint mappings, tool transcripts, request latency, resource use, coordination events, retries, and failure reasons. Measure completed acceptance checks and defects found by review. Record any manual intervention and confirm that all inference used the declared local models.

A useful outcome report should distinguish:

- Serving and connection readiness.
- Actual multi-agent coordination.
- Project acceptance results.
- Performance under concurrency.
- Recovery and cleanup behavior.

Keep existing desktop/student sessions, other OpenRig rigs, model caches, and unrelated containers intact. Inspect the helper scripts for test limits and known assumptions before reusing them. Use new unique rig names; re-importing the same name created ambiguous rig records during the smoke test. Teardown by exact rig ID when available.

## Local evidence for the next session

Workspace: `/Users/kipung/Documents/Codex/2026-10-03/files-pasted-by-the-user-handoff`.

- `outputs/fleet-validation-20261004.md`: human-readable fleet and integration report.
- `outputs/model-controls/results/*-qwen-pilot-20261004.json`: per-endpoint serving results; Flash covers both workers.
- `outputs/model-controls/results/openrig-smoke-20261004.json`: passing OpenRig launch, tool-loop completion, and teardown.
- `outputs/model-controls/results/openrig-agent-transcript.jsonl`: independent write/read/completion evidence.
- `outputs/model-controls/results/final-test-process-check.json`: final pilot process/container checks.

Next action: receive the user's project guide, turn it into a concrete test scope and acceptance plan, then run the larger isolated local-model OpenRig test.
