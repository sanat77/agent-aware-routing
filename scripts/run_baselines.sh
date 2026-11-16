#!/usr/bin/env bash
# Phase 4 baseline runs. Pick one baseline per command, or "all".
#
#   scripts/run_baselines.sh B          # B native cache:      E2E (records traces) + replay   ~4-4.5 h   <- run first
#   scripts/run_baselines.sh C          # C session affinity:  E2E + replay of B's traces      ~4-4.5 h
#   scripts/run_baselines.sh A          # A no cache:          E2E + replay of B's traces      ~9-10 h
#   scripts/run_baselines.sh all        # B, then C, then A
#
# Options (any order):  --tier1  also run episodes 50-99 (cumulative 100)   --check  preflight only
#
# The replay stage of A and C needs B's recorded traces. If B has not finished, A/C run their E2E stage and skip
# the replay; re-run the same command after B to do it. Only one baseline can run at a time (they share the GPU
# and ports); a second invocation refuses to start. Ctrl-C is safe: progress is saved and the same command
# resumes where it stopped. Requires AC power (set ALLOW_BATTERY=1 to override).
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"

usage() { sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; }

TARGETS=()
WITH_TIER1=0
CHECK_ONLY=0
for arg in "$@"; do
  case "$arg" in
    A|a|no_cache) TARGETS+=(no_cache) ;;
    B|b|native|native_cache) TARGETS+=(native_cache) ;;
    C|c|affinity|session_affinity) TARGETS+=(session_affinity) ;;
    all|ALL) TARGETS+=(native_cache session_affinity no_cache) ;;
    --tier1) WITH_TIER1=1 ;;
    --check) CHECK_ONLY=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $arg"; echo; usage; exit 2 ;;
  esac
done
if (( ${#TARGETS[@]} == 0 )) && [[ $CHECK_ONLY == 0 ]]; then usage; exit 2; fi

letter() { case "$1" in no_cache) echo A ;; native_cache) echo B ;; session_affinity) echo C ;; esac; }
NAMES=""
if (( ${#TARGETS[@]} )); then for t in "${TARGETS[@]}"; do NAMES="$NAMES$(letter "$t")"; done; fi

# ---------------------------------------------------------------- single-run lock
mkdir -p results/baseline .run
LOCK=.run/run_baselines.lock
if [[ -f $LOCK ]] && kill -0 "$(cat "$LOCK")" 2>/dev/null; then
  echo "another baseline run is active (PID $(cat "$LOCK")). Wait for it, or stop it with Ctrl-C in its terminal."
  exit 1
fi
echo $$ > "$LOCK"

LOG="results/baseline/run_baselines_${NAMES:-check}_$(date +%Y%m%d_%H%M%S).log"
# tee ignores Ctrl-C so the log keeps the final lines while the benchmark saves its progress
exec > >(trap '' INT; tee -a "$LOG") 2>&1

say() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
FAILED=()
SKIPPED=()

# keep the Mac awake (idle + system sleep) for as long as this script runs
caffeinate -is -w $$ &

release_lock() { [[ "$(cat "$LOCK" 2>/dev/null)" == "$$" ]] && rm -f "$LOCK"; }
trap release_lock EXIT
# Ctrl-C reaches the running benchmark directly (same process group); it saves its progress and exits.
# The trap only makes sure the inference servers are gone before this script exits.
trap 'say "interrupted - progress is saved; re-run the same command to resume"; "$PY" -m bench.stack stop >/dev/null 2>&1; exit 130' INT TERM

# ---------------------------------------------------------------- preflight
say "baselines: ${NAMES:-none (check only)}  tier1: $WITH_TIER1  (log: $LOG)"
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

# ---------------------------------------------------------------- stages
run_stage() {  # name, command...
  local name="$1"; shift
  say "=== START $name"
  local t0=$SECONDS
  if "$@"; then say "=== DONE  $name in $(( (SECONDS - t0) / 60 )) min"
  else say "=== FAILED $name (exit $?)"; FAILED+=("$name"); fi
  "$PY" -m bench.report --configs no_cache,native_cache,session_affinity --name baseline >/dev/null 2>&1 \
    && say "    tables refreshed: reports/generated/baseline_tables.md"
}

TRACES=results/baseline/native_cache/e2e
traces_ready() {  # tier -> 0 if Baseline B's E2E run for that tier is complete
  "$PY" -c "import json,sys; m=json.load(open('$TRACES/tier$1/run.json')); sys.exit(0 if m['status']=='complete' else 1)" 2>/dev/null
}

run_baseline() {  # config, tier
  local cfg="$1" tier="$2" name
  name="$(letter "$cfg") $cfg tier$tier"
  run_stage "E2E    $name" "$PY" -m bench.run_e2e --config "$cfg" --tiers "$tier"
  if traces_ready "$tier"; then
    run_stage "REPLAY $name" "$PY" -m bench.replay --config "$cfg" --traces "$TRACES" --tiers "$tier"
  else
    say "=== SKIP   REPLAY $name: Baseline B's traces for tier$tier are not complete yet."
    say "           Run 'scripts/run_baselines.sh B' first, then re-run this command (finished work is skipped)."
    SKIPPED+=("REPLAY $name")
  fi
}

TIERS="0"
[[ $WITH_TIER1 == 1 ]] && TIERS="0 1"
for tier in $TIERS; do
  for cfg in "${TARGETS[@]}"; do
    run_baseline "$cfg" "$tier"
  done
done

"$PY" -m bench.stack stop >/dev/null 2>&1
if (( ${#FAILED[@]} )); then say "finished with FAILED stages: ${FAILED[*]} (re-run the same command to retry)"; fi
if (( ${#SKIPPED[@]} )); then say "SKIPPED stages: ${SKIPPED[*]}"; fi
if (( ${#FAILED[@]} == 0 && ${#SKIPPED[@]} == 0 )); then
  say "DONE: baseline(s) $NAMES complete - tables: reports/generated/baseline_tables.md"
fi
