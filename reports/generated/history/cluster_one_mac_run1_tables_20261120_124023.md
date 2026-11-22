# Generated tables: cluster_one_mac_run1

## End-to-end agent benchmark

Episodes per config: S2 prefix-aware=100; common episode set = 100

| Metric | S2 prefix-aware |
|---|---|
| 1 Task success rate | 30.0% (30/100) |
| 2 Hidden test pass rate | 54.9% (6094/11100) |
| 3 Regression-free patch rate | 28.0% (28/100) |
| 4 Tool-call success rate | 95.3% (1147/1203) |
| 5 E2E latency p50 / p95 / p99 (s) | 540.7 / 1,313 / 1,534 |
| 6 TTFT p50 / p95 / p99 (ms) | 5,398 / 46,568 / 74,942 |
| 7 Prefill latency mean / p95 (ms) | 7,698 / 36,515 |
| 8 Session-resumption latency mean / p95 (ms) | 3,812 / 10,596 (n=218) |
| 9 Queue wait mean / p95 (ms) | 5,611 / 33,645 |
| 10 Successful tasks per minute | 0.095 |
| 11 Eligible-request cache-hit rate | 98.8% (1106/1120) |
| 12 Prefix-cache reuse ratio | 69.7% (3386126/4856671) |
| 13 Recomputed prompt tokens (total) | 1,470,545 |
| 14 Retention across tool waits (fully retained) | 99.5% (217/218) |
| 15 Prefix-loss events / slot switches / host-cache saves | 14 / 511 / 1418 |
| 16 Peak RSS llama / gateway (MiB) | 5,497 / 7 |
| 17 Mean slot utilization / KV occupancy est. | 0.67 / 0.20 |
| 18 Slot busy max/mean ; request CV | 1.06 ; 0.24 |
| 19 Routing decision (us) mean / gateway overhead (ms) mean | 0.07 / 8.12 |
| 20 Model / tool / episode failure rate | 0.0% (0/1637) / 4.7% (56/1203) / 0.0% (0/100) |

### Per-workload breakdown

**repeated_prefix** (n=20 per config)

| Metric | S2 prefix-aware |
|---|---|
| Task success | 35.0% (7/20) |
| E2E latency mean / p95 (s) | 139.0 / 215.3 |
| TTFT mean / p95 (ms) | 2,371 / 6,131 |
| Prefill mean (ms) | 2,347 |
| Queue wait mean (ms) | 0 |
| Cache-hit rate (eligible) | 100.0% (206/206) |
| Prefix reuse ratio | 88.3% (678357/768456) |
| Recomputed tokens | 90,099 |
| Resumption latency mean (ms) | n/a |
| Prefix-loss events | 0 |

**concurrent** (n=20 per config)

| Metric | S2 prefix-aware |
|---|---|
| Task success | 25.0% (5/20) |
| E2E latency mean / p95 (s) | 453.1 / 701.2 |
| TTFT mean / p95 (ms) | 3,491 / 9,135 |
| Prefill mean (ms) | 3,289 |
| Queue wait mean (ms) | 113 |
| Cache-hit rate (eligible) | 100.0% (237/237) |
| Prefix reuse ratio | 89.5% (827043/923849) |
| Recomputed tokens | 96,806 |
| Resumption latency mean (ms) | n/a |
| Prefix-loss events | 0 |

**tool_wait** (n=20 per config)

| Metric | S2 prefix-aware |
|---|---|
| Task success | 25.0% (5/20) |
| E2E latency mean / p95 (s) | 501.7 / 692.3 |
| TTFT mean / p95 (ms) | 4,122 / 10,783 |
| Prefill mean (ms) | 3,794 |
| Queue wait mean (ms) | 239 |
| Cache-hit rate (eligible) | 99.1% (225/227) |
| Prefix reuse ratio | 88.3% (786094/890590) |
| Recomputed tokens | 104,496 |
| Resumption latency mean (ms) | 3,812 |
| Prefix-loss events | 2 |

**bursty** (n=20 per config)

