"""End-to-end runs of the multi-agent LangGraph app through llm-router + per-server gateways (setups S1-S3).

Usage:
  python -m bench.cluster_run --setup S2 --tiers 0            # episodes 0-49
  python -m bench.cluster_run --setup S1 --tiers 0,1 --max-episodes 200
  python -m bench.cluster_run --setup S2 --first 4 --out results/cluster/smoke/S2   (smoke test)
Results: results/cluster/<profile>/<setup>/e2e/tier<k>/ . Re-running resumes (completed episodes are skipped).
"""
import argparse
import json
import time
from pathlib import Path

import httpx

from agent.session import ABORT

from . import cluster
from .manifest import load
from .monitor import Monitor
from .provenance import install_termination_handler, write_run_json
from .run_e2e import groups_in_order, run_group
from .util import say

ROOT = Path(__file__).resolve().parents[1]


def setup_dir(profile, setup):
    return ROOT / cluster.CLUSTER["results_root"] / profile / setup


def start_monitors(out_dir, info):
    mons = []
    for i, si in enumerate(info["servers"]):
        pids = {"llama": si.get("llama_pid"), "gateway": si.get("gateway_pid")}
        if i == 0:
            pids["router"] = info.get("router_pid")
        mons.append(Monitor(out_dir / "logs", si["llama_url"], pids, name=f"monitor_{si['id']}",
                            slot_prefix=si["id"], track_bench=(i == 0)).start())
    return mons


def stack_meta(info, mons):
    peak = {}
    for m, si in zip(mons, info["servers"]):
        for k, v in m.peak_rss.items():
            peak[k if k in ("bench", "router") else f"{k}_{si['id']}"] = v
    return {"total_slots": info["total_slots"], "n_ctx_per_slot": info["n_ctx_per_slot"],
            "model_startup_s": info["model_startup_s"], **{k: v for k, v in info.items() if k != "servers"},
            "servers": info["servers"]}, peak


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--setup", required=True, choices=sorted(cluster.CLUSTER["setups"]))
    ap.add_argument("--profile", default="one_mac")
    ap.add_argument("--tiers", default=None)
    ap.add_argument("--first", type=int, default=None)
    ap.add_argument("--max-episodes", type=int, default=None, help="only manifest episodes with index < N")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    cfg = cluster.CLUSTER
    manifest = load()
    if args.first:
        selections = [(f"first{args.first}", manifest[: args.first])]
    else:
        tiers = [int(t) for t in args.tiers.split(",")]
        selections = [(f"tier{t}", [e for e in manifest if e["tier"] == t
                                    and (args.max_episodes is None or e["index"] < args.max_episodes)])
                      for t in tiers]
    for label, episodes in selections:
        if not episodes:
            say(f"[{args.setup} {label}] no episodes selected (max-episodes cap); skipping")
            continue
        out_dir = Path(args.out) if args.out else setup_dir(args.profile, args.setup) / "e2e" / label
        out_dir.mkdir(parents=True, exist_ok=True)
        run_id = f"cluster-{args.profile}-{args.setup}-e2e-{label}"
        done = {p.stem for p in (out_dir / "episodes").glob("*.json")}
        if done >= {e["episode_id"] for e in episodes} and (out_dir / "run.json").exists():
            say(f"[{run_id}] all {len(episodes)} episodes already complete; skipping")
            continue
        info = cluster.start(args.setup, out_dir / "logs", run_id=run_id, profile=args.profile)
        mons = start_monitors(out_dir, info)
        t_start = time.time()
        n_done = [len(done)]
        finalized = []

        def log(r):
            if r.get("status") == "aborted":
                return
            n_done[0] += 1
            ev = r.get("evaluation") or {}
            say(f"[{run_id}] {n_done[0]}/{len(episodes)} {r.get('episode_id')} {r.get('workload')} "
                f"{r.get('status')}/{r.get('outcome')} success={ev.get('task_success')} "
                f"calls={r.get('model_calls')} helpers={len(r.get('helper_sessions') or [])} "
                f"t={r.get('total_latency_s', 0):.0f}s")

        def finalize(status):
            if finalized:
                return finalized[0]
            for m in mons:
                m.stop()
            try:
                stats = cluster.collect_stats(info)
                (out_dir / "logs" / "final_stats.json").write_text(json.dumps(stats, indent=1))
            except Exception as exc:  # noqa: BLE001 - never lose run.json because stats collection failed
                say(f"final stats collection failed: {exc!r}")
            cluster.stop()
            completed = len(list((out_dir / "episodes").glob("*.json")))
            stack, peak = stack_meta(info, mons)
            meta = {"run_id": run_id, "setup": args.setup, "profile": args.profile, "label": label,
                    "episodes": len(episodes), "episodes_completed": completed,
                    "status": status if completed >= len(episodes) else "partial", "stack": stack,
                    "peak_rss_bytes": peak, "agent": cfg["agent"], "model": cfg["model"],
                    "manifest_sha256": json.loads((ROOT / "manifests" / "master_manifest.meta.json").read_text())["sha256"]}
            finalized.append(write_run_json(out_dir / "run.json", meta, time.time() - t_start))
            return finalized[0]

        install_termination_handler(lambda status: (ABORT.set(), finalize(status)))
        try:
            for group in groups_in_order(episodes):
                run_group(group, out_dir=out_dir, info={"gateway_url": info["router_url"]}, config_name=args.setup,
                          agent_cfg=cfg["agent"], run_id=run_id, log=log)
            meta = finalize("complete")
        except BaseException:
            ABORT.set()
            finalize("error")
            raise
        say(f"[{run_id}] {meta['episodes_completed']}/{len(episodes)} episodes complete; this invocation "
            f"{(time.time() - t_start) / 60:.1f} min, total {meta['wall_s'] / 60:.1f} min")


if __name__ == "__main__":
    main()
