#!/usr/bin/env bash
# Start/stop a detached llama-server instance with a named profile.
# Usage: scripts/llama_ctl.sh start <profile> [extra llama-server args...]
#        scripts/llama_ctl.sh stop
#        scripts/llama_ctl.sh status
# Profiles live in configs/llama_profiles/<profile>.env
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$ROOT/.run"
mkdir -p "$RUN_DIR"
PID_FILE="$RUN_DIR/llama-server.pid"
LOG_FILE="$RUN_DIR/llama-server.log"

cmd="${1:-status}"; shift || true

is_running() { [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; }

case "$cmd" in
  start)
    profile="${1:?profile required}"; shift || true
    if is_running; then echo "already running (pid $(cat "$PID_FILE"))"; exit 1; fi
    # shellcheck disable=SC1090
    source "$ROOT/configs/llama_profiles/$profile.env"
    : "${MODEL:?}" "${LLAMA_PORT:=8090}" "${CTX:=32768}" "${NP:=4}"
    args=(-m "$ROOT/$MODEL" -ngl 99 -fa on -c "$CTX" -np "$NP" --metrics --slots
          --jinja --host 127.0.0.1 --port "$LLAMA_PORT" --seed 1234
          -t "${THREADS:-4}")
    # shellcheck disable=SC2206
    args+=(${PROFILE_ARGS:-})
    args+=("$@")
    echo "$(date -u +%FT%TZ) profile=$profile args=${args[*]}" > "$RUN_DIR/llama-server.cmd"
    nohup llama-server "${args[@]}" > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    t0=$(python3 -c 'import time;print(time.time())')
    for _ in $(seq 1 240); do
      if curl -sf "http://127.0.0.1:$LLAMA_PORT/health" >/dev/null 2>&1; then
        t1=$(python3 -c 'import time;print(time.time())')
        python3 -c "print(f'ready startup_s={$t1-$t0:.2f}')" | tee "$RUN_DIR/llama-server.startup"
        exit 0
      fi
      is_running || { echo "llama-server exited"; tail -30 "$LOG_FILE"; exit 1; }
      sleep 0.5
    done
    echo "timeout waiting for llama-server"; exit 1 ;;
  stop)
    if is_running; then kill "$(cat "$PID_FILE")"; sleep 1; kill -9 "$(cat "$PID_FILE")" 2>/dev/null || true; fi
    rm -f "$PID_FILE"; echo stopped ;;
  status)
    if is_running; then echo "running pid $(cat "$PID_FILE")"; cat "$RUN_DIR/llama-server.cmd"; else echo "not running"; fi ;;
  *) echo "unknown command $cmd"; exit 2 ;;
esac
