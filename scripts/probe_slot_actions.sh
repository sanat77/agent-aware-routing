#!/usr/bin/env bash
# Start a throw-away llama-server with --slot-save-path, run scripts/probe_slot_actions.py, stop it.
# Refuses to run while a baseline or another llama-server is using the GPU.
set -uo pipefail
cd "$(dirname "$0")/.."
LOCK=../agent-aware-routing/.run/run_baselines.lock
if [[ -f $LOCK ]] && kill -0 "$(cat "$LOCK")" 2>/dev/null; then echo "baseline run active - not probing"; exit 1; fi
if pgrep -x llama-server >/dev/null; then echo "a llama-server is already running - not probing"; exit 1; fi
PORT=8190
mkdir -p .run/slots
llama-server -m models/Qwen3-4B-Instruct-2507-Q4_K_M.gguf -ngl 99 -fa on -c 16384 -np 2 -ctk q8_0 -ctv q8_0 \
  --metrics --slots --jinja -lv 4 --seed 1234 -t 4 --cache-ram 2048 --slot-save-path "$PWD/.run/slots" \
  --host 127.0.0.1 --port $PORT > .run/probe_llama.log 2>&1 &
PID=$!
trap 'kill $PID 2>/dev/null' EXIT
for _ in $(seq 1 120); do curl -sf "http://127.0.0.1:$PORT/health" >/dev/null && break; sleep 0.5; done
.venv/bin/python scripts/probe_slot_actions.py "http://127.0.0.1:$PORT"
ls -la .run/slots
grep -iE "slot_save|slot_restore|erase|saved|restored" .run/probe_llama.log | head -8
