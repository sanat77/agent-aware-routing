"""Trace replay through llm-router + gateways (setups S1-S3).

Replays the multi-agent traces recorded by the end-to-end recording run (setup S2 by default): every request's
chat messages, JSON schema, n_predict, session id (lead or helper), parent session and role, and the recorded
gaps between requests (tool execution + scheduled tool delays). Lifecycle events are re-sent the way the agent
sent them: tool waits for the lead, `completed` for each helper after its last request and for the lead at the
end. The model performs real inference for every request; agent decisions are fixed, so correctness is not
measured here.

Usage: python -m bench.cluster_replay --setup S3 --tiers 0 [--profile one_mac]
"""
import argparse
import gzip
import json
import threading
import time
from pathlib import Path

from agent.llm import GatewayClient, ModelCallError
from agent.prompts import SCHEMA_SHAS, SCHEMAS
from agent.session import ABORT

from . import cluster
from .cluster_run import setup_dir, stack_meta, start_monitors
from .manifest import load
from .provenance import install_termination_handler, write_run_json
from .run_e2e import groups_in_order
from .util import say

ROOT = Path(__file__).resolve().parents[1]


def load_trace(trace_root, episode_id):
    for p in Path(trace_root).glob(f"*/traces/{episode_id}.jsonl.gz"):
        with gzip.open(p, "rt") as f:
            return [json.loads(l) for l in f]
    return None


def replay_session(ep, trace, *, router_url, out, lock, scheduled_start, tag):
    client = GatewayClient(router_url, api="chat", max_retries=1)
    lead = ep["session_id"]
    last_index = {}
    for i, req in enumerate(trace):
        last_index[req["session_id"]] = i
    t_start = time.time()
    records, errors = [], 0
    last_resp = None
    for i, req in enumerate(trace):
        if req.get("schema_sha") != SCHEMA_SHAS.get(req.get("schema")):
            raise RuntimeError("trace was recorded with a different JSON schema")
        if i == 0:
            time.sleep(max(0.0, t_start + max(0.0, req["sent_offset_s"]) - time.time()))
        else:
            gap = max(0.0, req.get("gap_since_prev_response_s") or 0.0)
            tool_wait = min(gap, req.get("tool_wait_before_s") or 0.0)
            time.sleep(max(0.0, gap - tool_wait))
            if tool_wait > 0:
                client.event(lead, "tool_wait_start", expected_wait_ms=tool_wait * 1000, mode="replay",
                             agent_role=req.get("role"))
                time.sleep(tool_wait)
                client.event(lead, "tool_wait_end", waited_ms=tool_wait * 1000, agent_role=req.get("role"))
        t0 = time.time()
        try:
            data = client.complete(messages=req["messages"], session_id=req["session_id"],
                                   episode_id=ep["episode_id"], step=req["step"], n_predict=req["n_predict"],
                                   json_schema=SCHEMAS[req["schema"]], request_id=f"{req['request_id']}-rp{tag}",
                                   parent_session_id=req.get("parent_session_id"), agent_role=req.get("role"))
            ok = True
        except ModelCallError as exc:
            data, ok = {"error": str(exc)}, False
        t1 = time.time()
        last_resp = t1
        errors += 0 if ok else 1
        timings = data.get("timings") or {}
        gw = data.get("gateway") or {}
        records.append({
            "step": req["step"], "request_id": f"{req['request_id']}-rp{tag}", "session_id": req["session_id"],
            "role": req.get("role"), "ok": ok, "latency_ms": (t1 - t0) * 1000, "server_id": gw.get("server_id"),
            "served_slot": data.get("id_slot"), "prompt_n": timings.get("prompt_n"), "cache_n": timings.get("cache_n"),
            "prompt_ms": timings.get("prompt_ms"), "predicted_n": timings.get("predicted_n"),
            "predicted_ms": timings.get("predicted_ms"), "ttft_ms": gw.get("ttft_ms"),
            "gateway_queue_ms": gw.get("gateway_queue_ms"), "est_upstream_queue_ms": gw.get("est_upstream_queue_ms"),
            "routing_decision_us": gw.get("routing_decision_us"), "decision_reason": gw.get("decision_reason"),
            "router_reason": data.get("router_reason"), "restored": gw.get("restored"),
            "tool_wait_before_s": req.get("tool_wait_before_s") or 0.0,
            "recorded_prompt_tokens": req.get("recorded_prompt_tokens"),
            "output_matches_recording": data.get("content") == req.get("recorded_content"),
        })
        if req["session_id"] != lead and last_index[req["session_id"]] == i:
            client.event(req["session_id"], "completed", agent_role=req.get("role"), outcome="replay_done")
    client.event(lead, "completed", outcome="replay_done")
    res = {"episode_id": ep["episode_id"], "session_id": lead, "workload": ep["workload"],
           "bug_category": ep["bug_category"], "scheduled_start": scheduled_start, "started_at": t_start,
           "session_wait_s": max(0.0, t_start - scheduled_start), "session_latency_s": (last_resp or t_start) - t_start,
           "requests": len(records), "request_errors": errors,
           "helper_sessions": sorted({r["session_id"] for r in records if r["session_id"] != lead}),
           "records": records}
    with lock:
        if not ABORT.is_set():
            with open(out / "replay_sessions.jsonl", "a") as f:
                f.write(json.dumps(res) + "\n")
    client.close()
    return res


