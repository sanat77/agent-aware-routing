"""Controlled trace replay: re-send recorded agent inference requests under a different routing configuration.

What is held fixed: serialized prompts (byte-identical), n_predict, JSON schema, temperature 0, session ids,
manifest arrival schedule and concurrency, and each session's recorded inter-request gaps (tool execution +
tool-delay schedule). The model still performs real inference for every request.
What is NOT replayed: agent decisions. The agent does not run; therefore task correctness is not measured here.

Usage:
  python -m bench.replay --config session_affinity --traces results/baseline/native_cache/e2e --tiers 0,1
"""
import argparse
import gzip
import json
import threading
import time
from pathlib import Path

import httpx

from agent.prompts import ACTION_SCHEMA, ACTION_SCHEMA_SHA

from . import stack
from .manifest import load
from .monitor import Monitor
from .provenance import write_run_json
from .run_e2e import groups_in_order

ROOT = Path(__file__).resolve().parents[1]


def load_trace(trace_root, episode_id):
    for p in Path(trace_root).glob(f"*/traces/{episode_id}.jsonl.gz"):
        with gzip.open(p, "rt") as f:
            return [json.loads(l) for l in f]
    return None


def replay_session(ep, trace, *, gateway, out, lock, scheduled_start, repeat_tag):
    client = httpx.Client(timeout=httpx.Timeout(900.0, connect=10.0))
    sid = ep["session_id"]
    t_start = time.time()

    def event(name, **kw):
        try:
            client.post(f"{gateway}/v1/sessions/{sid}/events", json={"event": name, **kw}, timeout=5)
        except httpx.HTTPError:
            pass

    event("session_start", episode_id=ep["episode_id"], workload=ep["workload"], replay=True)
    records = []
    last_resp = None
    errors = 0
    for i, req in enumerate(trace):
        if req.get("schema_sha") != ACTION_SCHEMA_SHA:
            raise RuntimeError("trace was recorded with a different action schema")
        if i == 0:
            wait_until = t_start + max(0.0, req["sent_offset_s"])
            time.sleep(max(0.0, wait_until - time.time()))
        else:
            gap = max(0.0, req.get("gap_since_prev_response_s") or 0.0)
            tool_wait = min(gap, req.get("tool_wait_before_s") or 0.0)
            time.sleep(max(0.0, gap - tool_wait))  # tool execution time
            if tool_wait > 0:
                event("tool_wait_start", expected_wait_ms=tool_wait * 1000, mode="replay")
                time.sleep(tool_wait)
                event("tool_wait_end", waited_ms=tool_wait * 1000)
        body = {"prompt": req["prompt"], "n_predict": req["n_predict"], "temperature": 0.0, "top_k": 1,
                "seed": 1234, "cache_prompt": True, "json_schema": ACTION_SCHEMA}
        headers = {"x-session-id": sid, "x-request-id": f"{req['request_id']}-rp{repeat_tag}",
                   "x-episode-id": ep["episode_id"], "x-step": str(req["step"])}
        t0 = time.time()
        try:
            r = client.post(f"{gateway}/completion", json=body, headers=headers)
            data = r.json()
            ok = r.status_code == 200 and bool(data.get("timings"))
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            data, ok = {"error": repr(exc)}, False
        t1 = time.time()
        last_resp = t1
        errors += 0 if ok else 1
        timings = data.get("timings") or {}
        gw = data.get("gateway") or {}
        records.append({
            "step": req["step"], "request_id": headers["x-request-id"], "ok": ok, "latency_ms": (t1 - t0) * 1000,
            "served_slot": data.get("id_slot"), "prompt_n": timings.get("prompt_n"), "cache_n": timings.get("cache_n"),
            "prompt_ms": timings.get("prompt_ms"), "predicted_n": timings.get("predicted_n"),
            "predicted_ms": timings.get("predicted_ms"), "ttft_ms": gw.get("ttft_ms"),
            "gateway_queue_ms": gw.get("gateway_queue_ms"), "est_upstream_queue_ms": gw.get("est_upstream_queue_ms"),
            "routing_decision_us": gw.get("routing_decision_us"), "decision_reason": gw.get("decision_reason"),
            "tool_wait_before_s": req.get("tool_wait_before_s") or 0.0,
            "recorded_prompt_tokens": req.get("recorded_prompt_tokens"),
            "output_matches_recording": data.get("content") == req.get("recorded_content"),
        })
    event("completed", outcome="replay_done")
    res = {"episode_id": ep["episode_id"], "session_id": sid, "workload": ep["workload"],
           "bug_category": ep["bug_category"], "scheduled_start": scheduled_start, "started_at": t_start,
           "session_wait_s": max(0.0, t_start - scheduled_start), "session_latency_s": (last_resp or t_start) - t_start,
           "requests": len(records), "request_errors": errors, "records": records}
    with lock:
        with open(out / "replay_sessions.jsonl", "a") as f:
            f.write(json.dumps(res) + "\n")
    client.close()
    return res


