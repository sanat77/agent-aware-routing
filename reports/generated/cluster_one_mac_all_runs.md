# All runs: one_mac

Each run is a separate result set (`results/cluster/one_mac/<run>/`). Rows are per run; the last row of each block is the mean and standard deviation across runs.

## End-to-end (real agents)

**S1 round-robin**

| run | episodes | bug-fix rate | mean latency (s) | mean TTFT (ms) | prefix reuse | recomputed tokens / episode |
|---|---|---|---|---|---|---|
| run1 | 100 | 0.380 | 682.1 | 18,641 | 0.591 | 19,403 |

**S2 prefix-aware**

| run | episodes | bug-fix rate | mean latency (s) | mean TTFT (ms) | prefix reuse | recomputed tokens / episode |
|---|---|---|---|---|---|---|
| run1 | 100 | 0.300 | 619.7 | 13,427 | 0.697 | 14,705 |

**S3 prefix+session**

| run | episodes | bug-fix rate | mean latency (s) | mean TTFT (ms) | prefix reuse | recomputed tokens / episode |
|---|---|---|---|---|---|---|
| run1 | 100 | 0.290 | 689.4 | 16,815 | 0.651 | 17,014 |

## Trace replay (same requests)

**S1 round-robin**

| run | episodes | mean latency (s) | mean TTFT (ms) | prefix reuse | recomputed tokens / episode |
|---|---|---|---|---|---|
| run1 | 100 | 729.1 | 19,862 | 0.584 | 20,192 |

**S2 prefix-aware**

| run | episodes | mean latency (s) | mean TTFT (ms) | prefix reuse | recomputed tokens / episode |
|---|---|---|---|---|---|
| run1 | 100 | 613.4 | 13,439 | 0.694 | 14,842 |

**S3 prefix+session**

| run | episodes | mean latency (s) | mean TTFT (ms) | prefix reuse | recomputed tokens / episode |
|---|---|---|---|---|---|
| run1 | 100 | 635.5 | 14,383 | 0.684 | 15,339 |

