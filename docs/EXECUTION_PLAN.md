# Practical execution configuration (Phase 4)

## Bottleneck

Everything runs on one Apple M1 GPU (MacBook Pro 17,1, 16 GB). Measured with `llama-batched-bench`
(Qwen3-4B-Instruct-2507 Q4_K_M, q8_0 KV cache, 2,048-token prompts):

| parallel sequences | prompt processing (tok/s) | token generation (tok/s, aggregate) |
|---:|---:|---:|
| 1 | 210.6 | 18.0 |
| 2 | 211.8 | 20.8 |
| 4 | 212.1 | 37.7 |
| 8 | 211.8 | 59.7 |

Parallel sessions raise aggregate decode throughput about 3.3x at 8 sessions. Prompt processing does not scale at
all, and prompt processing is the cost that caching policies change.

## Measured cost per episode (smoke run, 10 episodes, Baseline B native cache)

The 10-episode smoke run took 34.5 minutes of wall time. Per-episode wall time (agent plus hidden evaluation):

| workload | episodes | wall time (s) | prefill (s) | decode (s) |
|---|---:|---|---|---|
| repeated_prefix | 2 | 146, 201 | 30, 32 | 110, 167 |
| concurrent | 2 | 101, 212 | 14, 42 | 72, 163 |
| tool_wait | 2 | 95, 338 | 9, 28 | 52, 230 |
| bursty | 2 | 112, 187 | 13, 41 | 91, 140 |
| unique_prefix | 2 | 962, 963 | 362, 392 | 533, 583 |

With the cache working, decode dominates. Without prefix reuse (the unique-prefix control, and every workload under
Baseline A), prefill dominates and an episode takes roughly 5-6x longer.

## Why the full matrix does not fit

Extrapolating from these measurements, one 50-episode tier costs about 2.2 h end-to-end under B or C and about 5 h
under A. All 1,000 episodes would therefore take about 44 h per cached configuration and about 100 h for A, or
roughly 230 h of end-to-end runs for the four configurations, before trace replays (which cost about the same again).
An earlier rough estimate of "60+ hours" was too low.

## Configuration actually executed

| Run | Episodes | Status |
|---|---|---|
| Smoke test (B) | first 10 of the manifest | done: `results/smoke/native_cache` |
| Baselines A, B, C, end-to-end | tier 0 = episodes 0-49 (10 per workload, 23 of 25 bug categories) | `scripts/run_baselines.sh` |
| Baselines A, B, C, trace replay of B's recorded traces | same 50 sessions | `scripts/run_baselines.sh` |
| Optional extension to 100 episodes | tier 1 = episodes 50-99 | `scripts/run_baselines.sh --tier1` |
| Candidate D (Rust policy) | same tiers as the baselines | after the baseline freeze |
| 500 and 1,000 episode tiers | tiers 2-3 | not run live on this Mac. Same scripts run them unchanged (`--tiers 2,3`) on more hardware. Any virtual-time simulation of these tiers will be labelled as simulation in the reports, never mixed with measurements |

Expected time for tier 0: about 8-9 h for B and C (end-to-end and replay), then about 9-10 h for A.

## Controls for a fair comparison

* Configurations run one after another, never in parallel: they share the GPU and the ports.
* Same immutable manifest (`manifests/master_manifest.jsonl`, sha256 recorded in every `run.json`).
* Same frozen code, model (sha256-checked) and llama.cpp build (checked against `expected_build`) for every run.
  The git commit is recorded per invocation.
* The agent's step budget (15 model calls) is the binding limit. The episode timeout is 3,600 s and only guards
  against hangs, so slow configurations are not penalised on correctness by a wall-clock cut-off.
* The run requires AC power. Power source and thermal notes are sampled into `monitor.jsonl` once a minute.
* Runs are resumable. A retried episode's earlier partial requests are excluded from the metrics by request id.
