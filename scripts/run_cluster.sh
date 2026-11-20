#!/usr/bin/env bash
# Multi-server experiment: smart router (step 1) + session-aware caching (step 2). One setup per command.
#
#   scripts/run_cluster.sh S2       # run FIRST. Smart router. Real agents fix the bugs (their requests are
#                                   #   recorded), then those exact requests are replayed.
#   scripts/run_cluster.sh S1       # round-robin router: real agents + replay of S2's recorded requests
#   scripts/run_cluster.sh S3       # smart router + session-aware cache: real agents + replay
#   scripts/run_cluster.sh all      # S2, then S1, then S3
#   scripts/run_cluster.sh report   # rebuild the reports from the raw results
#
# Options: --run NAME     result-set name (default run1). A new name starts a fresh, separate result set and
#                         never touches earlier ones; the same name resumes where it stopped.
#          --tiers LIST   manifest tiers, default 0,1,2,3 = all 1,000 episodes (tier 0 = first 50, 1 = next 50,
#                         2 = next 400, 3 = last 500). Tiers run in order and each finished tier is kept.
#          --profile P    one_mac (default) or three_macs (edit configs/cluster.json first)
#          --check        preflight checks only
# Ctrl-C is safe. Completed episodes are never re-run or overwritten.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"

usage() { sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; }

STEPS=()
TIERS="0,1,2,3"
PROFILE="one_mac"
RUN="run1"
CHECK_ONLY=0
while (( $# )); do
  case "$1" in
    S1|s1) STEPS+=(S1) ;;
    S2|s2) STEPS+=(S2) ;;
    S3|s3) STEPS+=(S3) ;;
    report) STEPS+=(report) ;;
    all) STEPS+=(S2 S1 S3) ;;
    --tiers) shift; TIERS="${1:?--tiers needs a value like 0 or 0,1}" ;;
    --profile) shift; PROFILE="${1:?--profile needs a value}" ;;
    --run) shift; RUN="${1:?--run needs a name}" ;;
    --check) CHECK_ONLY=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1"; echo; usage; exit 2 ;;
  esac
  shift
