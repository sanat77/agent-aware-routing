# Generated tables: cluster_one_mac_run1

## End-to-end agent benchmark

Episodes per config: S1 round-robin=100, S2 prefix-aware=100, S3 prefix+session=100; common episode set = 100

| Metric | S1 round-robin | S2 prefix-aware | S3 prefix+session |
|---|---|---|---|
| 1 Task success rate | 38.0% (38/100) | 30.0% (30/100) | 29.0% (29/100) |
| 2 Hidden test pass rate | 65.0% (7215/11100) | 54.9% (6094/11100) | 58.9% (6539/11100) |
| 3 Regression-free patch rate | 35.0% (35/100) | 28.0% (28/100) | 26.0% (26/100) |
| 4 Tool-call success rate | 93.7% (1108/1183) | 95.3% (1147/1203) | 94.4% (1137/1204) |
| 5 E2E latency p50 / p95 / p99 (s) | 575.0 / 1,588 / 1,760 | 540.7 / 1,313 / 1,534 | 508.4 / 1,655 / 1,728 |
| 6 TTFT p50 / p95 / p99 (ms) | 9,133 / 60,647 / 115,371 | 5,398 / 46,568 / 74,942 | 5,655 / 68,283 / 119,368 |
| 7 Prefill latency mean / p95 (ms) | 9,843 / 35,573 | 7,698 / 36,515 | 8,638 / 42,290 |
| 8 Session-resumption latency mean / p95 (ms) | 8,285 / 25,007 (n=208) | 3,812 / 10,596 (n=218) | 3,270 / 9,749 (n=221) |
| 9 Queue wait mean / p95 (ms) | 8,663 / 45,072 | 5,611 / 33,645 | 7,966 / 44,649 |
| 10 Successful tasks per minute | 0.104 | 0.095 | 0.084 |
| 11 Eligible-request cache-hit rate | 82.2% (916/1114) | 98.8% (1106/1120) | 97.8% (1068/1092) |
| 12 Prefix-cache reuse ratio | 59.1% (2799712/4740054) | 69.7% (3386126/4856671) | 65.1% (3169583/4870955) |
| 13 Recomputed prompt tokens (total) | 1,940,342 | 1,470,545 | 1,701,372 |
| 14 Retention across tool waits (fully retained) | 63.5% (132/208) | 99.5% (217/218) | 99.1% (219/221) |
| 15 Prefix-loss events / slot switches / host-cache saves | 180 / 927 / 1868 | 14 / 511 / 1418 | 24 / 538 / 615 |
| 16 Peak RSS llama / gateway (MiB) | 5,366 / 7 | 5,497 / 7 | 5,081 / 7 |
| 17 Mean slot utilization / KV occupancy est. | 0.60 / 0.21 | 0.67 / 0.20 | 0.63 / 0.16 |
| 18 Slot busy max/mean ; request CV | 1.05 ; 0.09 | 1.06 ; 0.24 | 1.33 ; 0.39 |
| 19 Routing decision (us) mean / gateway overhead (ms) mean | 0.09 / 8.42 | 0.07 / 8.12 | 1,047 / 8.95 |
| 20 Model / tool / episode failure rate | 0.1% (1/1627) / 6.3% (75/1183) / 0.0% (0/100) | 0.0% (0/1637) / 4.7% (56/1203) / 0.0% (0/100) | 0.2% (3/1638) / 5.6% (67/1204) / 0.0% (0/100) |

### Per-workload breakdown

**repeated_prefix** (n=20 per config)

