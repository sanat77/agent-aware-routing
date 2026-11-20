"""End-to-end agent benchmark: real LangGraph agent + real local inference + real tests.

Usage:
  python -m bench.run_e2e --config native_cache --tiers 0          # first 50 episodes
  python -m bench.run_e2e --config native_cache --tiers 1          # episodes 50-99 (cumulative 100)
  python -m bench.run_e2e --config native_cache --first 10 --out results/smoke/native_cache
Results go to <results_dir>/e2e/tier<k>/ (or --out). Re-running skips completed episodes (resume).
"""
import argparse
import json
import threading
import time
from pathlib import Path

from agent.session import ABORT, run_episode

from . import stack
from .manifest import WORKLOADS, load
from .monitor import Monitor
from .provenance import install_termination_handler, write_run_json

ROOT = Path(__file__).resolve().parents[1]


def episode_options(ep, agent_cfg):
    opts = {"max_steps": agent_cfg["max_steps"], "n_predict": agent_cfg["n_predict"],
            "ctx_tokens": agent_cfg["ctx_tokens"], "episode_timeout_s": agent_cfg["episode_timeout_s"],
            "context_mode": ep["context_mode"], "resumable": ep["resumable"]}
    # cluster experiments: OpenAI chat API through llm-router, and multi-agent mode
    opts.update({k: agent_cfg[k] for k in ("api", "agent_mode") if k in agent_cfg})
    return opts


def groups_in_order(episodes):
    """Workload blocks in fixed order; groups in manifest order within each block."""
    out = []
    for workload in WORKLOADS:
        seen = {}
        for e in episodes:
            if e["workload"] == workload:
                seen.setdefault(e["group_id"], []).append(e)
        out.extend(seen.values())
    return out


def _safe_run(e, *, out_dir, info, run_id, config_name, ws_root, agent_cfg, scheduled_start):
    if info.get("announce_starts"):
        try:
            print(f"[{run_id}] starting {e['episode_id']} ({e['workload']}, {e['bug_category']})", flush=True)
        except (BrokenPipeError, OSError, ValueError):
            pass
    try:
        return run_episode(e, out_dir=out_dir, gateway_url=info["gateway_url"], run_id=run_id,
                           config_name=config_name, workspace_root=ws_root,
                           options=episode_options(e, agent_cfg), scheduled_start=scheduled_start)
    except Exception as exc:  # noqa: BLE001 - keep the benchmark going, record the failure; retried on resume
        r = {"episode_id": e["episode_id"], "workload": e["workload"], "status": "harness_error",
             "error": repr(exc), "t": time.time()}
        with open(out_dir / "harness_errors.jsonl", "a") as f:
            f.write(json.dumps(r) + "\n")
        return r


def run_group(group, *, out_dir, info, config_name, agent_cfg, run_id, log):
    done = {p.stem for p in (out_dir / "episodes").glob("*.json")}
    todo = [e for e in group if e["episode_id"] not in done]
    if not todo:
        return []
    conc = max(1, min(group[0]["concurrency"], len(group)))
    results = []
    lock = threading.Lock()
    ws_root = ROOT / ".run" / "workspaces" / run_id
    kw = dict(out_dir=out_dir, info=info, run_id=run_id, config_name=config_name, ws_root=ws_root,
              agent_cfg=agent_cfg)

    if group[0]["arrival_rule"] == "closed_loop":
        for e in todo:
            r = _safe_run(e, scheduled_start=time.time(), **kw)
            log(r)
            results.append(r)
        return results

    sem = threading.Semaphore(conc)
    t0 = time.time() + 0.5

    def worker(e):
        sched = t0 + e["arrival_offset_s"]
        time.sleep(max(0.0, sched - time.time()))
        with sem:
            r = _safe_run(e, scheduled_start=sched, **kw)
        with lock:
            log(r)
            results.append(r)

    threads = [threading.Thread(target=worker, args=(e,)) for e in todo]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--tiers", default=None, help="comma list of tier indices, e.g. 0 or 0,1")
    ap.add_argument("--first", type=int, default=None, help="only the first N manifest episodes (smoke tests)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--policy", default=None, help="override gateway policy (candidate D)")
    ap.add_argument("--gateway-arg", action="append", default=[])
    args = ap.parse_args()

    exp = stack.EXPERIMENTS
    cfg = exp["configs"][args.config]
    manifest = load()
    if args.first:
        selections = [("first%d" % args.first, manifest[: args.first])]
    else:
        tiers = [int(t) for t in args.tiers.split(",")]
        selections = [(f"tier{t}", [e for e in manifest if e["tier"] == t]) for t in tiers]

    for label, episodes in selections:
        out_dir = Path(args.out) if args.out else ROOT / cfg["results_dir"] / "e2e" / label
        out_dir.mkdir(parents=True, exist_ok=True)
        run_id = f"{args.config}-e2e-{label}"
        done = {p.stem for p in (out_dir / "episodes").glob("*.json")}
        if done >= {e["episode_id"] for e in episodes} and (out_dir / "run.json").exists():
            print(f"[{run_id}] all {len(episodes)} episodes already complete; skipping", flush=True)
            continue
        info = stack.start(args.config, out_dir / "logs", run_id=run_id, policy_override=args.policy,
                           gateway_extra=args.gateway_arg)
        mon = Monitor(out_dir / "logs", info["llama_url"], {"llama": info["llama_pid"],
                                                            "gateway": info["gateway_pid"]}).start()
        t_start = time.time()
        n_done = [len(done)]
        finalized = []

        def log(r):
            if r.get("status") == "aborted":
                return
            n_done[0] += 1
            ev = r.get("evaluation") or {}
            print(f"[{run_id}] {n_done[0]}/{len(episodes)} {r.get('episode_id')} {r.get('workload')} "
                  f"{r.get('status')}/{r.get('outcome')} success={ev.get('task_success')} "
                  f"calls={r.get('model_calls')} t={r.get('total_latency_s', 0):.0f}s", flush=True)

        def finalize(status):
            if finalized:
                return finalized[0]
            mon.stop()
            gw_stats = None
            try:
                import httpx
                gw_stats = httpx.get(f"{info['gateway_url']}/gateway/stats", timeout=5).json()
            except Exception:  # noqa: BLE001
                pass
            stack.stop()
            completed = len(list((out_dir / "episodes").glob("*.json")))
            meta = {"run_id": run_id, "config": args.config, "label": label, "episodes": len(episodes),
                    "episodes_completed": completed, "status": status if completed >= len(episodes) else "partial",
                    "stack": info, "peak_rss_bytes": mon.peak_rss, "monitor_samples": mon.samples,
                    "gateway_stats": gw_stats, "agent": exp["agent"], "model": exp["model"],
                    "manifest_sha256": json.loads(
                        (ROOT / "manifests" / "master_manifest.meta.json").read_text())["sha256"]}
            finalized.append(write_run_json(out_dir / "run.json", meta, time.time() - t_start))
            return finalized[0]

        install_termination_handler(lambda status: (ABORT.set(), finalize(status)))
        try:
            for group in groups_in_order(episodes):
                run_group(group, out_dir=out_dir, info=info, config_name=args.config,
                          agent_cfg=exp["agent"], run_id=run_id, log=log)
            meta = finalize("complete")
        except BaseException:
            ABORT.set()
            finalize("error")
            raise
        completed = meta["episodes_completed"]
        print(f"[{run_id}] {completed}/{len(episodes)} episodes complete; this invocation "
              f"{(time.time() - t_start) / 60:.1f} min, total {meta['wall_s'] / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
