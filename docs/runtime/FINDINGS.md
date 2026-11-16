# llama.cpp runtime capability findings (verified empirically)

Runtime: Homebrew `llama-server` build b11669 (commit 620d2225c). Full `--help` output: `llama-server-help.txt`.
Raw probe outputs: `api_probe.json`, `cache_probe.json`. Probe scripts: `scripts/probe_*.py`.
The probes below were run with Qwen2.5-Coder-3B. The frozen model is Qwen3-4B-Instruct-2507 (see "Model selection").

## Model selection

| Candidate (Q4_K_M) | file | prefill tok/s | decode tok/s | KV per token (f16) | trial episodes fixed |
|---|---:|---:|---:|---:|---:|
| Qwen2.5-Coder-1.5B-Instruct | 1.12 GB | 597 | 47 | 28 KB | not tried (weaker than 3B) |
| Qwen2.5-Coder-3B-Instruct | 2.10 GB | 288 | 26 | 36 KB | 0 of 8 (loops; could not produce valid patches) |
| **Qwen3-4B-Instruct-2507** | 2.50 GB | 208 | 19.7 | 144 KB | 3 of 8 |

Qwen3-4B has 8 KV heads, so its KV cache is about 4x larger per token. The frozen configuration uses a q8_0 KV cache
(`-ctk q8_0 -ctv q8_0`), which measured at the same prefill speed (209.7 tok/s at 2,048 tokens) and fits
4 slots x 8,192 tokens. Peak llama-server RSS in the smoke run was 6.9 GB including the 4 GB host prompt cache.

| Capability | Verified | How |
|---|---|---|
| Per-request slot pinning (`id_slot`) | yes | `/completion` and `/v1/chat/completions` honour `id_slot`; log line `selected slot by id` |
| Per-request prompt cache toggle (`cache_prompt`) | yes | `cache_prompt=false` → `timings.cache_n = 0` |
| Server-wide prompt cache toggle | yes | `--no-cache-prompt` |
| Reused-token count per request | yes | `timings.cache_n`, `timings.prompt_n`, `timings.prompt_ms` |
| Slot that served the request | yes (`/completion` only) | final stream chunk field `id_slot` (chat endpoint does not return it) |
| Default slot selection | yes | log: `selected slot by LCP similarity` (threshold `--slot-prompt-similarity`, default 0.10) else `selected slot by LRU` |
| Host-RAM prompt cache | yes | `--cache-ram N` MiB (default 8192). Idle slot state is saved on new task (`saving idle slot to prompt cache`) and restored into any slot; capacity is also bounded by a token limit equal to `n_ctx` (log: `limits: 8192.000 MiB, 16384 tokens`) |
| Cache bytes | yes (logs at `-lv 4`) | `prompt_save: - saving prompt with length N, total state size = X MiB`, `cache state: K prompts, Y MiB` |
| Slot state introspection | partial | `GET /slots`: `id`, `is_processing`, `n_ctx`, `id_task`, `n_prompt_tokens`; no prompt text |
| Prometheus metrics | yes | `--metrics`: `prompt_tokens_total`, `prompt_tokens_cached_total`, `requests_processing`, `requests_deferred`, ... (no KV-cells-used gauge in this build) |
| Slot save/restore/erase to disk | exists, not used | `POST /slots/{id}?action=...` requires `--slot-save-path` |
| Grammar / JSON-schema constrained output | yes | `json_schema` field on `/completion` |
| KV usage % gauge | **not exposed** in this build | KV utilisation is therefore reported as *estimated* from slot token counts, and labelled as such |

Consequences for the experiment design:

* Baseline A (no cache) = `--no-cache-prompt --cache-ram 0` **and** `cache_prompt=false` per request.
* Baseline B (native) = defaults: LCP/LRU slot selection + host-RAM prompt cache.
* Baseline C (affinity) and Candidate D (Rust policy) steer requests only via `id_slot`. KV tensors stay inside llama.cpp; nothing moves them except llama.cpp's own prompt cache.
* Because the host-RAM prompt cache restores evicted prefixes cheaply (a ~820-token prefix restored with `prompt_ms` ≈ 38 ms vs 2830 ms recompute), native caching is a strong baseline. Routing can only win where that cache is exceeded or where slot choice changes queueing.