| Metric | S1 round-robin | S2 prefix-aware | S3 prefix+session |
|---|---|---|---|
| Task success | 25.0% (5/20) | 35.0% (7/20) | 30.0% (6/20) |
| E2E latency mean / p95 (s) | 204.8 / 260.8 | 139.0 / 215.3 | 146.1 / 236.7 |
| TTFT mean / p95 (ms) | 4,900 / 10,239 | 2,371 / 6,131 | 2,569 / 6,401 |
| Prefill mean (ms) | 4,871 | 2,347 | 2,547 |
| Queue wait mean (ms) | 0 | 0 | 0 |
| Cache-hit rate (eligible) | 90.2% (220/244) | 100.0% (206/206) | 100.0% (210/210) |
| Prefix reuse ratio | 77.4% (744309/961872) | 88.3% (678357/768456) | 87.8% (718010/817883) |
| Recomputed tokens | 217,563 | 90,099 | 99,873 |
| Resumption latency mean (ms) | n/a | n/a | n/a |
| Prefix-loss events | 20 | 0 | 0 |

**concurrent** (n=20 per config)

| Metric | S1 round-robin | S2 prefix-aware | S3 prefix+session |
|---|---|---|---|
| Task success | 50.0% (10/20) | 25.0% (5/20) | 45.0% (9/20) |
| E2E latency mean / p95 (s) | 458.7 / 837.1 | 453.1 / 701.2 | 378.7 / 604.6 |
| TTFT mean / p95 (ms) | 9,010 / 29,024 | 3,491 / 9,135 | 3,303 / 9,363 |
| Prefill mean (ms) | 6,464 | 3,289 | 3,093 |
| Queue wait mean (ms) | 2,428 | 113 | 139 |
| Cache-hit rate (eligible) | 85.6% (173/202) | 100.0% (237/237) | 100.0% (216/216) |
| Prefix reuse ratio | 77.8% (573355/737394) | 89.5% (827043/923849) | 89.1% (715366/803283) |
| Recomputed tokens | 164,039 | 96,806 | 87,917 |
| Resumption latency mean (ms) | n/a | n/a | n/a |
| Prefix-loss events | 24 | 0 | 0 |

**tool_wait** (n=20 per config)

| Metric | S1 round-robin | S2 prefix-aware | S3 prefix+session |
|---|---|---|---|
| Task success | 40.0% (8/20) | 25.0% (5/20) | 40.0% (8/20) |
| E2E latency mean / p95 (s) | 510.1 / 886.1 | 501.7 / 692.3 | 458.9 / 676.4 |
| TTFT mean / p95 (ms) | 8,260 / 24,754 | 4,122 / 10,783 | 3,742 / 10,062 |
| Prefill mean (ms) | 7,236 | 3,794 | 3,373 |
| Queue wait mean (ms) | 920 | 239 | 243 |
| Cache-hit rate (eligible) | 85.5% (183/214) | 99.1% (225/227) | 99.1% (220/222) |
| Prefix reuse ratio | 77.0% (623399/809590) | 88.3% (786094/890590) | 88.4% (715048/809323) |
| Recomputed tokens | 186,191 | 104,496 | 94,275 |
| Resumption latency mean (ms) | 8,285 | 3,812 | 3,270 |
| Prefix-loss events | 25 | 2 | 2 |

**bursty** (n=20 per config)

| Metric | S1 round-robin | S2 prefix-aware | S3 prefix+session |
|---|---|---|---|
| Task success | 20.0% (4/20) | 35.0% (7/20) | 20.0% (4/20) |
| E2E latency mean / p95 (s) | 1,251 / 1,676 | 998.7 / 1,257 | 1,166 / 1,708 |
| TTFT mean / p95 (ms) | 43,574 / 115,570 | 31,752 / 72,890 | 38,262 / 108,468 |
| Prefill mean (ms) | 9,742 | 4,521 | 6,397 |
| Queue wait mean (ms) | 33,569 | 26,996 | 31,233 |
| Cache-hit rate (eligible) | 79.8% (194/243) | 95.1% (231/243) | 91.0% (213/234) |
| Prefix reuse ratio | 71.0% (662028/932951) | 87.0% (832488/956359) | 81.6% (758449/929339) |
| Recomputed tokens | 270,923 | 123,871 | 170,890 |
| Resumption latency mean (ms) | n/a | n/a | n/a |
| Prefix-loss events | 48 | 12 | 21 |

