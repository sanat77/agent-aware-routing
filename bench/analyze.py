"""Compute the 20 benchmark metrics for an end-to-end or replay run directory (one or more tiers).

Every metric is a dict with its statistics and the number of observations `n`. Metrics that the runtime does not
expose are reported as {"available": False, "reason": ...} instead of being estimated silently.
"""
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

from .logparse import parse as parse_llama_log

HIDDEN_TESTS_PER_EPISODE = 111  # 25 check modules; constant across episodes (collection errors count as 0 passed)
TOOL_WAIT_MIN_S = 1.0


def stats(values):
    vals = [float(v) for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if not vals:
        return {"n": 0}
    a = np.array(vals)
    out = {"n": len(vals), "mean": float(a.mean()), "median": float(np.median(a)), "p95": float(np.percentile(a, 95)),
           "min": float(a.min()), "max": float(a.max()), "sum": float(a.sum())}
    out["p99"] = float(np.percentile(a, 99)) if len(vals) >= 20 else None  # p99 not meaningful below ~20 obs
    return out


def rate(num, den):
    return {"value": (num / den) if den else None, "num": num, "n": den}


def _jsonl(path):
    """Read a JSONL file, skipping a line truncated by an interrupted write."""
    p = Path(path)
    if not p.exists():
        return []
    rows = []
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def load_dirs(base, kind, tiers=None):
    """Return tier directories under base/<kind>/ (optionally only the named tiers), sorted by name."""
    root = Path(base) / kind
    return sorted([d for d in root.glob("*") if d.is_dir() and (d / "run.json").exists()
                   and (tiers is None or d.name in tiers)])


# --------------------------------------------------------------------------------------------------------------
# request-level metrics shared by e2e and replay
# --------------------------------------------------------------------------------------------------------------

def request_metrics(reqs, ctx_mode_by_session, waits_before):
    """reqs: list of dicts with session_id, step, prompt_n, cache_n, prompt_ms, ttft_ms, queue, slot, ..."""
    by_session = defaultdict(list)
    for r in reqs:
        by_session[r["session_id"]].append(r)
    eligible = hits = 0
    retention_vals, retained, after_wait = [], 0, 0
    prefix_loss = 0
    resumption = []
    for sid, rs in by_session.items():
        rs.sort(key=lambda r: (r["step"] if r["step"] is not None else -1, r.get("arrival", 0)))
        append_mode = ctx_mode_by_session.get(sid, "append") == "append"
        for prev, cur in zip(rs, rs[1:]):
            if not append_mode or cur.get("prompt_tokens") is None:
                continue
            eligible += 1
            ok = (cur["cache_n"] or 0) >= 0.5 * cur["prompt_tokens"]
            hits += ok
            prev_tokens = prev.get("prompt_tokens") or 0
            if prev_tokens and (cur["cache_n"] or 0) < 0.5 * prev_tokens:
                prefix_loss += 1
            w = waits_before.get((sid, cur["step"]), 0.0)
            if w >= TOOL_WAIT_MIN_S and prev_tokens:
                after_wait += 1
                frac = min(1.0, (cur["cache_n"] or 0) / prev_tokens)
                retention_vals.append(frac)
                retained += frac >= 0.9
        for cur in rs:
            if waits_before.get((sid, cur["step"]), 0.0) >= TOOL_WAIT_MIN_S and cur.get("ttft_ms") is not None:
                resumption.append(cur["ttft_ms"])
    total_prompt = sum(r.get("prompt_tokens") or 0 for r in reqs)
    total_cached = sum(r.get("cache_n") or 0 for r in reqs)
    # slot switches: request served on a slot whose previous request belonged to another session
    switches = 0
    last_on_slot = {}
    for r in sorted(reqs, key=lambda r: r.get("arrival", 0)):
        s = r.get("slot")
        if s is None:
            continue
        if s in last_on_slot and last_on_slot[s] != r["session_id"]:
            switches += 1
        last_on_slot[s] = r["session_id"]
    slot_counts = defaultdict(int)
    for r in reqs:
        if r.get("slot") is not None:
            slot_counts[r["slot"]] += 1
    counts = np.array(list(slot_counts.values()) or [0])
    return {
        "ttft_ms": stats(r.get("ttft_ms") for r in reqs),
        "prefill_ms": stats(r.get("prompt_ms") for r in reqs),
        "prefill_ms_per_request_with_uncached_tokens": stats(r.get("prompt_ms") for r in reqs if (r.get("prompt_n") or 0) > 1),
        "queue_wait_ms": stats((r.get("gateway_queue_ms") or 0) + (r.get("est_upstream_queue_ms") or 0) for r in reqs),
        "gateway_queue_ms": stats(r.get("gateway_queue_ms") for r in reqs),
        "est_upstream_queue_ms": stats(r.get("est_upstream_queue_ms") for r in reqs),
        "session_resumption_latency_ms": stats(resumption),
        "eligible_cache_hit_rate": rate(hits, eligible),
        "prefix_reuse_ratio": rate(total_cached, total_prompt),
        "recomputed_prompt_tokens": {"total": sum(r.get("prompt_n") or 0 for r in reqs),
                                     "per_request": stats(r.get("prompt_n") for r in reqs)},
        "cache_retention_across_tool_waits": {"mean_retained_fraction": stats(retention_vals),
                                              "fully_retained_rate": rate(retained, after_wait)},
        "prefix_loss_events": prefix_loss,
        "slot_switches": switches,
        "per_slot_requests": dict(sorted(slot_counts.items())),
        "request_load_cv": float(counts.std() / counts.mean()) if counts.mean() else None,
        "routing_decision_us": stats(r.get("routing_decision_us") for r in reqs),
        "gateway_overhead_ms": stats(r.get("gateway_overhead_ms") for r in reqs),
        "input_tokens": total_prompt,
        "cached_tokens": total_cached,
        "output_tokens": sum(r.get("predicted_n") or 0 for r in reqs),
        "requests": len(reqs),
        "request_errors": sum(1 for r in reqs if r.get("error")),
    }


def monitor_metrics(monitor_rows, n_ctx_total):
    if not monitor_rows:
        return {"available": False}
    slot_busy = defaultdict(list)
    kv_est = []
    for row in monitor_rows:
        slots = row.get("slots")
        if not slots:
            continue
        kv_est.append(sum((s.get("n_prompt_tokens") or 0) for s in slots) / n_ctx_total)
        for s in slots:
            slot_busy[s["id"]].append(1.0 if s["busy"] else 0.0)
    util = {k: float(np.mean(v)) for k, v in sorted(slot_busy.items())}
    u = np.array(list(util.values()) or [0.0])
    peak = defaultdict(int)
    for row in monitor_rows:
        for k, v in (row.get("rss") or {}).items():
            if v:
                peak[k] = max(peak[k], v)
    return {
        "available": True,
        "slot_utilization": util,
        "mean_slot_utilization": float(u.mean()),
        "slot_busy_imbalance_max_over_mean": float(u.max() / u.mean()) if u.mean() else None,
        "slot_busy_cv": float(u.std() / u.mean()) if u.mean() else None,
        "kv_occupancy_estimate": {**stats(kv_est), "note": "sum(slot n_prompt_tokens)/n_ctx from GET /slots; "
                                  "an estimate because llama.cpp b11669 exposes no KV-cells-used gauge"},
        "peak_rss_mib": {k: v / 2 ** 20 for k, v in peak.items()},
        "samples": len(monitor_rows),
        "power_samples_on_ac": rate(sum(1 for r in monitor_rows if (r.get("power") or {}).get("on_ac_power")),
                                    sum(1 for r in monitor_rows if r.get("power"))),
    }


# --------------------------------------------------------------------------------------------------------------

def gateway_requests(run_dir, keep_request_ids=None):
    """Gateway request records. If a run was interrupted and resumed, an episode may have been retried:
    duplicates are removed by request_id (last wins), and for e2e runs only requests belonging to completed
    episodes (keep_request_ids) are kept."""
    rows = _jsonl(Path(run_dir) / "logs" / "gateway" / "requests.jsonl")
    latest = {}
    for r in rows:
        latest[r.get("request_id")] = r
    out = []
    for rid, r in latest.items():
        if keep_request_ids is not None and rid not in keep_request_ids:
            continue
        out.append({
            "session_id": r.get("session_id"), "episode_id": r.get("episode_id"), "step": r.get("step"),
            "arrival": r.get("arrival_unix_ms"), "prompt_n": r.get("prompt_n"), "cache_n": r.get("cache_n"),
            "prompt_tokens": r.get("prompt_tokens"), "prompt_ms": r.get("prompt_ms"), "ttft_ms": r.get("ttft_ms"),
            "predicted_n": r.get("predicted_n"), "gateway_queue_ms": r.get("gateway_queue_ms"),
            "est_upstream_queue_ms": r.get("est_upstream_queue_ms"), "slot": r.get("served_slot"),
            "routing_decision_us": r.get("routing_decision_us"), "gateway_overhead_ms": r.get("gateway_overhead_ms"),
            "error": r.get("error"), "decision_reason": r.get("decision_reason"),
        })
    return out


def analyze_e2e(base, tiers=None):
    dirs = load_dirs(base, "e2e", tiers)
    episodes, reqs, mon, waits, run_meta, logs = [], [], [], {}, [], []
    wall = 0.0
    for d in dirs:
        meta = json.loads((d / "run.json").read_text())
        run_meta.append(meta)
        wall += meta["wall_s"]
        tier_eps = [json.loads(p.read_text()) for p in sorted((d / "episodes").glob("*.json"))]
        episodes.extend(tier_eps)
        keep = {c["request_id"] for e in tier_eps for c in e.get("calls", [])}
        reqs.extend(gateway_requests(d, keep_request_ids=keep))
        mon.extend(_jsonl(d / "logs" / "monitor.jsonl"))
        logs.append(parse_llama_log(d / "logs" / "llama-server.log"))
    ctx_mode = {e["session_id"]: e.get("options", {}).get("context_mode", "append") for e in episodes}
    waits = _waits_from_events(dirs)
    return summarize(episodes, reqs, mon, waits, run_meta, logs, wall, ctx_mode, kind="e2e")


def _waits_from_events(dirs):
    """Map (session_id, step) -> tool wait seconds that preceded that model call."""
    waits = {}
    for d in dirs:
        evs = _jsonl(d / "events.jsonl")
        pending = defaultdict(float)
        for ev in evs:
            sid = ev["session_id"]
            if ev["kind"] == "tool_wait":
                pending[sid] += ev["seconds"]
            elif ev["kind"] == "model_call":
                if pending[sid] > 0:
                    waits[(sid, ev["step"])] = pending[sid]
                pending[sid] = 0.0
    return waits


def summarize(episodes, reqs, mon, waits, run_meta, logs, wall, ctx_mode, kind, by_workload=True):
    n = len(episodes)
    out = {"kind": kind, "episodes": n, "wall_minutes": wall / 60.0}
    if kind == "e2e":
        ev = [e.get("evaluation") or {} for e in episodes]
        succ = sum(1 for x in ev if x.get("task_success"))
        out["1_task_success_rate"] = rate(succ, n)
        out["2_hidden_test_pass_rate"] = rate(sum(x.get("hidden_tests_passed", 0) for x in ev),
                                              HIDDEN_TESTS_PER_EPISODE * n)
        out["3_regression_free_patch_rate"] = rate(sum(1 for x in ev if x.get("regression_free")), n)
        out["3b_regression_free_given_success"] = rate(sum(1 for x in ev if x.get("regression_free")), succ)
        tc = sum(e.get("tool_calls", 0) for e in episodes)
        tok = sum(e.get("tool_calls_ok", 0) for e in episodes)
        out["4_tool_call_success_rate"] = rate(tok, tc)
        out["5_end_to_end_task_latency_s"] = stats(e.get("agent_latency_s") for e in episodes)
        out["10_completed_tasks_per_minute"] = {"value": succ / (wall / 60.0) if wall else None,
                                                "successful_tasks": succ, "wall_minutes": wall / 60.0}
        out["agent_completed_status_rate"] = rate(sum(1 for e in episodes if e.get("status") == "completed"), n)
        out["outcomes"] = _count(e.get("outcome") for e in episodes)
        out["session_wait_s"] = stats(e.get("session_wait_s") for e in episodes)
        out["tool_execution_s_per_call"] = stats(t["seconds"] for e in episodes for t in e.get("tools", []))
        out["tool_wait_s_per_episode"] = stats(e.get("tool_wait_seconds") for e in episodes)
        out["model_calls_per_episode"] = stats(e.get("model_calls") for e in episodes)
        out["tool_calls_per_episode"] = stats(e.get("tool_calls") for e in episodes)
        out["input_tokens_per_episode"] = stats(e.get("input_tokens") for e in episodes)
        out["output_tokens_per_episode"] = stats(e.get("output_tokens") for e in episodes)
        out["recomputed_tokens_per_episode"] = stats(e.get("recomputed_tokens") for e in episodes)
        tool_err = sum(e.get("tool_calls", 0) - e.get("tool_calls_ok", 0) for e in episodes)
        model_err = sum(len(e.get("model_errors", [])) for e in episodes)
        crashes = sum(1 for e in episodes if e.get("crash") or e.get("status") == "harness_error")
    else:
        out["5_end_to_end_session_latency_s"] = stats(e.get("session_latency_s") for e in episodes)
        out["10_completed_sessions_per_minute"] = {"value": n / (wall / 60.0) if wall else None,
                                                   "note": "replay has no task correctness; sessions replayed per minute"}
        out["session_wait_s"] = stats(e.get("session_wait_s") for e in episodes)
        out["output_matches_recording_rate"] = rate(
            sum(1 for e in episodes for r in e["records"] if r.get("output_matches_recording")),
            sum(len(e["records"]) for e in episodes))
        tool_err, model_err = 0, sum(e.get("request_errors", 0) for e in episodes)
        crashes = 0
        tc = 0
    rm = request_metrics(reqs, ctx_mode, waits)
    out["6_ttft_ms"] = rm["ttft_ms"]
    out["7_prefill_latency_ms"] = rm["prefill_ms"]
    out["8_session_resumption_latency_ms"] = rm["session_resumption_latency_ms"]
    out["9_queue_wait_ms"] = {**rm["queue_wait_ms"], "gateway_queue_ms": rm["gateway_queue_ms"],
                              "est_upstream_queue_ms": rm["est_upstream_queue_ms"],
                              "note": "upstream queue is estimated: upstream TTFT - prompt_ms - 1 decode step"}
    out["11_eligible_cache_hit_rate"] = {**rm["eligible_cache_hit_rate"],
                                         "definition": "requests at step>=1 of append-mode sessions with cache_n >= 50% of prompt tokens"}
    out["12_prefix_cache_reuse_ratio"] = rm["prefix_reuse_ratio"]
    out["13_recomputed_prompt_tokens"] = rm["recomputed_prompt_tokens"]
    out["14_cache_retention_across_tool_waits"] = rm["cache_retention_across_tool_waits"]
    llama = _merge_logs(logs)
    out["15_cache_eviction_and_slot_reset_events"] = {
        "prefix_loss_events": rm["prefix_loss_events"], "slot_switches": rm["slot_switches"],
        "prompt_cache_saves_to_host_ram": llama.get("prompt_cache_saves"),
        "tasks_with_zero_reuse": llama.get("tasks_with_zero_reuse"),
        "definition": "prefix_loss: eligible request reusing <50% of the previous request's tokens; "
                      "slot_switch: slot serves a different session than its previous request"}
    m = monitor_metrics(mon, n_ctx_total=_n_ctx_total(run_meta))
    out["16_peak_process_ram_mib"] = m.get("peak_rss_mib") if m.get("available") else {"available": False}
    out["17_slot_and_kv_utilization"] = {k: m.get(k) for k in ("slot_utilization", "mean_slot_utilization",
                                                                "kv_occupancy_estimate")} if m.get("available") else {"available": False}
    out["power_samples_on_ac"] = m.get("power_samples_on_ac") if m.get("available") else None
    out["18_session_load_imbalance"] = {"slot_busy_max_over_mean": m.get("slot_busy_imbalance_max_over_mean"),
                                        "slot_busy_cv": m.get("slot_busy_cv"),
                                        "per_slot_requests": rm["per_slot_requests"],
                                        "request_count_cv": rm["request_load_cv"]}
    out["19_rust_routing_overhead"] = {"decision_us": rm["routing_decision_us"],
                                       "gateway_overhead_ms": rm["gateway_overhead_ms"]}
    out["20_failure_rates"] = {"model_request_failures": rate(model_err, max(rm["requests"], 1)),
                               "tool_failures": rate(tool_err, tc) if kind == "e2e" else None,
                               "episode_crashes": rate(crashes, n), "gateway_logged_errors": rm["request_errors"]}
    out["tokens"] = {"input": rm["input_tokens"], "cached": rm["cached_tokens"], "output": rm["output_tokens"],
                     "model_calls": rm["requests"]}
    out["cache_bytes"] = {"prompt_cache_max_state_mib": llama.get("prompt_cache_max_state_mib"),
                          "prompt_cache_saved_mib_total": llama.get("prompt_cache_saved_mib"),
                          "source": "llama-server -lv 4 log lines 'cache state' / 'prompt_save'"}
    out["llama_slot_selection"] = llama.get("slot_selection")
    out["model_startup_s"] = stats(r["stack"].get("model_startup_s") for r in run_meta)
    if by_workload:
        out["by_workload"] = {}
        for w in sorted({e["workload"] for e in episodes}):
            ew = [e for e in episodes if e["workload"] == w]
            sids = {e["session_id"] for e in ew}
            rw = [r for r in reqs if r["session_id"] in sids]
            sub = summarize(ew, rw, [], waits, run_meta, [], wall, ctx_mode, kind, by_workload=False)
            for k in ("16_peak_process_ram_mib", "17_slot_and_kv_utilization", "18_session_load_imbalance",
                      "cache_bytes", "model_startup_s", "llama_slot_selection", "power_samples_on_ac"):
                sub.pop(k, None)
            out["by_workload"][w] = sub
    return out


def _n_ctx_total(run_meta):
    for r in run_meta:
        s = r.get("stack", {})
        if s.get("total_slots") and s.get("n_ctx_per_slot"):
            return s["total_slots"] * s["n_ctx_per_slot"]
    return 32768


def _merge_logs(logs):
    out = {}
    for l in logs:
        if not l.get("available"):
            continue
        for k, v in l.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out[k] = max(out.get(k, 0), v) if "max" in k else out.get(k, 0) + v
            elif isinstance(v, dict):
                d = out.setdefault(k, {})
                for kk, vv in v.items():
                    d[kk] = d.get(kk, 0) + vv
    return out


def _count(it):
    c = defaultdict(int)
    for x in it:
        c[x] += 1
    return dict(c)


def analyze_replay(base, subdir="replay", tiers=None):
    root = Path(base) / subdir
    dirs = sorted(d for d in root.glob("*") if d.is_dir() and (d / "run.json").exists()
                  and (tiers is None or d.name in tiers))
    sessions, reqs, mon, run_meta, logs = [], [], [], [], []
    wall = 0.0
    waits = {}
    for d in dirs:
        meta = json.loads((d / "run.json").read_text())
        meta.setdefault("stack", {})
        run_meta.append(meta)
        wall += meta["wall_s"]
        for s in _jsonl(d / "replay_sessions.jsonl"):
            sessions.append(s)
            for r in s["records"]:
                if r.get("tool_wait_before_s"):
                    waits[(s["session_id"], r["step"])] = r["tool_wait_before_s"]
        keep = {r["request_id"] for s in sessions for r in s["records"]}
        reqs.extend(gateway_requests(d, keep_request_ids=keep))
        mon.extend(_jsonl(d / "logs" / "monitor.jsonl"))
        logs.append(parse_llama_log(d / "logs" / "llama-server.log"))
    from .manifest import load
    man = {e["session_id"]: e for e in load()}
    ctx_mode = {sid: man[sid]["context_mode"] for sid in {s["session_id"] for s in sessions} if sid in man}
    return summarize(sessions, reqs, mon, waits, run_meta, logs, wall, ctx_mode, kind="replay")


def per_episode_table(base, kind="e2e", tiers=None):
    """Flat per-episode rows (for CSV export and paired statistics)."""
    rows = []
    if kind == "e2e":
        for d in load_dirs(base, "e2e", tiers):
            tier_eps = [json.loads(p.read_text()) for p in sorted((d / "episodes").glob("*.json"))]
            keep = {c["request_id"] for e in tier_eps for c in e.get("calls", [])}
            reqs = gateway_requests(d, keep_request_ids=keep)
            by_sid = defaultdict(list)
            for r in reqs:
                by_sid[r["session_id"]].append(r)
            for e in tier_eps:
                ev = e.get("evaluation") or {}
                rs = by_sid.get(e["session_id"], [])
                rows.append({
                    "episode_id": e["episode_id"], "workload": e["workload"], "bug_category": e["bug_category"],
                    "fault_id": e.get("fault_id"), "status": e.get("status"), "outcome": e.get("outcome"),
                    "task_success": int(bool(ev.get("task_success"))), "regression_free": int(bool(ev.get("regression_free"))),
                    "hidden_tests_passed": ev.get("hidden_tests_passed", 0), "agent_latency_s": e.get("agent_latency_s"),
                    "session_wait_s": e.get("session_wait_s"), "model_calls": e.get("model_calls"),
                    "tool_calls": e.get("tool_calls"), "tool_calls_ok": e.get("tool_calls_ok"),
                    "input_tokens": e.get("input_tokens"), "cached_tokens": e.get("cached_tokens"),
                    "recomputed_tokens": e.get("recomputed_tokens"), "output_tokens": e.get("output_tokens"),
                    "mean_ttft_ms": _mean(r["ttft_ms"] for r in rs), "sum_prefill_ms": sum(r["prompt_ms"] or 0 for r in rs),
                    "mean_queue_ms": _mean((r["gateway_queue_ms"] or 0) + (r["est_upstream_queue_ms"] or 0) for r in rs),
                    "tool_wait_s": e.get("tool_wait_seconds"),
                })
    else:
        root = Path(base) / kind
        for d in sorted(x for x in root.glob("*") if (x / "run.json").exists() and (tiers is None or x.name in tiers)):
            for s in _jsonl(d / "replay_sessions.jsonl"):
                rec = s["records"]
                rows.append({
                    "episode_id": s["episode_id"], "workload": s["workload"], "bug_category": s["bug_category"],
                    "session_latency_s": s["session_latency_s"], "session_wait_s": s["session_wait_s"],
                    "requests": s["requests"], "request_errors": s["request_errors"],
                    "input_tokens": sum((r["prompt_n"] or 0) + (r["cache_n"] or 0) for r in rec),
                    "cached_tokens": sum(r["cache_n"] or 0 for r in rec),
                    "recomputed_tokens": sum(r["prompt_n"] or 0 for r in rec),
                    "mean_ttft_ms": _mean(r["ttft_ms"] for r in rec), "sum_prefill_ms": sum(r["prompt_ms"] or 0 for r in rec),
                    "mean_queue_ms": _mean((r["gateway_queue_ms"] or 0) + (r["est_upstream_queue_ms"] or 0) for r in rec),
                    "output_match_rate": _mean(1.0 if r["output_matches_recording"] else 0.0 for r in rec),
                })
    return rows


def _mean(it):
    v = [x for x in it if x is not None]
    return float(np.mean(v)) if v else None
