"""Validate every one of the 1,000 fault episodes.

For each (category, variation):
  1. the fault applies cleanly (each edit matches exactly once),
  2. the shipped reproduction test FAILS on the faulty workspace,
  3. the faulty workspace is scored task_success = False by the hidden evaluator,
  4. the reference solution (pristine tracker/) is scored regression_free = True.

Usage: python -m faultlab.validate [--jobs 8] [--limit N] [--out results/faultlab_validation.json]
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from .injector import PRISTINE, all_episode_keys, build_workspace, evaluate


def check_one(key):
    category_name, v = key
    t0 = time.time()
    out = {"bug_category": category_name, "bug_variation": v}
    with tempfile.TemporaryDirectory(prefix="faultlab-val-") as tmp:
        ws = Path(tmp) / "ws"
        try:
            spec = build_workspace(category_name, v, ws)
        except Exception as exc:  # noqa: BLE001
            out.update(ok=False, error=f"build: {exc}")
            return out
        out["fault_id"] = spec["fault_id"]
        proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", spec["visible_test"]],
                              cwd=ws, capture_output=True, text=True, timeout=120)
        out["visible_fails_on_fault"] = proc.returncode != 0
        faulty = evaluate(ws, category_name, v)
        out["faulty_task_success"] = faulty["task_success"]
        out["faulty_hidden_bug_failed"] = faulty["hidden_bug_tests_total"] - faulty["hidden_bug_tests_passed"]
        shutil.rmtree(ws / "tracker")
        shutil.copytree(PRISTINE / "tracker", ws / "tracker")
        fixed = evaluate(ws, category_name, v)
        out["reference_regression_free"] = fixed["regression_free"]
        out["reference_failed_tests"] = fixed["failed_tests"]
        out["hidden_tests_total"] = fixed["hidden_tests_total"]
        out["regression_tests_total"] = fixed["regression_tests_total"]
    out["ok"] = (out["visible_fails_on_fault"] and not out["faulty_task_success"]
                 and out["reference_regression_free"])
    out["seconds"] = round(time.time() - t0, 2)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--category", default=None)
    ap.add_argument("--out", default="results/faultlab_validation.json")
    args = ap.parse_args()
    keys = all_episode_keys()
    if args.category:
        keys = [k for k in keys if k[0] == args.category]
    if args.limit:
        keys = keys[: args.limit]
    results = []
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(check_one, k) for k in keys]
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            if not r["ok"]:
                print("FAIL", json.dumps(r)[:600], flush=True)
    results.sort(key=lambda r: (r["bug_category"], r["bug_variation"]))
    bad = [r for r in results if not r["ok"]]
    summary = {"episodes": len(results), "ok": len(results) - len(bad), "failed": len(bad),
               "per_category": {}}
    for r in results:
        c = summary["per_category"].setdefault(r["bug_category"], {"ok": 0, "failed": 0})
        c["ok" if r["ok"] else "failed"] += 1
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"summary": summary, "results": results}, indent=1))
    print(json.dumps(summary["per_category"], indent=0))
    print(f"validated {len(results)} episodes: {summary['ok']} ok, {summary['failed']} failed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