**unique_prefix** (n=20 per config)

| Metric | S1 round-robin | S2 prefix-aware | S3 prefix+session |
|---|---|---|---|
| Task success | 55.0% (11/20) | 30.0% (6/20) | 10.0% (2/20) |
| E2E latency mean / p95 (s) | 986.3 / 1,375 | 1,006 / 1,537 | 1,298 / 1,722 |
| TTFT mean / p95 (ms) | 34,089 / 74,771 | 29,604 / 63,968 | 40,120 / 91,454 |
| Prefill mean (ms) | 27,739 | 29,014 | 30,642 |
| Queue wait mean (ms) | 6,182 | 442 | 9,263 |
| Cache-hit rate (eligible) | n/a | n/a | n/a |
| Prefix reuse ratio | 0.6% (5109/825575) | 1.0% (8815/846143) | 1.0% (9963/1035925) |
| Recomputed tokens | 820,466 | 837,328 | 1,025,962 |
| Resumption latency mean (ms) | n/a | n/a | n/a |
| Prefix-loss events | 0 | 0 | 0 |

### Paired comparison: S2 prefix-aware vs S1 round-robin

Paired by episode ID against **S1 round-robin**; 95% bootstrap CI over episodes (10,000 resamples).

| Config | Metric | n | candidate mean | baseline mean | difference | 95% CI |
|---|---|---|---|---|---|---|
| S2 prefix-aware | agent_latency_s | 100 | 619.73 | 682.14 | -9.2% * | [-16.0%, -1.6%] |
| S2 prefix-aware | task_success | 100 | 0.30 | 0.38 | -8.0 pp | [-19.0, +4.0] pp |
| S2 prefix-aware | mean_ttft_ms | 100 | 12,833 | 18,078 | -29.0% * | [-35.3%, -22.7%] |
| S2 prefix-aware | sum_prefill_ms | 100 | 126,014 | 160,147 | -21.3% * | [-34.0%, -8.7%] |
| S2 prefix-aware | recomputed_tokens | 100 | 14,705 | 19,403 | -24.2% * | [-35.9%, -12.4%] |
| S2 prefix-aware | mean_queue_ms | 100 | 5,322 | 8,306 | -35.9% * | [-47.8%, -26.2%] |

`*` = 95% CI excludes zero.

### Paired comparison: S3 prefix+session vs S2 prefix-aware

Paired by episode ID against **S2 prefix-aware**; 95% bootstrap CI over episodes (10,000 resamples).

| Config | Metric | n | candidate mean | baseline mean | difference | 95% CI |
|---|---|---|---|---|---|---|
| S3 prefix+session | agent_latency_s | 100 | 689.44 | 619.73 | +11.2% * | [+2.0%, +21.0%] |
| S3 prefix+session | task_success | 100 | 0.29 | 0.30 | -1.0 pp | [-12.0, +10.0] pp |
| S3 prefix+session | mean_ttft_ms | 100 | 15,951 | 12,833 | +24.3% * | [+11.4%, +38.8%] |
| S3 prefix+session | sum_prefill_ms | 100 | 141,490 | 126,014 | +12.3% | [-1.9%, +29.4%] |
| S3 prefix+session | recomputed_tokens | 100 | 17,014 | 14,705 | +15.7% * | [+3.1%, +31.5%] |
| S3 prefix+session | mean_queue_ms | 100 | 7,633 | 5,322 | +43.4% * | [+14.6%, +89.2%] |

`*` = 95% CI excludes zero.

### Paired comparison: S3 prefix+session vs S1 round-robin

Paired by episode ID against **S1 round-robin**; 95% bootstrap CI over episodes (10,000 resamples).

