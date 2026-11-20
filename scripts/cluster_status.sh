#!/usr/bin/env bash
# Show what a running (or finished) cluster experiment is doing. Read-only: safe to run at any time.
#   scripts/cluster_status.sh            # run1, one_mac
#   scripts/cluster_status.sh run2       # another run name
#   watch -n 30 scripts/cluster_status.sh   (if `watch` is installed) to refresh every 30 s
cd "$(dirname "$0")/.."
RUN="${1:-run1}"
PROFILE="${2:-one_mac}"
exec .venv/bin/python - "$RUN" "$PROFILE" <<'EOF'
import json, subprocess, sys, time
from pathlib import Path
import httpx
from bench.heartbeat import last_event

run, profile = sys.argv[1], sys.argv[2]
base = Path("results/cluster") / profile / run
manifest = [json.loads(l) for l in Path("manifests/master_manifest.jsonl").read_text().splitlines()]
per_tier = {t: sum(1 for e in manifest if e["tier"] == t) for t in range(4)}

procs = subprocess.run(["pgrep", "-fl", "bench.cluster_run|bench.cluster_replay"], capture_output=True, text=True).stdout
active = [l.split(" ", 1)[1] for l in procs.splitlines() if l.strip()]
print(f"run {run} ({profile}) - {time.strftime('%Y-%m-%d %H:%M:%S')}")
print("running now: " + (" | ".join(a.split("-m ", 1)[-1][:90] for a in active) if active else "nothing"))

for setup in ("S2", "S1", "S3"):
    for kind in ("e2e", "replay"):
        cells = []
        for t in range(4):
            d = base / setup / kind / f"tier{t}"
            if not d.exists():
                continue
            if kind == "e2e":
                done = len(list((d / "episodes").glob("*.json")))
            else:
                f = d / "replay_sessions.jsonl"
                done = sum(1 for _ in open(f)) if f.exists() else 0
            status = ""
            if (d / "run.json").exists():
                status = json.loads((d / "run.json").read_text()).get("status", "")
            cells.append(f"tier{t} {done}/{per_tier[t]}{' (' + status + ')' if status else ''}")
        if cells:
            label = "real agents" if kind == "e2e" else "replay"
            print(f"  {setup} {label:11s}: " + ", ".join(cells))

for port, sid in ((8201, "w0"), (8202, "w1")):
    try:
        d = httpx.get(f"http://127.0.0.1:{port}/gateway/stats", timeout=2).json()
        occ = d.get("occupancy") or {}
        slots = ", ".join(f"slot{s['slot']}: {(s['occupant'] or 'empty')[-20:]}" for s in occ.get("slots", []))
        print(f"  server {sid}: {d['aggregates']['requests']} requests so far, {d.get('in_flight', 0)} in flight | {slots}")
    except httpx.HTTPError:
        pass

newest = sorted(base.glob("*/*/tier*/events.jsonl"), key=lambda p: p.stat().st_mtime)
if newest:
    age, what = last_event(newest[-1])
    print(f"  last agent activity: {what}" + (f" ({age:.0f} s ago)" if age is not None else ""))
logs = sorted(base.glob("run_cluster_*.log"), key=lambda p: p.stat().st_mtime)
if logs:
    print(f"  console log: {logs[-1]}  (tail -f it to follow)")
    for line in logs[-1].read_text(errors="replace").strip().splitlines()[-3:]:
        print("    " + line[:160])
EOF