def run(config, trace_root, episodes, out, policy=None, gateway_extra=(), repeat_tag="0"):
    out.mkdir(parents=True, exist_ok=True)
    done = set()
    if (out / "replay_sessions.jsonl").exists():
        done = {json.loads(l)["episode_id"] for l in (out / "replay_sessions.jsonl").read_text().splitlines()}
    traces = {e["episode_id"]: load_trace(trace_root, e["episode_id"]) for e in episodes}
    missing = [k for k, v in traces.items() if not v]
    episodes = [e for e in episodes if traces.get(e["episode_id"])]
    if episodes and {e["episode_id"] for e in episodes} <= done and (out / "run.json").exists():
        print(f"[replay {config} {out.name}] all {len(episodes)} sessions already complete; skipping", flush=True)
        return json.loads((out / "run.json").read_text())
    info = stack.start(config, out / "logs", run_id=f"{config}-replay-{out.name}", policy_override=policy,
                       gateway_extra=gateway_extra)
    mon = Monitor(out / "logs", info["llama_url"], {"llama": info["llama_pid"], "gateway": info["gateway_pid"]}).start()
    lock = threading.Lock()
    t_run = time.time()
    n = [len(done)]
    status = "interrupted"
    try:
        for group in groups_in_order(episodes):
            todo = [e for e in group if e["episode_id"] not in done]
            if not todo:
                continue
            conc = max(1, min(group[0]["concurrency"], len(group)))
            if group[0]["arrival_rule"] == "closed_loop":
                for e in todo:
                    replay_session(e, traces[e["episode_id"]], gateway=info["gateway_url"], out=out, lock=lock,
                                   scheduled_start=time.time(), repeat_tag=repeat_tag)
                    n[0] += 1
                continue
            sem = threading.Semaphore(conc)
            t0 = time.time() + 0.5

            def worker(e):
                sched = t0 + e["arrival_offset_s"]
                time.sleep(max(0.0, sched - time.time()))
                with sem:
                    replay_session(e, traces[e["episode_id"]], gateway=info["gateway_url"], out=out, lock=lock,
                                   scheduled_start=sched, repeat_tag=repeat_tag)
                n[0] += 1

            threads = [threading.Thread(target=worker, args=(e,)) for e in todo]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            print(f"[replay {config} {out.name}] {n[0]}/{len(episodes)} sessions", flush=True)
        status = "complete"
    finally:
        mon.stop()
        stack.stop()
        meta = {"config": config, "policy": policy or stack.EXPERIMENTS["configs"][config]["gateway_policy"],
                "trace_root": str(trace_root), "episodes": len(episodes), "missing_traces": missing,
                "status": status, "stack": info, "peak_rss_bytes": mon.peak_rss, "repeat_tag": repeat_tag,
                "manifest_sha256": json.loads((ROOT / "manifests" / "master_manifest.meta.json").read_text())["sha256"]}
        meta = write_run_json(out / "run.json", meta, time.time() - t_run)
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--traces", required=True, help="e2e dir containing tier*/traces/*.jsonl.gz")
    ap.add_argument("--tiers", default="0")
    ap.add_argument("--episodes", default=None, help="comma list of episode ids (subset / repetitions)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--policy", default=None)
    ap.add_argument("--repeat-tag", default="0")
    ap.add_argument("--gateway-arg", action="append", default=[])
    args = ap.parse_args()
    manifest = load()
    cfg = stack.EXPERIMENTS["configs"][args.config]
    if args.episodes:
        ids = set(args.episodes.split(","))
        selections = [(f"subset_r{args.repeat_tag}", [e for e in manifest if e["episode_id"] in ids])]
    else:
        selections = [(f"tier{t}", [e for e in manifest if e["tier"] == int(t)]) for t in args.tiers.split(",")]
    for label, eps in selections:
        out = Path(args.out) / label if args.out else ROOT / cfg["results_dir"] / "replay" / label
        meta = run(args.config, Path(args.traces), eps, out, policy=args.policy,
                   gateway_extra=args.gateway_arg, repeat_tag=args.repeat_tag)
        print(json.dumps({k: meta[k] for k in ("config", "episodes", "wall_s", "missing_traces")}))


if __name__ == "__main__":
    main()