| Metric | S2 prefix-aware |
|---|---|
| Task success | 35.0% (7/20) |
| E2E latency mean / p95 (s) | 998.7 / 1,257 |
| TTFT mean / p95 (ms) | 31,752 / 72,890 |
| Prefill mean (ms) | 4,521 |
| Queue wait mean (ms) | 26,996 |
| Cache-hit rate (eligible) | 95.1% (231/243) |
| Prefix reuse ratio | 87.0% (832488/956359) |
| Recomputed tokens | 123,871 |
| Resumption latency mean (ms) | n/a |
| Prefix-loss events | 12 |

**unique_prefix** (n=20 per config)

| Metric | S2 prefix-aware |
|---|---|
| Task success | 30.0% (6/20) |
| E2E latency mean / p95 (s) | 1,006 / 1,537 |
| TTFT mean / p95 (ms) | 29,604 / 63,968 |
| Prefill mean (ms) | 29,014 |
| Queue wait mean (ms) | 442 |
| Cache-hit rate (eligible) | n/a |
| Prefix reuse ratio | 1.0% (8815/846143) |
| Recomputed tokens | 837,328 |
| Resumption latency mean (ms) | n/a |
| Prefix-loss events | 0 |

![e2e_workload_bars](../assets/cluster_one_mac_run1/e2e_workload_bars.png)
![e2e_latency_cdf](../assets/cluster_one_mac_run1/e2e_latency_cdf.png)
![e2e_cache](../assets/cluster_one_mac_run1/e2e_cache.png)
![e2e_slot_utilization](../assets/cluster_one_mac_run1/e2e_slot_utilization.png)

### Session-aware cache metrics (End-to-end)