| Config | Metric | n | candidate mean | baseline mean | difference | 95% CI |
|---|---|---|---|---|---|---|
| S3 prefix+session | agent_latency_s | 100 | 689.44 | 682.14 | +1.1% | [-6.3%, +8.9%] |
| S3 prefix+session | task_success | 100 | 0.29 | 0.38 | -9.0 pp | [-20.0, +2.0] pp |
| S3 prefix+session | mean_ttft_ms | 100 | 15,951 | 18,078 | -11.8% * | [-21.2%, -2.2%] |
| S3 prefix+session | sum_prefill_ms | 100 | 141,490 | 160,147 | -11.6% | [-24.0%, +1.1%] |
| S3 prefix+session | recomputed_tokens | 100 | 17,014 | 19,403 | -12.3% * | [-23.3%, -1.6%] |
| S3 prefix+session | mean_queue_ms | 100 | 7,633 | 8,306 | -8.1% | [-26.1%, +12.8%] |

`*` = 95% CI excludes zero.

![e2e_workload_bars](../assets/cluster_one_mac_run1/e2e_workload_bars.png)
![e2e_latency_cdf](../assets/cluster_one_mac_run1/e2e_latency_cdf.png)
![e2e_cache](../assets/cluster_one_mac_run1/e2e_cache.png)
![e2e_slot_utilization](../assets/cluster_one_mac_run1/e2e_slot_utilization.png)

### Session-aware cache metrics (End-to-end)

