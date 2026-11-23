# Does Session-Aware KV Caching Speed Up Coding Agents? A Measured Experiment on a Single Mac

*Draft for review.*

**At a glance**

- I built a full agent-serving stack on one 16 GB MacBook, with a coding agent, a Rust gateway, an open-source router and a 4B model running on llama.cpp. I then benchmarked three serving setups on 100 real coding tasks each.
- **Routing each request to the server that already holds its cache (KV-aware routing) made agents 15.9% faster**, cut time to first token by 32.7%, and raised the cache-hit rate from 80.4% to 98.6%.
- **Adding session-aware cache management on top did not help at this scale.** It was 3.6% slower in controlled replay, and almost all of that loss came from one burst-heavy workload.
- The result suggests my test conditions were too mild for session-aware caching to pay off. The second half of this article lays out how I'd test that properly.

All code, the 1,000-task benchmark and the raw results are public: [github.com/sanat77/agent-aware-routing](https://github.com/sanat77/agent-aware-routing).

---

## Problem statement

The next trillion users of the web won't be people. They'll be AI agents. Agents already write production code at scale: Stripe's agents open over 1,300 pull requests a week [1]. A single coding session can make hundreds of model calls, and each call carries the entire conversation so far [1]. Context windows have grown from a few thousand tokens to up to a million, and agents use that room.

The hardware hasn't kept pace. Everything a model remembers about a conversation lives in its KV cache, in GPU memory, and that memory is small. For a 70B-parameter model like Llama 3 70B, the KV cache takes about 320 KB per token [6]. A single 128k-token conversation needs about 40 GB, half of an 80 GB H100, before counting the model itself. A GPU can hold only a few long agent conversations at once. Everything else gets evicted and recomputed from scratch.

So the bottleneck for agents isn't only how fast we compute. It's how well we decide what to keep in memory.

A coding agent doesn't send a model one request. It reads an issue, calls a tool, reads the result, and calls the model again, 16 times per task on average in this benchmark. Each call carries the full conversation so far. Across the 100 tasks per setup here, that came to 1,637 model calls and 4.86 million prompt tokens, most of which the model had already seen.

Before generating anything, a model must process its input. This is the **prefill** step, and its output is stored in the **KV cache**. If the cache for a conversation is still in memory, the next call only prefills the new tokens. If it isn't, the whole conversation is recomputed. On the hardware, a full recompute of a long agent prompt costs tens of seconds, while a cache hit costs about one.

NVIDIA's Dynamo team describes this pattern as write-once-read-many in [Full-Stack Optimizations for Agentic Inference with NVIDIA Dynamo](https://developer.nvidia.com/blog/full-stack-optimizations-for-agentic-inference-with-nvidia-dynamo/) [1]. That post was the starting point for this experiment. It splits the problem into layers. One is **KV-aware routing**: send each request to the worker that already has its cache. Another is **Session-aware KV-cache management**: decide which caches to keep, using what the agent harness knows, such as which agents are paused on tools and which have finished. This experiment talks majorly about the second layer, session-aware caching, as an open design in the KV-cache space.

KV-aware routing makes sure a request goes to the GPU that holds its cache. It can't make sure the cache is still there when the request arrives. While an agent waits on a tool, the GPU may evict its cache to make room for other agents. Meanwhile, caches of agents that have already finished can keep taking up memory.

The question I wanted to answer on real inference was this: **if the GPU also knows which agents are still working, which are paused on a tool, and which have finished, and uses that to decide which caches to keep and which to evict, do agents get faster than with KV-aware routing alone?**

## Assumptions

### Concepts

I use these terms throughout:

- **Round robin:** send requests to servers in turn, ignoring what each one has cached.
- **KV cache:** the stored result of prefill, so a prompt's prefix isn't recomputed.
- **KV-aware (prefix-aware) routing:** send each request to the server holding the longest matching prefix of its prompt. For a full treatment, see the router section of the NVIDIA post [1] and the Dynamo router guide [2].
- **Session:** all requests from one agent working on one task.
- **Slot:** a place on the server that holds one conversation's KV cache. When all slots are full, something must be evicted.

### Experiment constraints

| Item | Value |
|---|---|
| Hardware | 1× MacBook Pro, Apple M1, 16 GB unified memory (one GPU) |
| Model | Qwen3-4B-Instruct-2507, Q4_K_M weights, q8_0 KV cache |
| Inference engine | llama.cpp `llama-server`, build b11669, Metal |
| Servers | 2 llama-servers × 2 slots = **4 KV slots**, 16k context per server (about 8k tokens per slot) |
| Built-in cache | llama.cpp host-RAM prompt cache, 2 GB per server (on in all setups) |
| Router | [llm-router](https://github.com/zxuhan/llm-router), pinned at commit `c1345f71` |
| Tasks | 100 per setup, about 10.5 hours of compute per setup |
| Rules | Real inference only, with no mocks, no paid APIs and no simulated latency. Result sets are never overwritten. |

The two servers share one GPU. That makes this a test of policy logic, not of multi-machine performance.

## The experiment

### The stack

```
LangGraph coding agent  ──►  llm-router  ──►  Rust gateway (per server)  ──►  llama-server
  (tags session ID,          (S1: round robin     (S3: session manager:        (Qwen3-4B,
   tool-wait, finished)       S2/S3: KV-aware)     evict / save / restore)      2 slots)
```

- **MiniIssueTracker**: a small web app I wrote, with 1,000 planted bugs. Each bug, plus its failing test, is one **episode**. The agent must find and fix the bug without breaking the hidden tests.
- **Agent**: built with LangGraph. It has file read, search, edit and test-run tools.
- **Rust gateway**: an Axum service in front of each server. It records per-request timing and cache metrics in all setups. In S3, it also runs the session manager.
- **Harness**: replays a fixed episode manifest (sha256-pinned), collects 20 metrics, and computes paired bootstrap confidence intervals.

### The three setups

| Setup | Routing | Cache management |
|---|---|---|
| **S1** | Round robin | llama.cpp default (recency-based) |
| **S2** | KV-aware (llm-router, longest-prefix match) | llama.cpp default |
| **S3** | KV-aware (same as S2) | **Session-aware gateway policy** |

S2 is the same idea as NVIDIA Dynamo's KV-aware router, implemented here by llm-router. S3 keeps S2's routing and changes only one thing: which cache gets evicted when a server runs out of slots. The next section explains how.

### The Rust gateway and session manager (S3)

The gateway is a small Rust service (Axum and Tokio) that sits between the router and each llama-server. It exposes the same OpenAI-style chat API as llama.cpp, so the router and agent don't know it's there.

**In all three setups**, the gateway is a pass-through that measures. It logs per-request queue time, prefill time, time to first token, which slot served the request, and how many prompt tokens were reused or recomputed. Because S1, S2 and S3 run through the same gateway, its overhead is about the same in every setup (8–11 ms per request), and every metric is measured the same way.

**In S3**, the gateway also runs the **session manager**, which is the component under test. llama.cpp on its own sees anonymous requests. It reuses or evicts slots based on prompt similarity and recency. The session manager adds what llama.cpp can't see: which agent each request belongs to, and what that agent is doing.

*Signals from the agent.* The agent sends two kinds of information:

- **A session ID on every model request**, as an `x-session-id` HTTP header.
- **Lifecycle events**, sent to `POST /v1/sessions/{id}/events`: `session_start`, `tool_wait_start` (with the expected wait), `tool_wait_end`, and `completed` or `failed`.

From these, the manager tracks every session as **Active**, **Waiting** (on a tool) or **Finished**. It also tracks which of the server's slots holds each session's cache.

*Decisions it makes.* The gateway pins each request to a slot it chooses, using llama.cpp's `id_slot` field, instead of letting llama.cpp pick. When a request arrives:

```text
on request for session s:
  if s's cache is in an idle slot      → reuse it                 (warm hit)
  if every slot is busy                → wait at the gateway
  else pick a victim slot, in order:
    1. empty slot
    2. slot held by a FINISHED session  → erase (largest first)
    3. slot held by a session WAITING on a tool → save its KV to disk first
                                                  (longest-waiting first)
    4. least-recently-used active slot
  if s was saved earlier               → restore its KV from disk into the slot
on session finish                      → erase its slot immediately
```

*How it moves caches.* Saving, restoring and erasing use llama.cpp's slot API (`/slots/{id}?action=save|restore|erase`). A saved session's KV is written to a file on local SSD. The total is capped at 4 GB per server, and the oldest files are dropped first. When a saved session's agent returns, its KV is loaded back into a slot instead of being recomputed.

*What it costs.* Each save and restore runs before the request it serves. They averaged 361 ms and 249 ms in replay. When every slot is busy, the request waits at the gateway until one is freed. S1 and S2 have neither cost.

This is the harness-to-orchestrator signal path the NVIDIA post argues for [1], in a minimal form: a session ID and three lifecycle states. The policy is about 450 lines of Rust with unit tests, in [`gateway/src/sessions.rs`](https://github.com/sanat77/agent-aware-routing/blob/session-cache/gateway/src/sessions.rs).

### Workloads

The 100 episodes are split evenly across five traffic patterns. Each pattern tests a different stress on the cache.

| Workload | Concurrent agents | Tool wait per step | What it stresses |
|---|---|---|---|
| repeated_prefix | 1 | 0 s | Pure prefix reuse |
| concurrent | 2–8 | ~0.5 s | Agents competing for slots |
| tool_wait | 4 | **6.6 s mean, 25.5 s max** | Cache survival across tool pauses |
| bursty | 8 | ~0.25 s | 8 agents on 4 slots, arriving together |
| unique_prefix | 4 | ~0.5 s | No shared prefix (control case) |

### Method

- **Real-agent runs.** The agent actually solves each task. This captures everything, including task success, but the agent's choices vary from run to run.
- **Controlled replay.** I recorded every request the agent made under S2, then replayed the identical request stream, with the same timing, against S1 and S3. This removes agent randomness and is the primary speed comparison.
- **Statistics.** I paired results by episode and computed 95% bootstrap confidence intervals with 10,000 resamples. "Significant" below means the interval excludes zero.

### Hypothesis

H1: S2 beats S1 (KV-aware routing helps). H2: S3 beats S2 (session-aware caching helps further).

### Results

**Controlled replay, 100 episodes, paired:**

| Metric | S2 vs S1 | S3 vs S2 |
|---|---|---|
| Session latency | **−15.9%** [−18.8, −12.9] | +3.6% [+1.0, +6.5] |
| Time to first token (mean) | **−32.7%** [−37.2, −28.4] | +7.6% [+0.9, +15.2] |
| Prefill time | **−24.5%** [−32.0, −17.9] | +1.7% [−3.1, +7.1] (n.s.) |
| Recomputed prompt tokens | **−26.5%** [−33.6, −20.7] | +3.4% [+0.6, +7.3] |
| Queue wait | **−41.5%** [−52.0, −33.2] | +15.1% [+0.8, +33.0] |

| Cache metric (replay) | S1 | S2 | S3 |
|---|---|---|---|
| Cache-hit rate (eligible requests) | 80.4% | 98.6% | 98.2% |
| Cache fully kept across a tool wait | 66.5% | 99.1% | **100%** |
| KV held by finished sessions (mean tokens) | 6,957 | 6,055 | **371** |
| Avoidable live evictions* | 87 | 20 | **0** |
| Resumption TTFT after a tool wait (mean) | 9.2 s | 4.1 s | **3.7 s** |

\*An avoidable eviction is a live agent's cache being evicted while a finished agent's cache still held a slot.

**Real-agent runs** confirmed the direction. S2 vs S1: latency −9.2% [−16.0, −1.6], TTFT −29.0%. S3 vs S2: latency +11.2% [+2.0, +21.0], TTFT +24.3%, queue wait +43.4%. Task success was 38% (S1), 30% (S2) and 29% (S3), with no significant differences, as expected for a serving-layer change.

**Where S3's time went (replay):**

| Cost | Count | Time |
|---|---|---|
| Saves to disk | 272 | 361 ms mean |
| Restores from disk | 226 | 249 ms mean |
| Requests waiting at the gateway for a free slot | 283 | 9,873 s total |
| Routing decision | per request | ~1 ms (vs <1 µs in S2) |

**By workload (replay, mean session latency, n = 20 each):**

| Workload | S2 | S3 | Difference |
|---|---|---|---|
| repeated_prefix | 138.1 s | 138.9 s | +0.6% |
| concurrent | 438.3 s | 447.3 s | +2.1% |
| tool_wait | 496.3 s | 489.5 s | **−1.4%** |
| bursty | 990.4 s | 1,101 s | **+11.2%** |
| unique_prefix | 1,004 s | 1,001 s | −0.3% |

The four non-bursty workloads roughly cancel each other out. **The bursty workload accounts for nearly all of S3's total deficit.** It is the one pattern where 8 agents arrive at once for 4 slots, and S3 recomputed 33% more tokens there than S2 (165k vs 125k). On tool_wait, the workload S3 was designed for, S3 was slightly ahead. Per-workload samples are small, so these are directions, not significant results.

Charts are in the repo: [latency CDF](../reports/assets/cluster_one_mac_run1/replay_latency_cdf.png), [per-workload bars](../reports/assets/cluster_one_mac_run1/replay_workload_bars.png) and [cache metrics](../reports/assets/cluster_one_mac_run1/replay_cache.png).

## Conclusions

1. **KV-aware routing is the main win, and it is solid.** H1 holds on every latency and cache metric, in both replay and real-agent runs. Turning on prefix-aware routing removed most cache misses: hits went from 80% to 99%, and cache kept across tool waits went from 67% to 99%. This agrees with the NVIDIA post's point that cache-blind routing sends a conversation's next turn to the wrong worker about (N−1)/N of the time [1].
2. **H2 is not supported at this scale.** The session-aware policy worked mechanically. It reached 100% retention, zero avoidable evictions, about 16× less memory held by finished sessions, and faster resumption. But S2 had left very little to recover, about 1% of tool waits lost cache. Save/restore and gateway slot waits cost more than that.
3. **The loss is concentrated, not spread evenly.** S3 matched or slightly beat S2 where it was designed to help (tool waits). It lost under bursts. The most likely cause is the gateway's "wait for a free slot" path. With 8 simultaneous agents and 4 slots, S3 holds requests at the gateway, and saves run on the request path. S2 has neither.
4. **Scope of the claim.** On one Mac, with a 4B model, about 8k-token contexts, 4 slots and these five workloads, session-aware caching did not improve on KV-aware routing. This does not show that session-aware caching doesn't help in general. The takeaway is that this experiment was run on a small scale that the marginal benefit of using S2 vs S3 is not high.

## If I ran it again

The hypothesis was that S3 would beat S2, and it didn't. There are two possible explanations:

- **A. S3 isn't better.** KV-aware routing plus the engine's built-in cache already captures nearly all the value.
- **B. The test couldn't show it.** The benchmark didn't create the conditions session-aware caching exists for, so S3 paid its overhead and had nothing to win.

The evidence leans toward B. The NVIDIA post frames the eviction problem as one that appears in a high-traffic environment, where a 2–30 second tool pause is long enough for an agent's prefix to age out [1]. My setup had little of that pressure:

| Condition | This experiment | Production coding agents |
|---|---|---|
| Agents per KV slot | ≤ 2 (8 agents / 4 slots, often fewer) | Tens to hundreds per GPU |
| Tool waits | One workload, 6.6 s mean | Seconds to minutes (builds, tests, approvals) |
| Context length | ~8k tokens per slot | 32k–200k tokens [1] |
| Recompute cost vs restore | Close, so restore barely wins | Recompute grows with context, so restore wins clearly |
| Fallback cache | 2 GB host-RAM prompt cache quietly rescued S2 | Under pressure, fallback tiers fill up too |
| Workers | 2 servers sharing one GPU | Independent GPUs |

S2 lost only 2 of 218 tool-wait resumptions. No caching policy can beat a baseline that only misses 1% of the time by much. To decide between A and B, I'd change the test suite as follows.

**1. Sweep memory pressure instead of testing one point.** I'd run S2 and S3 at 1×, 2×, 4× and 8× more concurrent agents than KV slots. If B is right, S3 loses at low pressure, as it did here, and wins past some crossover. The crossover point is the result we're fishing for. If S3 never crosses over, A is right.

**2. Use realistic tool waits in every workload.** I'd draw wait times from real agent traces, from seconds up to several minutes. I'd also sweep the wait length, since longer waits are exactly when recency-based eviction removes caches that are about to be reused.

**3. Use long contexts.** I'd run tasks on larger repositories, so sessions reach 32k–128k tokens. Recompute cost grows with context length, while restore cost grows only with bytes moved. That shifts the trade-off toward S3.

**4. Remove the fixable overhead first.** I'd move saves off the request path and replace the gateway's slot wait with admission control. Without that, a bigger test would partly measure an implementation flaw, as the bursty result suggests.

**5. Use production-like hardware and more samples.**

- **GPUs:** several independent GPU servers (for example, H100- or L40S-class), so each worker has its own memory and compute, and routing decisions behave as they do in a real cluster.
- **Model:** a larger model in the 30B+ range, or a mixture-of-experts model. It has a larger KV cache per token and slower prefill, which raises the cost of every miss.
- **Engine:** vLLM or SGLang, whose paged KV caches and priority-based eviction [1] are closer to production than llama.cpp slots.
- **Samples:** 300+ episodes and at least three repeated runs per setup, to measure run-to-run variance and narrow the confidence intervals.

**Decision rule.** **B is confirmed** if S3 beats S2 on session latency and TTFT, with intervals excluding zero, once agents outnumber slots and waits are realistic. **A is confirmed** if S2 still matches S3 there.

## What's next

- **Fix S3's overhead and re-run.** Make saves asynchronous and remove the gateway slot wait. Then repeat run1's conditions to separate the idea from the implementation.
- **Run the pressure and tool-wait sweep** above. It is the most direct test of the hypothesis.
- **Prediction-based prefetch.** S3 reacts to agent state. The next step is to predict it, for example: "this agent started a test suite and typically returns in about 40 seconds." The cache can then be restored just before the agent's next request arrives. The NVIDIA post describes the same direction as harness-driven prefetch hooks [1].
- **Measure which agent signals matter.** I'd ablate the hints (session ID, tool-wait flag, expected wait time, finished flag, some other signal that helps estimating the session wait time) one at a time to see which ones carry the benefit.
- **Go multi-machine.** I'd run the same three setups across separate machines, using the three-Mac profile already in the repo, where routing decisions carry more weight.

## References

1. NVIDIA, "Full-Stack Optimizations for Agentic Inference with NVIDIA Dynamo," NVIDIA Technical Blog. https://developer.nvidia.com/blog/full-stack-optimizations-for-agentic-inference-with-nvidia-dynamo/ (This post inspired the project and covers KV-aware routing, agent hints, cache retention and lifecycle-aware caching.)
2. NVIDIA Dynamo, KV Router guide. https://docs.dynamo.nvidia.com/dynamo/v-0-9-1/components/router/router-guide
3. llama.cpp. https://github.com/ggml-org/llama.cpp
4. llm-router (MIT), pinned at commit `c1345f71`. https://github.com/zxuhan/llm-router
5. Project repository: code, benchmark manifest, raw results and generated reports. https://github.com/sanat77/agent-aware-routing
6. Meta Llama 3 70B model configuration (80 layers, 8 KV heads, head dimension 128). The KV size is 2 × 80 × 8 × 128 × 2 bytes ≈ 320 KB per token at FP16. https://huggingface.co/meta-llama/Meta-Llama-3-70B
