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

## Commands (from `agent-aware-routing-session-cache/`)

| Order | Command | What it does |
|---|---|---|
| 1 | `scripts/run_cluster.sh S2` | Smart router. For each tier: the real agents fix the bugs (every model request is recorded), then those exact requests are replayed |
| 2 | `scripts/run_cluster.sh S1` | Round-robin. For each tier: real agents, then replay of S2's recorded requests |
| 3 | `scripts/run_cluster.sh S3` | Smart router + session-aware cache. Same as S1 |
| - | `scripts/run_cluster.sh all` | S2, S1, S3 in order |
| - | `scripts/run_cluster.sh report` | rebuild every report from the raw results |

Every setup runs every one of the 1,000 episodes by default (`--tiers 0,1,2,3`), tier by tier
(50, 50, 400, 500 episodes), and averages are taken over all of them. A finished tier is complete and kept even
if you stop afterwards. Use `--tiers 0` for the first 50 only. `--check` runs the preflight only.

### Keeping results apart: `--run NAME`

Results go to `results/cluster/<profile>/<run>/<setup>/`. The default run name is `run1`.

* The same name resumes: completed episodes are never re-run or overwritten.
* A new name (`--run run2`) is a completely separate result set: use it to repeat the whole experiment and
  measure run-to-run variation (the model is not perfectly deterministic). The replays of a run always use the
  recording made by S2 in that same run.

### Time (estimated from Baseline B's measured speed; one Mac)

About 5 hours per 50 episodes per setup (real agents ~2.5 h + replay ~2.5 h). All 1,000 episodes: about
4-5 days per setup, about 2 weeks for S1+S2+S3 on one Mac, roughly a third of that with three Macs.
The first tier (50 episodes) of all three setups: about 15 hours.

## Inputs and outputs

In: `manifests/master_manifest.jsonl` (immutable), `configs/cluster.json`, the model file, the MiniIssueTracker
fault lab. Out, under `results/cluster/<profile>/<run>/`:

```
S2/e2e/tier<k>/episodes/*.json        per episode: bug fixed?, hidden tests, latency, tokens, helper sessions
S2/e2e/tier<k>/traces/*.jsonl.gz      every request (chat messages, session, role, timing) -> used by the replays
S{1,3}/e2e/tier<k>/...                same, for S1 and S3
S{1,2,3}/replay/tier<k>/replay_sessions.jsonl   per-request timings when the recorded requests are re-sent
*/logs/gateway_w*/requests.jsonl      per request: server, slot, cached vs recomputed tokens, TTFT, queue, slot actions
*/logs/gateway_w*/occupancy.jsonl     every second: which session holds each slot, finished-session tokens, saves
*/logs/router.log, router.yaml        llm-router decisions and config
*/logs/llama-server_w*.log, monitor_w*.jsonl, final_stats.json, run.json (provenance, git commit, wall time)
run_cluster_<setup>_<time>.log        console log of each command
```

Reports (rebuilt from the raw results, which are never modified):

* `reports/generated/cluster_<profile>_<run>_tables.md`: the 20 metrics per setup (averages, p50/p95/p99, counts),
  per-workload tables, paired comparisons (S2 vs S1 = step 1 effect, S3 vs S2 = step 2 effect) with 95% bootstrap
  intervals, the session-cache table (memory held by finished sessions, live-session evictions and how many were
  avoidable, saves/restores and their cost, request share per server, router decisions); charts in
  `reports/assets/cluster_<profile>_<run>/`.
* `reports/generated/cluster_<profile>_all_runs.md`: headline numbers per run and the mean ± std across runs.
* `reports/generated/history/`: a dated copy of the run's report at the end of every command.

## What to expect

* S1 vs S2: round-robin splits a session's turns across both servers, so more prompt tokens are recomputed;
  prefix-aware keeps a session on one server until that server's slots are full (then it spills over).
* S2 vs S3: differences appear only when slots are contended (bursty, concurrent and tool-wait workloads):
  S3 should hold less finished-session cache and avoid evicting live sessions, at the cost of disk saves/restores
  (measured: ~43 ms to save and ~15 ms to restore a 1,200-token session on this Mac). With few sessions per
  slot it may show no difference; that is a valid result.
* Correctness (bug-fix rate) should not depend on the setup; the real-agent runs check that.

## Verified before handing over

Rust unit tests (19, including the session manager's eviction order), a 2-episode S3 end-to-end run through
llm-router (helper sessions created and erased on finish, no slot-action errors), a 2-episode S1 replay through
both servers, the report pipeline on that data, and the across-runs summary. The full runs have not been executed.
