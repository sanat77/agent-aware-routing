"""Report for the multi-server experiment (S1 round-robin, S2 prefix-aware, S3 prefix-aware + session-aware cache).

Usage: python -m bench.cluster_report [--profile one_mac] [--run run1] [--tiers tier0,tier1] [--snapshot]
Writes, per run: reports/generated/cluster_<profile>_<run>_tables.md (+ metrics JSON, charts in
reports/assets/cluster_<profile>_<run>/), and across runs: reports/generated/cluster_<profile>_all_runs.md.
Reports are rebuilt from the raw results, which are never modified; --snapshot keeps a dated copy as well.
"""
import argparse
import json
import shutil
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from . import report
from .analyze import _jsonl, stats
from .cluster import CLUSTER

ROOT = Path(__file__).resolve().parents[1]
SETUPS = ("S1", "S2", "S3")
COUNTER_KEYS = ("requests", "warm", "assigned_empty", "assigned_over_dead", "assigned_over_live", "live_evictions",
                "avoidable_live_evictions", "dead_evictions", "erases_on_finish", "saves", "save_failures", "restores",
                "restore_failures", "waits", "wait_ms_total", "save_ms_total", "restore_ms_total",
                "saved_files_deleted")


def _run_dirs(base, kind, tiers):
    root = Path(base) / kind
    return sorted(d for d in root.glob("*") if (d / "run.json").exists() and (tiers is None or d.name in tiers))


def session_metrics(base, kind, tiers):
    totals = Counter()
    dead_mean_total = 0.0
    dead_p95 = []
    live_mean_total = 0.0
    saved_bytes_max = 0
    per_server_requests = Counter()
    router_reasons = Counter()
    snapshots = 0
    for d in _run_dirs(base, kind, tiers):
        for occ in sorted((d / "logs").glob("gateway_*/occupancy.jsonl")):
            rows = _jsonl(occ)
            snapshots += len(rows)
            prev = None
            for r in rows:  # counters reset when a gateway restarts (resumed run): sum each segment's last value
                c = r.get("counters") or {}
                if prev is not None and c.get("requests", 0) < prev.get("requests", 0):
                    for k in COUNTER_KEYS:
                        totals[k] += prev.get(k, 0)
                prev = c
            if prev:
                for k in COUNTER_KEYS:
                    totals[k] += prev.get(k, 0)
            dead = [((r.get("occupancy") or {}).get("dead_tokens_resident") or 0) for r in rows]
            live = [((r.get("occupancy") or {}).get("live_sessions") or 0) for r in rows]
            if dead:
                dead_mean_total += float(np.mean(dead))
                dead_p95.append(float(np.percentile(dead, 95)))
                live_mean_total += float(np.mean(live))
            saved_bytes_max = max([saved_bytes_max] + [((r.get("occupancy") or {}).get("saved_bytes") or 0) for r in rows])
        for req in sorted((d / "logs").glob("gateway_*/requests.jsonl")):
            for r in _jsonl(req):
                per_server_requests[r.get("server_id")] += 1
        if kind == "e2e":
            for p in (d / "episodes").glob("*.json"):
                for c in json.loads(p.read_text()).get("calls", []):
                    router_reasons[c.get("router_reason")] += 1
        else:
            for s in _jsonl(d / "replay_sessions.jsonl"):
                for r in s["records"]:
                    router_reasons[r.get("router_reason")] += 1
    n_req = sum(per_server_requests.values())
    share = {k: v / n_req for k, v in sorted(per_server_requests.items(), key=lambda kv: str(kv[0]))} if n_req else {}
    return {
        "counters": dict(totals),
        "dead_tokens_resident_mean_total": dead_mean_total,
        "dead_tokens_resident_p95_max_server": max(dead_p95) if dead_p95 else None,
        "live_sessions_mean_total": live_mean_total,
        "saved_bytes_max": saved_bytes_max,
        "per_server_request_share": share,
        "router_reasons": dict(router_reasons),
        "occupancy_snapshots": snapshots,
        "avg_save_ms": totals["save_ms_total"] / totals["saves"] if totals["saves"] else None,
        "avg_restore_ms": totals["restore_ms_total"] / totals["restores"] if totals["restores"] else None,
    }


def make_section(profile, tiers):
    def section(kind, present):
        data = {s: session_metrics(report.results_dir(s), kind, tiers) for s in present}
        title = "End-to-end" if kind == "e2e" else "Replay"
        md = f"### Session-aware cache metrics ({title})\n\n"
        md += "| Metric | " + " | ".join(report.LABELS[s] for s in present) + " |\n|---|" + "---|" * len(present) + "\n"
        rows = [
            ("Memory held by finished sessions: mean tokens (sum over servers)",
             lambda m: report._fmt(m["dead_tokens_resident_mean_total"], 0)),
            ("Live-session evictions (cache of an unfinished session pushed out of its slot)",
             lambda m: str(m["counters"].get("live_evictions", 0))),
            ("... of which avoidable (a finished session's cache was still resident)",
             lambda m: str(m["counters"].get("avoidable_live_evictions", 0))),
            ("Finished-session caches reused / erased on finish",
             lambda m: f"{m['counters'].get('dead_evictions', 0)} / {m['counters'].get('erases_on_finish', 0)}"),
            ("Saves to disk / restores (failures)",
             lambda m: f"{m['counters'].get('saves', 0)} / {m['counters'].get('restores', 0)} "
                       f"({m['counters'].get('save_failures', 0)}/{m['counters'].get('restore_failures', 0)})"),
            ("Mean save / restore time (ms)",
             lambda m: f"{report._fmt(m['avg_save_ms'])} / {report._fmt(m['avg_restore_ms'])}"),
            ("Gateway slot waits (count, total s)",
             lambda m: f"{m['counters'].get('waits', 0)} ({m['counters'].get('wait_ms_total', 0) / 1000:.1f})"),
            ("Request share per server", lambda m: ", ".join(f"{k}={v:.0%}" for k, v in m["per_server_request_share"].items())),
            ("Router decisions", lambda m: ", ".join(f"{k}={v}" for k, v in sorted(m["router_reasons"].items(), key=lambda kv: str(kv[0])))),
        ]
        for label, fn in rows:
            md += f"| {label} | " + " | ".join(fn(data[s]) for s in present) + " |\n"
        md += ("\nLive/avoidable evictions are counted identically in all setups from the slot that served each "
               "request; only S3 acts on them. S1/S2 never save, restore or erase.\n\n")
        return md, data
    return section


