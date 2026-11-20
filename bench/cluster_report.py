"""Report for the multi-server experiment (S1 round-robin, S2 prefix-aware, S3 prefix-aware + session-aware cache).

Usage: python -m bench.cluster_report [--profile one_mac] [--tiers tier0,tier1]
Writes reports/generated/cluster_<profile>_tables.md (+ metrics JSON, charts) and per-setup summaries/CSVs.
"""
import argparse
import json
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="one_mac")
    ap.add_argument("--tiers", default=None)
    args = ap.parse_args()
    tiers = args.tiers.split(",") if args.tiers else None
    base = ROOT / CLUSTER["results_root"] / args.profile
    for s in SETUPS:
        report.RESULT_DIRS[s] = base / s
    report.build(list(SETUPS), f"cluster_{args.profile}", kinds=("e2e", "replay"), baseline="S1", tiers=tiers,
                 pairs=[("S2", "S1"), ("S3", "S2"), ("S3", "S1")], extra_sections=make_section(args.profile, tiers))


if __name__ == "__main__":
    main()
