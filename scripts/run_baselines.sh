#!/usr/bin/env bash
# Unattended baseline run (Phase 4). Runs the three baseline configurations ONE AFTER ANOTHER: they share the
# single M1 GPU and the same ports, and running them side by side would contaminate every latency measurement.
#
#   scripts/run_baselines.sh            # tier 0 (50 episodes): E2E + replay for B, C, then A
#   scripts/run_baselines.sh --tier1    # additionally extend everything to 100 episodes (tier 1)
#   scripts/run_baselines.sh --check    # preflight checks only
#
# Safe to stop with Ctrl-C at any time. Re-running the same command resumes: completed episodes and replayed
# sessions are skipped, and logs/metrics are appended. Requires AC power (set ALLOW_BATTERY=1 to override).
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
WITH_TIER1=0
CHECK_ONLY=0
[[ "${1:-}" == "--tier1" ]] && WITH_TIER1=1
[[ "${1:-}" == "--check" ]] && CHECK_ONLY=1
mkdir -p results/baseline .run
LOG="results/baseline/run_baselines_$(date +%Y%m%d_%H%M%S).log"
# tee ignores Ctrl-C so the log keeps the final lines while the benchmark saves its progress
exec > >(trap '' INT; tee -a "$LOG") 2>&1

say() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
FAILED=()

# keep the Mac awake (idle + system sleep) for as long as this script runs
caffeinate -is -w $$ &

# Ctrl-C reaches the running benchmark directly (same process group); it saves its progress and exits.
# The trap only makes sure the inference servers are gone before this script exits.
trap 'say "interrupted - progress is saved; re-run the same command to resume"; "$PY" -m bench.stack stop >/dev/null 2>&1; exit 130' INT TERM

# ---------------------------------------------------------------- preflight
say "preflight checks (log: $LOG)"
if ! pmset -g batt | grep -q "AC Power" && [[ "${ALLOW_BATTERY:-0}" != 1 ]]; then
  say "the Mac is on battery: plug in the charger (battery power throttles the GPU and would skew timings)"; exit 1
fi
[[ -x "$PY" ]] || { say "missing .venv - run: uv sync"; exit 1; }
command -v llama-server >/dev/null || { say "llama-server not on PATH (brew install llama.cpp)"; exit 1; }
[[ -x gateway/target/release/inference-gateway ]] || {
  say "building Rust gateway"; PATH="/opt/homebrew/opt/rustup/bin:$PATH" cargo build --release --manifest-path gateway/Cargo.toml || exit 1; }
"$PY" - <<'EOF' || exit 1
import hashlib, json, shutil, sys
from pathlib import Path
exp = json.loads(Path("configs/experiments.json").read_text())
model = Path(exp["model"]["path"])
if not model.exists():
    sys.exit(f"model missing: {model} (download: {exp['model']['source']})")
h = hashlib.sha256()
with open(model, "rb") as f:
    for chunk in iter(lambda: f.read(1 << 24), b""):
        h.update(chunk)
if h.hexdigest() != exp["model"]["sha256"]:
    sys.exit(f"model sha256 mismatch: {h.hexdigest()}")
meta = json.loads(Path("manifests/master_manifest.meta.json").read_text())
if hashlib.sha256(Path("manifests/master_manifest.jsonl").read_bytes()).hexdigest() != meta["sha256"]:
    sys.exit("manifest digest mismatch - the master manifest must stay immutable")
free_gb = shutil.disk_usage(".").free / 1e9
if free_gb < 5:
    sys.exit(f"only {free_gb:.1f} GB free disk")
print(f"model ok, manifest ok ({meta['sha256'][:12]}), {free_gb:.0f} GB free")
EOF
if ! "$PY" -c "import json,sys; s=json.load(open('results/faultlab_validation.json'))['summary']; sys.exit(0 if s['ok']==1000 else 1)" 2>/dev/null; then
  say "validating all 1,000 fault episodes (~20 min, CPU only)"
  "$PY" -m faultlab.validate --jobs 6 --out results/faultlab_validation.json || { say "fault validation failed"; exit 1; }
fi
git diff --quiet HEAD -- agent bench faultlab miniissuetracker gateway/src configs manifests 2>/dev/null \
  || say "WARNING: frozen code differs from the committed baseline-freeze state (recorded in run.json)"
"$PY" -m bench.stack stop >/dev/null 2>&1
if [[ $CHECK_ONLY == 1 ]]; then say "preflight passed (--check: nothing run)"; exit 0; fi

run_stage() {  # name, command...
  local name="$1"; shift
  say "=== START $name"
  local t0=$SECONDS
  if "$@"; then say "=== DONE  $name in $(( (SECONDS - t0) / 60 )) min"
  else say "=== FAILED $name (exit $?) - continuing with the next stage"; FAILED+=("$name"); fi
  "$PY" -m bench.report --configs no_cache,native_cache,session_affinity --name baseline >/dev/null 2>&1 \
    && say "    tables refreshed: reports/generated/baseline_tables.md"
}

TRACES=results/baseline/native_cache/e2e
# ---------------------------------------------------------------- tier 0 (cumulative 50 episodes)
# Ordered by value: B and C first (~8-9 h together), then A (no cache), which is the slowest (~9-10 h).
run_stage "E2E    B native_cache     tier0 (50 ep, records traces)" "$PY" -m bench.run_e2e --config native_cache --tiers 0
run_stage "E2E    C session_affinity tier0 (50 ep)"               "$PY" -m bench.run_e2e --config session_affinity --tiers 0
run_stage "REPLAY B native_cache     tier0"                        "$PY" -m bench.replay --config native_cache --traces $TRACES --tiers 0
run_stage "REPLAY C session_affinity tier0"                        "$PY" -m bench.replay --config session_affinity --traces $TRACES --tiers 0
run_stage "E2E    A no_cache         tier0 (50 ep)"               "$PY" -m bench.run_e2e --config no_cache --tiers 0
run_stage "REPLAY A no_cache         tier0"                        "$PY" -m bench.replay --config no_cache --traces $TRACES --tiers 0

# ---------------------------------------------------------------- tier 1 (cumulative 100 episodes), optional
if [[ $WITH_TIER1 == 1 ]]; then
  run_stage "E2E    B native_cache     tier1" "$PY" -m bench.run_e2e --config native_cache --tiers 1
  run_stage "E2E    C session_affinity tier1" "$PY" -m bench.run_e2e --config session_affinity --tiers 1
  run_stage "REPLAY B native_cache     tier1" "$PY" -m bench.replay --config native_cache --traces $TRACES --tiers 1
  run_stage "REPLAY C session_affinity tier1" "$PY" -m bench.replay --config session_affinity --traces $TRACES --tiers 1
  run_stage "E2E    A no_cache         tier1" "$PY" -m bench.run_e2e --config no_cache --tiers 1
  run_stage "REPLAY A no_cache         tier1" "$PY" -m bench.replay --config no_cache --traces $TRACES --tiers 1
fi

"$PY" -m bench.stack stop >/dev/null 2>&1
if (( ${#FAILED[@]} )); then say "finished with failed stages: ${FAILED[*]} (re-run this script to retry them)"
else say "ALL BASELINE STAGES COMPLETE - tables: reports/generated/baseline_tables.md"; fi