def _key_metrics(summary, kind):
    """A few headline numbers from one setup's summary (for comparing repeated runs)."""
    if not summary:
        return None
    n = summary.get("episodes") or 0
    lat = summary.get("5_end_to_end_task_latency_s" if kind == "e2e" else "5_end_to_end_session_latency_s") or {}
    rec = (summary.get("13_recomputed_prompt_tokens") or {}).get("total")
    out = {"episodes": n, "latency_mean_s": lat.get("mean"), "ttft_mean_ms": (summary.get("6_ttft_ms") or {}).get("mean"),
           "prefix_reuse": (summary.get("12_prefix_cache_reuse_ratio") or {}).get("value"),
           "recomputed_tokens_per_episode": (rec / n) if (rec is not None and n) else None}
    if kind == "e2e":
        out["task_success"] = (summary.get("1_task_success_rate") or {}).get("value")
    return out


def write_runs_summary(profile, per_run):
    """reports/generated/cluster_<profile>_all_runs.md: one row per run, plus mean and std across runs."""
    cols = [("episodes", "episodes", 0), ("task_success", "bug-fix rate", 3), ("latency_mean_s", "mean latency (s)", 1),
            ("ttft_mean_ms", "mean TTFT (ms)", 0), ("prefix_reuse", "prefix reuse", 3),
            ("recomputed_tokens_per_episode", "recomputed tokens / episode", 0)]
    md = (f"# All runs: {profile}\n\nEach run is a separate result set (`results/cluster/{profile}/<run>/`). "
          "Rows are per run; the last row of each block is the mean and standard deviation across runs.\n\n")
    for kind, title in (("e2e", "End-to-end (real agents)"), ("replay", "Trace replay (same requests)")):
        md += f"## {title}\n\n"
        for s in SETUPS:
            rows = [(run, m[kind][s]) for run, m in per_run.items() if m.get(kind, {}).get(s)]
            if not rows:
                continue
            use = [c for c in cols if not (kind == "replay" and c[0] == "task_success")]
            md += f"**{report.LABELS[s]}**\n\n| run | " + " | ".join(c[1] for c in use) + " |\n|---|" + "---|" * len(use) + "\n"
            for run, k in rows:
                md += f"| {run} | " + " | ".join(report._fmt(k.get(c[0]), c[2]) if k.get(c[0]) is not None else "n/a"
                                                for c in use) + " |\n"
            if len(rows) > 1:
                cells = []
                for c in use:
                    v = [k[c[0]] for _, k in rows if k.get(c[0]) is not None]
                    cells.append(f"{np.mean(v):.{c[2]}f} ± {np.std(v, ddof=1):.{c[2]}f}" if len(v) > 1 else "n/a")
                md += "| mean ± std | " + " | ".join(cells) + " |\n"
            md += "\n"
    path = ROOT / "reports" / "generated" / f"cluster_{profile}_all_runs.md"
    path.write_text(md)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="one_mac")
    ap.add_argument("--run", default=None, help="one run name; default: every run found")
    ap.add_argument("--tiers", default=None)
    ap.add_argument("--snapshot", action="store_true", help="also keep a time-stamped copy of each report")
    args = ap.parse_args()
    tiers = args.tiers.split(",") if args.tiers else None
    base = ROOT / CLUSTER["results_root"] / args.profile
    runs = [args.run] if args.run else sorted(d.name for d in base.glob("*") if d.is_dir() and
                                               any((d / s).is_dir() for s in SETUPS))
    per_run = {}
    stamp = time.strftime("%Y%m%d_%H%M%S")
    for run in runs:
        for s in SETUPS:
            report.RESULT_DIRS[s] = base / run / s
        name = f"cluster_{args.profile}_{run}"
        metrics = report.build(list(SETUPS), name, kinds=("e2e", "replay"), baseline="S1", tiers=tiers,
                               pairs=[("S2", "S1"), ("S3", "S2"), ("S3", "S1")],
                               extra_sections=make_section(args.profile, tiers))
        per_run[run] = {kind: {s: _key_metrics((metrics.get(kind) or {}).get(s), kind) for s in SETUPS}
                        for kind in ("e2e", "replay")}
        if args.snapshot:
            hist = ROOT / "reports" / "generated" / "history"
            hist.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / "reports" / "generated" / f"{name}_tables.md", hist / f"{name}_tables_{stamp}.md")
    if per_run:
        path = write_runs_summary(args.profile, per_run)
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
