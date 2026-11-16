"""Start/stop the inference stack (llama-server + Rust gateway) for one experimental configuration.

CLI:  python -m bench.stack start <config> [--log-dir DIR]   |   python -m bench.stack stop
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / ".run"
EXPERIMENTS = json.loads((ROOT / "configs" / "experiments.json").read_text())


def _wait_health(url, proc, timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if proc.poll() is not None:
            raise RuntimeError(f"process exited early with code {proc.returncode}")
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return time.time() - t0
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise TimeoutError(url)


def _kill_pidfile(name):
    pid_file = RUN / f"{name}.pid"
    if not pid_file.exists():
        return
    pid = int(pid_file.read_text())
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(40):
            os.kill(pid, 0)
            time.sleep(0.25)
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    pid_file.unlink(missing_ok=True)


def stop():
    _kill_pidfile("gateway")
    _kill_pidfile("llama-server")


def start(config_name, log_dir, run_id="run", policy_override=None, gateway_extra=()):
    stop()
    RUN.mkdir(exist_ok=True)
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    exp = EXPERIMENTS
    cfg = exp["configs"][config_name]
    ls = exp["llama_server"]
    llama_args = [ls["binary"], "-m", str(ROOT / exp["model"]["path"]), *ls["common_args"],
                  *cfg["llama_extra"], "--host", "127.0.0.1", "--port", str(ls["port"])]
    llama_log = open(log_dir / "llama-server.log", "a")
    llama = subprocess.Popen(llama_args, stdout=llama_log, stderr=subprocess.STDOUT, start_new_session=True)
    (RUN / "llama-server.pid").write_text(str(llama.pid))
    llama_startup = _wait_health(f"http://127.0.0.1:{ls['port']}/health", llama)
    props = httpx.get(f"http://127.0.0.1:{ls['port']}/props", timeout=5).json()
    gw = exp["gateway"]
    policy = policy_override or cfg["gateway_policy"]
    gw_args = [str(ROOT / gw["binary"]), "--listen", f"127.0.0.1:{gw['port']}",
               "--upstream", f"http://127.0.0.1:{ls['port']}", "--policy", policy,
               "--n-slots", str(ls["n_slots"]), "--log-dir", str(log_dir / "gateway"), "--run-id", run_id,
               *gateway_extra]
    gw_log = open(log_dir / "gateway.log", "a")
    gateway = subprocess.Popen(gw_args, stdout=gw_log, stderr=subprocess.STDOUT, start_new_session=True)
    (RUN / "gateway.pid").write_text(str(gateway.pid))
    gw_startup = _wait_health(f"http://127.0.0.1:{gw['port']}/health", gateway, timeout=30)
    info = {
        "config": config_name, "policy": policy, "llama_args": llama_args, "gateway_args": gw_args,
        "llama_pid": llama.pid, "gateway_pid": gateway.pid, "model_startup_s": llama_startup,
        "gateway_startup_s": gw_startup, "build_info": props.get("build_info"),
        "total_slots": props.get("total_slots"), "n_ctx_per_slot": props.get("default_generation_settings", {}).get("n_ctx"),
        "gateway_url": f"http://127.0.0.1:{gw['port']}", "llama_url": f"http://127.0.0.1:{ls['port']}",
        "started_at": time.time(),
    }
    if props.get("build_info") != ls["expected_build"]:
        print(f"WARNING: llama-server build {props.get('build_info')} != frozen {ls['expected_build']}", file=sys.stderr)
    starts = []
    if (log_dir / "stack.json").exists():
        try:
            prev = json.loads((log_dir / "stack.json").read_text())
            starts = prev.get("previous_starts", []) + [{k: prev.get(k) for k in ("started_at", "model_startup_s")}]
        except json.JSONDecodeError:
            pass
    info["previous_starts"] = starts
    (log_dir / "stack.json").write_text(json.dumps(info, indent=1))
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["start", "stop"])
    ap.add_argument("config", nargs="?")
    ap.add_argument("--log-dir", default=str(RUN / "manual"))
    ap.add_argument("--policy", default=None)
    args = ap.parse_args()
    if args.cmd == "stop":
        stop()
        print("stopped")
    else:
        print(json.dumps(start(args.config, args.log_dir, policy_override=args.policy), indent=1))


if __name__ == "__main__":
    main()