| Metric | S2 prefix-aware |
|---|---|
| Memory held by finished sessions: mean tokens (sum over servers) | 6,815 |
| Live-session evictions (cache of an unfinished session pushed out of its slot) | 260 |
| ... of which avoidable (a finished session's cache was still resident) | 21 |
| Finished-session caches reused / erased on finish | 219 / 0 |
| Saves to disk / restores (failures) | 0 / 0 (0/0) |
| Mean save / restore time (ms) | n/a / n/a |
| Gateway slot waits (count, total s) | 0 (0.0) |
| Request share per server | w0=62%, w1=38% |
| Router decisions | fallback-least-loaded=56, longest-prefix=1280, spilled-fallback-least-loaded=290, spilled-from-saturated=11 |

Live/avoidable evictions are counted identically in all setups from the slot that served each request; only S3 acts on them. S1/S2 never save, restore or erase.

## Controlled trace replay

Episodes per config: S2 prefix-aware=100; common episode set = 100

| Metric | S2 prefix-aware |
|---|---|
| 1-4 Correctness | not measured in replay (agent decisions are fixed) |
| 5 E2E latency p50 / p95 / p99 (s) | 545.9 / 1,295 / 1,527 |
| 6 TTFT p50 / p95 / p99 (ms) | 5,505 / 46,791 / 67,616 |
| 7 Prefill latency mean / p95 (ms) | 7,771 / 38,032 |
| 8 Session-resumption latency mean / p95 (ms) | 4,055 / 10,847 (n=218) |
| 9 Queue wait mean / p95 (ms) | 5,548 / 34,704 |
| 10 Sessions per minute | 0.317 |
| 11 Eligible-request cache-hit rate | 98.6% (1104/1120) |
| 12 Prefix-cache reuse ratio | 69.4% (3372428/4856671) |
| 13 Recomputed prompt tokens (total) | 1,484,243 |
| 14 Retention across tool waits (fully retained) | 99.1% (216/218) |
| 15 Prefix-loss events / slot switches / host-cache saves | 16 / 520 / 1427 |
| 16 Peak RSS llama / gateway (MiB) | 5,262 / 7 |
| 17 Mean slot utilization / KV occupancy est. | 0.68 / 0.19 |
| 18 Slot busy max/mean ; request CV | 1.06 ; 0.23 |
| 19 Routing decision (us) mean / gateway overhead (ms) mean | 0.08 / 9.92 |
| 20 Model / tool / episode failure rate | 0.0% (0/1637) / n/a / 0.0% (0/100) |

### Per-workload breakdown

**repeated_prefix** (n=20 per config)

| Metric | S2 prefix-aware |
|---|---|
| E2E latency mean / p95 (s) | 138.1 / 214.7 |
| TTFT mean / p95 (ms) | 2,360 / 6,114 |
| Prefill mean (ms) | 2,329 |
| Queue wait mean (ms) | 0 |
| Cache-hit rate (eligible) | 100.0% (206/206) |
| Prefix reuse ratio | 88.3% (678357/768456) |
| Recomputed tokens | 90,099 |
| Resumption latency mean (ms) | n/a |
| Prefix-loss events | 0 |

**concurrent** (n=20 per config)

| Metric | S2 prefix-aware |
|---|---|
| E2E latency mean / p95 (s) | 438.3 / 665.7 |
| TTFT mean / p95 (ms) | 3,772 / 9,482 |
| Prefill mean (ms) | 3,483 |
| Queue wait mean (ms) | 195 |
| Cache-hit rate (eligible) | 99.6% (236/237) |
| Prefix reuse ratio | 88.9% (821019/923849) |
| Recomputed tokens | 102,830 |
| Resumption latency mean (ms) | n/a |
| Prefix-loss events | 1 |

**tool_wait** (n=20 per config)

| Metric | S2 prefix-aware |
|---|---|
| E2E latency mean / p95 (s) | 496.3 / 667.2 |
| TTFT mean / p95 (ms) | 4,303 / 10,821 |
| Prefill mean (ms) | 3,979 |
| Queue wait mean (ms) | 228 |
| Cache-hit rate (eligible) | 98.7% (224/227) |
| Prefix reuse ratio | 87.7% (781171/890590) |
| Recomputed tokens | 109,419 |
| Resumption latency mean (ms) | 4,055 |
| Prefix-loss events | 3 |

**bursty** (n=20 per config)

| Metric | S2 prefix-aware |
|---|---|
| E2E latency mean / p95 (s) | 990.4 / 1,253 |
| TTFT mean / p95 (ms) | 31,486 / 57,874 |
| Prefill mean (ms) | 4,526 |
| Queue wait mean (ms) | 26,729 |
| Cache-hit rate (eligible) | 95.5% (232/243) |
| Prefix reuse ratio | 87.0% (831831/956359) |
| Recomputed tokens | 124,528 |
| Resumption latency mean (ms) | n/a |
| Prefix-loss events | 11 |

**unique_prefix** (n=20 per config)

| Metric | S2 prefix-aware |
|---|---|
| E2E latency mean / p95 (s) | 1,004 / 1,529 |
| TTFT mean / p95 (ms) | 29,795 / 64,766 |
| Prefill mean (ms) | 29,268 |
| Queue wait mean (ms) | 383 |
| Cache-hit rate (eligible) | n/a |
| Prefix reuse ratio | 1.0% (8682/846143) |
| Recomputed tokens | 837,461 |
| Resumption latency mean (ms) | n/a |
| Prefix-loss events | 0 |

![replay_workload_bars](../assets/cluster_one_mac_run1/replay_workload_bars.png)
![replay_latency_cdf](../assets/cluster_one_mac_run1/replay_latency_cdf.png)
![replay_cache](../assets/cluster_one_mac_run1/replay_cache.png)
![replay_slot_utilization](../assets/cluster_one_mac_run1/replay_slot_utilization.png)

### Session-aware cache metrics (Replay)

| Metric | S2 prefix-aware |
|---|---|
| Memory held by finished sessions: mean tokens (sum over servers) | 6,055 |
| Live-session evictions (cache of an unfinished session pushed out of its slot) | 268 |
| ... of which avoidable (a finished session's cache was still resident) | 20 |
| Finished-session caches reused / erased on finish | 218 / 0 |
| Saves to disk / restores (failures) | 0 / 0 (0/0) |
| Mean save / restore time (ms) | n/a / n/a |
| Gateway slot waits (count, total s) | 0 (0.0) |
| Request share per server | w0=62%, w1=38% |
| Router decisions | fallback-least-loaded=59, longest-prefix=1271, spilled-fallback-least-loaded=294, spilled-from-saturated=13 |

Live/avoidable evictions are counted identically in all setups from the slot that served each request; only S3 acts on them. S1/S2 never save, restore or erase.