def run(setup, profile, trace_root, episodes, out, tag="0", allow_missing=False, run_name="run1"):
    traces = {e["episode_id"]: load_trace(trace_root, e["episode_id"]) for e in episodes}
    missing = [k for k, v in traces.items() if not v]
    if missing and not allow_missing:
        raise SystemExit(f"[replay {setup} {out.name}] {len(missing)} recorded traces missing under {trace_root} "
                         f"(e.g. {missing[:3]}); run the recording step first, or pass --allow-missing")
    out.mkdir(parents=True, exist_ok=True)
    done = set()
    if (out / "replay_sessions.jsonl").exists():
        for line in (out / "replay_sessions.jsonl").read_text().splitlines():
            try:
                done.add(json.loads(line)["episode_id"])
            except (json.JSONDecodeError, KeyError):
                continue
    episodes = [e for e in episodes if traces.get(e["episode_id"])]
    if episodes and {e["episode_id"] for e in episodes} <= done and (out / "run.json").exists():
        say(f"[replay {setup} {out.name}] all {len(episodes)} sessions already complete; skipping")
        return json.loads((out / "run.json").read_text())
    run_id = f"cluster-{profile}-{run_name}-{setup}-replay-{out.name}"
    info = cluster.start(setup, out / "logs", run_id=run_id, profile=profile)
    mons = start_monitors(out, info)
    lock = threading.RLock()
    t_run = time.time()
    n = [len(done)]
    finalized = []

    def finalize(status):
        if finalized:
            return finalized[0]
        for m in mons:
            m.stop()
        try:
            (out / "logs" / "final_stats.json").write_text(json.dumps(cluster.collect_stats(info), indent=1))
        except Exception as exc:  # noqa: BLE001 - never lose run.json because stats collection failed
            say(f"final stats collection failed: {exc!r}")
        cluster.stop()
        stack, peak = stack_meta(info, mons)
        meta = {"run": run_name, "setup": setup, "profile": profile, "trace_root": str(trace_root), "episodes": len(episodes),
                "missing_traces": missing, "status": status, "stack": stack, "peak_rss_bytes": peak, "repeat_tag": tag,
                "manifest_sha256": json.loads((ROOT / "manifests" / "master_manifest.meta.json").read_text())["sha256"]}
        finalized.append(write_run_json(out / "run.json", meta, time.time() - t_run))
        return finalized[0]

    def abort_and_finalize(status):
        with lock:
            ABORT.set()
        return finalize(status)

    install_termination_handler(abort_and_finalize)
    try:
        for group in groups_in_order(episodes):
            todo = [e for e in group if e["episode_id"] not in done]
            if not todo:
                continue
            conc = max(1, min(group[0]["concurrency"], len(group)))
            if group[0]["arrival_rule"] == "closed_loop":
                for e in todo:
                    replay_session(e, traces[e["episode_id"]], router_url=info["router_url"], out=out, lock=lock,
                                   scheduled_start=time.time(), tag=tag)
                    n[0] += 1
                continue
            sem = threading.Semaphore(conc)
            t0 = time.time() + 0.5

            def worker(e):
                sched = t0 + e["arrival_offset_s"]
                time.sleep(max(0.0, sched - time.time()))
                with sem:
                    replay_session(e, traces[e["episode_id"]], router_url=info["router_url"], out=out, lock=lock,
                                   scheduled_start=sched, tag=tag)
                n[0] += 1

            threads = [threading.Thread(target=worker, args=(e,)) for e in todo]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            say(f"[replay {setup} {out.name}] {n[0]}/{len(episodes)} sessions")
        return finalize("complete")
    except BaseException:
        abort_and_finalize("error")
        raise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--setup", required=True, choices=sorted(cluster.CLUSTER["setups"]))
    ap.add_argument("--profile", default="one_mac")
    ap.add_argument("--run", default="run1", help="result-set name; replays use the recording of the same run")
    ap.add_argument("--tiers", default="0")
    ap.add_argument("--traces", default=None, help="defaults to the recording setup's e2e directory of this run")
    ap.add_argument("--first", type=int, default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--allow-missing", action="store_true")
    args = ap.parse_args()
    manifest = load()
    rec = cluster.CLUSTER["recording_setup"]
    trace_root = Path(args.traces) if args.traces else setup_dir(args.profile, rec, args.run) / "e2e"
    if args.first:
        selections = [(f"first{args.first}", manifest[: args.first])]
    else:
        selections = [(f"tier{t}", [e for e in manifest if e["tier"] == int(t)]) for t in args.tiers.split(",")]
    for label, eps in selections:
        out = Path(args.out) / label if args.out else setup_dir(args.profile, args.setup, args.run) / "replay" / label
        meta = run(args.setup, args.profile, trace_root, eps, out, allow_missing=args.allow_missing, run_name=args.run)
        say(json.dumps({k: meta.get(k) for k in ("setup", "episodes", "wall_s", "missing_traces")}))


if __name__ == "__main__":
    main()
