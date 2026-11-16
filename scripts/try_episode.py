"""Developer helper: run single episodes against an already-running stack (python -m bench.stack start ...).

Usage: python scripts/try_episode.py <category> <variation> [<category> <variation> ...]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.session import run_episode  # noqa: E402
from faultlab.injector import episode_spec  # noqa: E402

args = sys.argv[1:]
for cat, v in zip(args[::2], args[1::2]):
    spec = episode_spec(cat, int(v))
    ep = {**spec, "episode_id": f"try-{cat}-{v}", "session_id": f"try-{cat}-{v}", "workload": "dev",
          "tool_delays_s": [], "prompt_nonce": "x"}
    res = run_episode(ep, out_dir="/tmp/try_runs", gateway_url="http://127.0.0.1:8080", run_id="try",
                      config_name="dev", workspace_root="/tmp/try_ws",
                      options={"max_steps": 15, "n_predict": 512, "ctx_tokens": 8192})
    print(json.dumps({k: res[k] for k in ("episode_id", "status", "outcome", "model_calls", "tool_calls",
                                          "agent_latency_s", "input_tokens", "cached_tokens", "output_tokens")}))
    print("  eval:", {k: res["evaluation"][k] for k in ("task_success", "regression_free", "hidden_tests_passed",
                                                        "hidden_tests_total")})
    for c in res["calls"]:
        print(f"   step {c['step']} slot={c['served_slot']} prompt_n={c['prompt_n']} cache_n={c['cache_n']} "
              f"pred={c['predicted_n']} lat={c['client_latency_ms']:.0f}ms")
    print("  diff:", res["diff"][:800])