| Metric | S1 round-robin | S2 prefix-aware | S3 prefix+session |
|---|---|---|---|
| Memory held by finished sessions: mean tokens (sum over servers) | 6,933 | 6,815 | 7 |
| Live-session evictions (cache of an unfinished session pushed out of its slot) | 544 | 260 | 344 |
| ... of which avoidable (a finished session's cache was still resident) | 68 | 21 | 0 |
| Finished-session caches reused / erased on finish | 307 / 0 | 219 / 0 | 31 / 176 |
| Saves to disk / restores (failures) | 0 / 0 (0/0) | 0 / 0 (0/0) | 344 / 288 (31/0) |
| Mean save / restore time (ms) | n/a / n/a | n/a / n/a | 352.9 / 250.5 |
| Gateway slot waits (count, total s) | 0 (0.0) | 0 (0.0) | 360 (12895.3) |
| Request share per server | w0=50%, w1=50% | w0=62%, w1=38% | w0=63%, w1=37% |
| Router decisions | round-robin=1627 | fallback-least-loaded=56, longest-prefix=1280, spilled-fallback-least-loaded=290, spilled-from-saturated=11 | fallback-least-loaded=50, longest-prefix=1284, spilled-fallback-least-loaded=292, spilled-from-saturated=12 |

Live/avoidable evictions are counted identically in all setups from the slot that served each request; only S3 acts on them. S1/S2 never save, restore or erase.

## Controlled trace replay

Episodes per config: S1 round-robin=100, S2 prefix-aware=100, S3 prefix+session=100; common episode set = 100

| Metric | S1 round-robin | S2 prefix-aware | S3 prefix+session |
|---|---|---|---|
| 1-4 Correctness | not measured in replay (agent decisions are fixed) | not measured in replay (agent decisions are fixed) | not measured in replay (agent decisions are fixed) |
| 5 E2E latency p50 / p95 / p99 (s) | 645.9 / 1,609 / 1,695 | 545.9 / 1,295 / 1,527 | 539.7 / 1,455 / 1,527 |
| 6 TTFT p50 / p95 / p99 (ms) | 9,560 / 70,215 / 104,012 | 5,505 / 46,791 / 67,616 | 5,472 / 54,972 / 102,206 |
| 7 Prefill latency mean / p95 (ms) | 10,280 / 39,723 | 7,771 / 38,032 | 7,900 / 37,867 |
| 8 Session-resumption latency mean / p95 (ms) | 9,174 / 28,311 (n=218) | 4,055 / 10,847 (n=218) | 3,725 / 10,383 (n=218) |
| 9 Queue wait mean / p95 (ms) | 9,428 / 53,100 | 5,548 / 34,704 | 6,286 / 41,145 |
| 10 Sessions per minute | 0.279 | 0.317 | 0.317 |
| 11 Eligible-request cache-hit rate | 80.4% (901/1120) | 98.6% (1104/1120) | 98.2% (1100/1120) |
| 12 Prefix-cache reuse ratio | 58.4% (2837451/4856671) | 69.4% (3372428/4856671) | 68.4% (3322760/4856671) |
| 13 Recomputed prompt tokens (total) | 2,019,220 | 1,484,243 | 1,533,911 |
| 14 Retention across tool waits (fully retained) | 66.5% (145/218) | 99.1% (216/218) | 100.0% (218/218) |
| 15 Prefix-loss events / slot switches / host-cache saves | 195 / 972 / 1845 | 16 / 520 / 1427 | 20 / 478 / 522 |
| 16 Peak RSS llama / gateway (MiB) | 5,289 / 6 | 5,262 / 7 | 5,779 / 7 |
| 17 Mean slot utilization / KV occupancy est. | 0.64 / 0.21 | 0.68 / 0.19 | 0.68 / 0.15 |
| 18 Slot busy max/mean ; request CV | 1.02 ; 0.01 | 1.06 ; 0.23 | 1.23 ; 0.34 |
| 19 Routing decision (us) mean / gateway overhead (ms) mean | 0.10 / 10.24 | 0.08 / 9.92 | 1,052 / 11.01 |
| 20 Model / tool / episode failure rate | 0.0% (0/1637) / n/a / 0.0% (0/100) | 0.0% (0/1637) / n/a / 0.0% (0/100) | 0.0% (0/1637) / n/a / 0.0% (0/100) |

### Per-workload breakdown

**repeated_prefix** (n=20 per config)

| Metric | S1 round-robin | S2 prefix-aware | S3 prefix+session |
|---|---|---|---|
| E2E latency mean / p95 (s) | 171.7 / 258.9 | 138.1 / 214.7 | 138.9 / 217.9 |
| TTFT mean / p95 (ms) | 4,856 / 10,778 | 2,360 / 6,114 | 2,437 / 6,170 |
| Prefill mean (ms) | 4,819 | 2,329 | 2,408 |
| Queue wait mean (ms) | 1 | 0 | 0 |
| Cache-hit rate (eligible) | 87.9% (181/206) | 100.0% (206/206) | 100.0% (206/206) |
| Prefix reuse ratio | 75.2% (578125/768456) | 88.3% (678357/768456) | 87.7% (673614/768456) |
| Recomputed tokens | 190,331 | 90,099 | 94,842 |
| Resumption latency mean (ms) | n/a | n/a | n/a |
| Prefix-loss events | 20 | 0 | 0 |

**concurrent** (n=20 per config)

| Metric | S1 round-robin | S2 prefix-aware | S3 prefix+session |
|---|---|---|---|
| E2E latency mean / p95 (s) | 554.1 / 822.7 | 438.3 / 665.7 | 447.3 / 686.2 |
| TTFT mean / p95 (ms) | 10,248 / 36,128 | 3,772 / 9,482 | 3,655 / 9,758 |
| Prefill mean (ms) | 7,089 | 3,483 | 3,431 |
| Queue wait mean (ms) | 3,026 | 195 | 122 |
| Cache-hit rate (eligible) | 87.8% (208/237) | 99.6% (236/237) | 100.0% (237/237) |
| Prefix reuse ratio | 77.7% (717765/923849) | 88.9% (821019/923849) | 88.9% (821199/923849) |
| Recomputed tokens | 206,084 | 102,830 | 102,650 |
| Resumption latency mean (ms) | n/a | n/a | n/a |
| Prefix-loss events | 26 | 1 | 0 |

**tool_wait** (n=20 per config)

| Metric | S1 round-robin | S2 prefix-aware | S3 prefix+session |
|---|---|---|---|
| E2E latency mean / p95 (s) | 576.2 / 803.0 | 496.3 / 667.2 | 489.5 / 666.2 |
| TTFT mean / p95 (ms) | 9,080 / 27,676 | 4,303 / 10,821 | 4,080 / 10,390 |
| Prefill mean (ms) | 6,946 | 3,979 | 3,695 |
| Queue wait mean (ms) | 2,012 | 228 | 298 |
| Cache-hit rate (eligible) | 85.0% (193/227) | 98.7% (224/227) | 100.0% (227/227) |
| Prefix reuse ratio | 77.2% (687121/890590) | 87.7% (781171/890590) | 88.0% (783720/890590) |
| Recomputed tokens | 203,469 | 109,419 | 106,870 |
| Resumption latency mean (ms) | 9,174 | 4,055 | 3,725 |
| Prefix-loss events | 26 | 3 | 0 |

**bursty** (n=20 per config)

| Metric | S1 round-robin | S2 prefix-aware | S3 prefix+session |
|---|---|---|---|
| E2E latency mean / p95 (s) | 1,307 / 1,699 | 990.4 / 1,253 | 1,101 / 1,484 |
| TTFT mean / p95 (ms) | 45,626 / 99,713 | 31,486 / 57,874 | 36,233 / 100,773 |
| Prefill mean (ms) | 10,019 | 4,526 | 6,059 |
| Queue wait mean (ms) | 35,342 | 26,729 | 29,599 |
| Cache-hit rate (eligible) | 75.3% (183/243) | 95.5% (232/243) | 93.0% (226/243) |
| Prefix reuse ratio | 70.7% (676330/956359) | 87.0% (831831/956359) | 82.7% (791022/956359) |
| Recomputed tokens | 280,029 | 124,528 | 165,337 |
| Resumption latency mean (ms) | n/a | n/a | n/a |
| Prefix-loss events | 57 | 11 | 17 |

**unique_prefix** (n=20 per config)

| Metric | S1 round-robin | S2 prefix-aware | S3 prefix+session |
|---|---|---|---|
| E2E latency mean / p95 (s) | 1,036 / 1,509 | 1,004 / 1,529 | 1,001 / 1,513 |
| TTFT mean / p95 (ms) | 35,847 / 79,693 | 29,795 / 64,766 | 29,657 / 63,710 |
| Prefill mean (ms) | 28,994 | 29,268 | 28,910 |
| Queue wait mean (ms) | 6,640 | 383 | 591 |
| Cache-hit rate (eligible) | n/a | n/a | n/a |
| Prefix reuse ratio | 0.6% (5135/846143) | 1.0% (8682/846143) | 1.0% (8827/846143) |
| Recomputed tokens | 841,008 | 837,461 | 837,316 |
| Resumption latency mean (ms) | n/a | n/a | n/a |
| Prefix-loss events | 0 | 0 | 0 |

### Paired comparison: S2 prefix-aware vs S1 round-robin

Paired by episode ID against **S1 round-robin**; 95% bootstrap CI over episodes (10,000 resamples).

| Config | Metric | n | candidate mean | baseline mean | difference | 95% CI |
|---|---|---|---|---|---|---|
| S2 prefix-aware | session_latency_s | 100 | 613.40 | 729.07 | -15.9% * | [-18.8%, -12.9%] |
| S2 prefix-aware | mean_ttft_ms | 100 | 12,883 | 19,139 | -32.7% * | [-37.2%, -28.4%] |
| S2 prefix-aware | sum_prefill_ms | 100 | 127,137 | 168,283 | -24.5% * | [-32.0%, -17.9%] |
| S2 prefix-aware | recomputed_tokens | 100 | 14,832 | 20,192 | -26.5% * | [-33.6%, -20.7%] |
| S2 prefix-aware | mean_queue_ms | 100 | 5,303 | 9,067 | -41.5% * | [-52.0%, -33.2%] |

`*` = 95% CI excludes zero.

### Paired comparison: S3 prefix+session vs S2 prefix-aware

Paired by episode ID against **S2 prefix-aware**; 95% bootstrap CI over episodes (10,000 resamples).

| Config | Metric | n | candidate mean | baseline mean | difference | 95% CI |
|---|---|---|---|---|---|---|
| S3 prefix+session | session_latency_s | 100 | 635.47 | 613.40 | +3.6% * | [+1.0%, +6.5%] |
| S3 prefix+session | mean_ttft_ms | 100 | 13,860 | 12,883 | +7.6% * | [+0.9%, +15.2%] |
| S3 prefix+session | sum_prefill_ms | 100 | 129,326 | 127,137 | +1.7% | [-3.1%, +7.1%] |
| S3 prefix+session | recomputed_tokens | 100 | 15,339 | 14,832 | +3.4% * | [+0.6%, +7.3%] |
| S3 prefix+session | mean_queue_ms | 100 | 6,102 | 5,303 | +15.1% * | [+0.8%, +33.0%] |

`*` = 95% CI excludes zero.

### Paired comparison: S3 prefix+session vs S1 round-robin

Paired by episode ID against **S1 round-robin**; 95% bootstrap CI over episodes (10,000 resamples).

| Config | Metric | n | candidate mean | baseline mean | difference | 95% CI |
|---|---|---|---|---|---|---|
| S3 prefix+session | session_latency_s | 100 | 635.47 | 729.07 | -12.8% * | [-15.7%, -9.9%] |
| S3 prefix+session | mean_ttft_ms | 100 | 13,860 | 19,139 | -27.6% * | [-33.5%, -21.9%] |
| S3 prefix+session | sum_prefill_ms | 100 | 129,326 | 168,283 | -23.1% * | [-30.1%, -17.3%] |
| S3 prefix+session | recomputed_tokens | 100 | 15,339 | 20,192 | -24.0% * | [-30.6%, -18.7%] |
| S3 prefix+session | mean_queue_ms | 100 | 6,102 | 9,067 | -32.7% * | [-46.1%, -21.1%] |

`*` = 95% CI excludes zero.

![replay_workload_bars](../assets/cluster_one_mac_run1/replay_workload_bars.png)
![replay_latency_cdf](../assets/cluster_one_mac_run1/replay_latency_cdf.png)
![replay_cache](../assets/cluster_one_mac_run1/replay_cache.png)
![replay_slot_utilization](../assets/cluster_one_mac_run1/replay_slot_utilization.png)

### Session-aware cache metrics (Replay)

| Metric | S1 round-robin | S2 prefix-aware | S3 prefix+session |
|---|---|---|---|
| Memory held by finished sessions: mean tokens (sum over servers) | 6,957 | 6,055 | 371 |
| Live-session evictions (cache of an unfinished session pushed out of its slot) | 585 | 268 | 268 |
| ... of which avoidable (a finished session's cache was still resident) | 87 | 20 | 0 |
| Finished-session caches reused / erased on finish | 313 / 0 | 218 / 0 | 39 / 180 |
| Saves to disk / restores (failures) | 0 / 0 (0/0) | 0 / 0 (0/0) | 272 / 226 (28/0) |
| Mean save / restore time (ms) | n/a / n/a | n/a / n/a | 360.8 / 248.8 |
| Gateway slot waits (count, total s) | 0 (0.0) | 0 (0.0) | 283 (9873.3) |
| Request share per server | w0=50%, w1=50% | w0=62%, w1=38% | w0=62%, w1=38% |
| Router decisions | round-robin=1637 | fallback-least-loaded=59, longest-prefix=1271, spilled-fallback-least-loaded=294, spilled-from-saturated=13 | fallback-least-loaded=56, longest-prefix=1281, spilled-fallback-least-loaded=291, spilled-from-saturated=9 |

Live/avoidable evictions are counted identically in all setups from the slot that served each request; only S3 acts on them. S1/S2 never save, restore or erase.