done
if (( ${#STEPS[@]} == 0 )) && [[ $CHECK_ONLY == 0 ]]; then usage; exit 2; fi
if [[ ! "$RUN" =~ ^[A-Za-z0-9_-]+$ ]]; then echo "--run name may only contain letters, digits, - and _"; exit 2; fi
NAMES=""
if (( ${#STEPS[@]} )); then NAMES="$(IFS=-; echo "${STEPS[*]}")"; fi
RESULTS="results/cluster/$PROFILE/$RUN"
mkdir -p "$RESULTS" .run
ONLY_REPORT=0
[[ "${STEPS[*]:-}" == "report" ]] && ONLY_REPORT=1

# ---------------------------------------------------------------- one GPU job at a time
LOCK=.run/run_cluster.lock
BASELINE_LOCK=../agent-aware-routing/.run/run_baselines.lock
if [[ $ONLY_REPORT == 0 ]]; then
  if [[ -f $LOCK ]] && kill -0 "$(cat "$LOCK")" 2>/dev/null; then
    echo "another cluster run is active (PID $(cat "$LOCK")). Wait for it, or press Ctrl-C in its terminal."; exit 1
  fi
  if [[ -f $BASELINE_LOCK ]] && kill -0 "$(cat "$BASELINE_LOCK")" 2>/dev/null; then
    echo "a baseline run is active (PID $(cat "$BASELINE_LOCK")); the GPU is busy. Run this after it finishes."; exit 1
  fi
  if pgrep -x llama-server >/dev/null; then
    echo "a llama-server is already running (another experiment?). Stop it first: .venv/bin/python -m bench.cluster stop"
    exit 1
  fi
  echo $$ > "$LOCK"
fi

LOG="$RESULTS/run_cluster_${NAMES:-check}_$(date +%Y%m%d_%H%M%S).log"
exec > >(trap '' INT; tee -a "$LOG") 2>&1
say() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
FAILED=()
SKIPPED=()
caffeinate -is -w $$ &
release_lock() { [[ "$(cat "$LOCK" 2>/dev/null)" == "$$" ]] && rm -f "$LOCK"; }
trap release_lock EXIT
trap 'say "interrupted - progress is saved; re-run the same command to resume"; "$PY" -m bench.cluster stop >/dev/null 2>&1; exit 130' INT TERM

# ---------------------------------------------------------------- preflight
say "setups: ${NAMES:-none (check only)}  run: $RUN  tiers: $TIERS  profile: $PROFILE  (log: $LOG)"
if [[ $ONLY_REPORT == 0 ]]; then
  if ! pmset -g batt | grep -q "AC Power" && [[ "${ALLOW_BATTERY:-0}" != 1 ]]; then
    say "the Mac is on battery: plug in the charger (battery power throttles the GPU and would skew timings)"; exit 1
  fi
  [[ -x "$PY" ]] || { say "missing .venv - run: uv sync"; exit 1; }
  command -v llama-server >/dev/null || { say "llama-server not on PATH (brew install llama.cpp)"; exit 1; }
  if [[ ! -x gateway/target/release/inference-gateway ]]; then
    say "building Rust gateway"
    PATH="/opt/homebrew/opt/rustup/bin:$PATH" cargo build --release --manifest-path gateway/Cargo.toml || exit 1
  fi
  if [[ ! -x third_party/llm-router/bin/router ]]; then
    say "fetching and building llm-router"; scripts/setup_llm_router.sh || exit 1
  fi
  "$PY" - "$PROFILE" <<'EOF' || exit 1
import hashlib, json, shutil, sys
from pathlib import Path
cfg = json.loads(Path("configs/cluster.json").read_text())
if sys.argv[1] not in cfg["profiles"]:
    sys.exit(f"unknown profile {sys.argv[1]}; choose from {sorted(cfg['profiles'])}")
model = Path(cfg["model"]["path"])
if not model.exists():
    sys.exit(f"model missing: {model} (download: {cfg['model']['source']})")
h = hashlib.sha256()
with open(model, "rb") as f:
    for chunk in iter(lambda: f.read(1 << 24), b""):
        h.update(chunk)
if h.hexdigest() != cfg["model"]["sha256"]:
    sys.exit(f"model sha256 mismatch: {h.hexdigest()}")
meta = json.loads(Path("manifests/master_manifest.meta.json").read_text())
if hashlib.sha256(Path("manifests/master_manifest.jsonl").read_bytes()).hexdigest() != meta["sha256"]:
    sys.exit("manifest digest mismatch - the master manifest must stay immutable")
free_gb = shutil.disk_usage(".").free / 1e9
if free_gb < 15:
    sys.exit(f"only {free_gb:.1f} GB free disk (session cache files need room)")
servers = ", ".join(f"{s['id']}@{s['host']}" for s in cfg["profiles"][sys.argv[1]]["servers"])
print(f"model ok, manifest ok ({meta['sha256'][:12]}), {free_gb:.0f} GB free, servers: {servers}")
EOF
  git diff --quiet HEAD -- agent bench faultlab miniissuetracker gateway/src configs manifests scripts 2>/dev/null \
    || say "WARNING: code differs from the last commit (recorded in every run.json)"
fi
if [[ $CHECK_ONLY == 1 ]]; then say "preflight passed (--check: nothing run)"; exit 0; fi

# ---------------------------------------------------------------- stages
refresh_report() {  # [--snapshot]
  "$PY" -m bench.cluster_report --profile "$PROFILE" --run "$RUN" "$@" >/dev/null 2>&1 \
    && say "    report: reports/generated/cluster_${PROFILE}_${RUN}_tables.md"
}
run_stage() {  # name, command...
  local name="$1"; shift
  say "=== START $name"
  local t0=$SECONDS
  if "$@"; then say "=== DONE  $name in $(( (SECONDS - t0) / 60 )) min"
  else say "=== FAILED $name (exit $?)"; FAILED+=("$name"); fi
  refresh_report
}
recording_ready() {  # tier -> 0 if S2's end-to-end run (the recording) for that tier is complete in this run
  "$PY" -c "import json,sys; m=json.load(open('$RESULTS/S2/e2e/tier$1/run.json')); sys.exit(0 if m['status']=='complete' else 1)" 2>/dev/null
}
run_setup() {  # setup: for each tier in order, the real-agent run, then the replay of S2's recorded requests
  local s="$1" t
  for t in ${TIERS//,/ }; do
    run_stage "$s tier$t: real agents" "$PY" -m bench.cluster_run --setup "$s" --tiers "$t" --profile "$PROFILE" --run "$RUN"
    if recording_ready "$t"; then
      run_stage "$s tier$t: replay" "$PY" -m bench.cluster_replay --setup "$s" --tiers "$t" --profile "$PROFILE" --run "$RUN"
    else
      say "=== SKIP   $s tier$t: replay needs S2's tier$t run first (scripts/run_cluster.sh S2 --run $RUN); re-run this command afterwards"
      SKIPPED+=("$s tier$t replay")
    fi
  done
}

for step in "${STEPS[@]}"; do
  case "$step" in
    S1|S2|S3) run_setup "$step" ;;
    report) "$PY" -m bench.cluster_report --profile "$PROFILE" && say "reports rebuilt for every run" ;;
  esac
done

if [[ $ONLY_REPORT == 0 ]]; then
  "$PY" -m bench.cluster stop >/dev/null 2>&1
  refresh_report --snapshot
fi
if (( ${#FAILED[@]} )); then say "finished with FAILED stages: ${FAILED[*]} (re-run the same command to retry)"; fi
if (( ${#SKIPPED[@]} )); then say "SKIPPED stages: ${SKIPPED[*]}"; fi
if (( ${#FAILED[@]} == 0 && ${#SKIPPED[@]} == 0 )); then
  say "DONE: ${NAMES} (run $RUN) - report: reports/generated/cluster_${PROFILE}_${RUN}_tables.md"
fi
