# Multi-server experiment: smart router (step 1) + session-aware caching (step 2)

Branch `session-cache`, folder `agent-aware-routing-session-cache/` (a git worktree next to the frozen baseline
folder, so the baseline code stays untouched).

## What runs

```
multi-agent LangGraph app  ->  llm-router  ->  gateway w0 (Rust)  ->  llama-server w0
(lead + explorer + reviewer     (picks a       gateway w1 (Rust)  ->  llama-server w1
 sub-agents, each its own        server)       (picks a slot; S3: session-aware cache)
 session; sends lifecycle
 events)
```

| Setup | Router (step 1) | Gateway on each server (step 2) |
|---|---|---|
| S1 | llm-router `roundrobin` | passthrough: llama.cpp picks the slot |
| S2 | llm-router `prefixaware` (sends a request to the server holding its prefix) | passthrough |
| S3 | llm-router `prefixaware` | `session_cache`: erases a finished session's cache at once, saves a paused session's cache to disk before reusing its slot, restores it when the session returns |

Same model (Qwen3-4B, sha256-checked), same llama.cpp build, same 1,000-episode manifest as the baselines.
The app differs from the baselines: it uses the OpenAI chat API (llm-router requires it) and multi-agent mode,
so these results are compared with each other (S1/S2/S3), not with the frozen A/B/C baselines.

Profile `one_mac` runs two llama-servers (2 slots each) on this Mac. They share one GPU, so it validates the logic;
distributed timing claims need `three_macs` (edit hosts in `configs/cluster.json`; each remote Mac needs
llama.cpp, the model and this folder at `remote_repo`; SSH keys for passwordless login).

## Commands (run in order, from `agent-aware-routing-session-cache/`)

| # | Command | What it does | Time for tier 0 (50 episodes, one Mac) |
|---|---|---|---|
| 1 | `scripts/run_cluster.sh record` | S2 end-to-end: the real agents fix the 50 bugs; every model request is recorded | ~2.5 h |
| 2 | `scripts/run_cluster.sh S1` | S1 end-to-end on the same 50 bugs, then S1 replay of the recorded requests | ~5 h |
| 3 | `scripts/run_cluster.sh S2` | S2 replay of the recorded requests | ~2.5 h |
| 4 | `scripts/run_cluster.sh S3` | S3 end-to-end, then S3 replay | ~5 h |
| - | `scripts/run_cluster.sh all` | 1 to 4 in order | ~15 h |
| - | `scripts/run_cluster.sh report` | rebuild the tables (also done after every stage) | seconds |

Add `--tiers 0,1` for 100 episodes, `--tiers 0,1,2,3` for all 1,000 (the time scales roughly with the episode count).
End-to-end runs of S1/S3 stop at the first 200 manifest episodes; replays cover every selected tier.
`--check` runs the preflight only. Ctrl-C is safe; re-running the same command resumes.

## Inputs and outputs

In: `manifests/master_manifest.jsonl` (immutable), `configs/cluster.json`, the model file, the MiniIssueTracker
fault lab. Out, under `results/cluster/<profile>/`:

```
S2/e2e/tier0/episodes/*.json        per-episode result: bug fixed?, hidden tests, latency, tokens, helpers
S2/e2e/tier0/traces/*.jsonl.gz      every request (chat messages, session, role, timing) -> used by the replays
S{1,3}/e2e/tier0/...                same, for S1 and S3 (correctness under each setup)
S{1,2,3}/replay/tier0/replay_sessions.jsonl   per-request timings when the recorded requests are re-sent
*/logs/gateway_w*/requests.jsonl    per request: server, slot, cached vs recomputed tokens, TTFT, queue, slot actions
*/logs/gateway_w*/occupancy.jsonl   every second: which session holds each slot, finished-session tokens, saves
*/logs/router.log, router.yaml      llm-router decisions and config
*/logs/llama-server_w*.log, monitor_w*.jsonl, final_stats.json, run.json (provenance, git commit, wall time)
run_cluster_<step>_<time>.log       console log of the command
```

Report: `reports/generated/cluster_<profile>_tables.md` with the 20 metrics for each setup, per-workload tables,
paired comparisons (S2 vs S1 = step 1 effect, S3 vs S2 = step 2 effect) with 95% bootstrap intervals, the
session-cache table (memory held by finished sessions, live-session evictions and how many were avoidable,
saves/restores and their cost, request share per server, router decisions), and charts in `reports/assets/`.

## What to expect

* S1 vs S2: round-robin splits a session's turns across both servers, so more prompt tokens are recomputed;
  prefix-aware keeps a session on one server until that server's slots are full (then it spills over).
* S2 vs S3: differences appear only when slots are contended (bursty, concurrent and tool-wait workloads):
  S3 should hold less finished-session cache and avoid evicting live sessions, at the cost of disk saves/restores
  (measured: ~43 ms to save and ~15 ms to restore a 1,200-token session on this Mac). With few sessions per
  slot it may show no difference; that is a valid result.
* Correctness (bug-fix rate) should not depend on the setup; the end-to-end runs check that.

## Verified before handing over

Rust unit tests (19, including the session manager's eviction order), a 2-episode S3 end-to-end run through
llm-router (helper sessions created and erased on finish, no slot-action errors), a 2-episode S1 replay through
both servers, and the report pipeline on that data. The full 50-episode runs have not been executed.
