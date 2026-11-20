"""Start/stop the multi-server stack for one setup (S1/S2/S3):

    agents -> llm-router -> gateway(w0) -> llama-server(w0)
                         -> gateway(w1) -> llama-server(w1)   (local process, or a remote Mac over SSH)

Gateways always run on the controller Mac (this machine) and talk to each llama-server over HTTP.

CLI:  python -m bench.cluster start S2 [--profile one_mac] [--log-dir DIR]  |  python -m bench.cluster stop
"""
import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / ".run" / "cluster"
CLUSTER = json.loads((ROOT / "configs" / "cluster.json").read_text())
LOCAL_HOSTS = {"127.0.0.1", "localhost"}


def _is_local(server):
    return not server.get("ssh") and server["host"] in LOCAL_HOSTS


def _wait(url, proc=None, timeout=240):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if proc is not None and proc.poll() is not None:
            raise RuntimeError(f"process for {url} exited with code {proc.returncode}")
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return time.time() - t0
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise TimeoutError(url)


def _kill(pid):
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(40):
            os.kill(pid, 0)
            time.sleep(0.25)
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _ssh(server, command):
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", server["ssh"], command],
                          capture_output=True, text=True, timeout=60)


def stop():
    RUN.mkdir(parents=True, exist_ok=True)
    for pid_file in sorted(RUN.glob("*.pid")):
        try:
            _kill(int(pid_file.read_text()))
        except ValueError:
            pass
        pid_file.unlink(missing_ok=True)
    remote = RUN / "remote.json"
    if remote.exists():
        for server in json.loads(remote.read_text()):
            _ssh(server, f"pkill -f 'llama-server.*--port {server['llama_port']}' || true")
        remote.unlink()


def _llama_args(server, slot_dir):
    ls = CLUSTER["llama_server"]
    model = CLUSTER["model"]["path"]
    return [ls["binary"], "-m", model, *ls["common_args"], "-c", str(server["ctx"]), "-np", str(server["np"]),
            "--cache-ram", str(server["cache_ram_mib"]), "--slot-save-path", slot_dir,
            "--host", "127.0.0.1" if _is_local(server) else "0.0.0.0", "--port", str(server["llama_port"])]


def start(setup_name, log_dir, run_id="cluster", profile="one_mac"):
    stop()
    setup = CLUSTER["setups"][setup_name]
    servers = CLUSTER["profiles"][profile]["servers"]
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    RUN.mkdir(parents=True, exist_ok=True)
    info = {"setup": setup_name, "profile": profile, "policy": setup["gateway_policy"],
            "router_strategy": setup["router_strategy"], "servers": [], "started_at": time.time()}
    remote = []
    procs = {}
    # 1. llama-servers
    for s in servers:
        if _is_local(s):
            slot_dir = str(RUN / "slots" / s["id"])
            Path(slot_dir).mkdir(parents=True, exist_ok=True)
            for f in Path(slot_dir).glob("*.bin"):
                f.unlink()
            args = _llama_args(s, slot_dir)
            log = open(log_dir / f"llama-server_{s['id']}.log", "a")
            p = subprocess.Popen(args, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            (RUN / f"llama_{s['id']}.pid").write_text(str(p.pid))
            procs[s["id"]] = p
        else:
            repo = s.get("remote_repo", "~/agent-aware-routing-session-cache")
            slot_dir = f"{repo}/.run/cluster/slots/{s['id']}"
            args = _llama_args(s, slot_dir)
            cmd = (f"cd {repo} && mkdir -p {shlex.quote(slot_dir)} .run && rm -f {shlex.quote(slot_dir)}/*.bin; "
                   f"nohup {' '.join(shlex.quote(a) for a in args)} > .run/llama-server_{s['id']}.log 2>&1 &")
            r = _ssh(s, cmd)
            if r.returncode != 0:
                raise RuntimeError(f"ssh start failed for {s['id']}: {r.stderr.strip()}")
            remote.append(s)
            (RUN / "remote.json").write_text(json.dumps(remote))
    for s in servers:
        url = f"http://{s['host']}:{s['llama_port']}"
        startup = _wait(f"{url}/health", procs.get(s["id"]))
        props = httpx.get(f"{url}/props", timeout=5).json()
        if props.get("build_info") != CLUSTER["llama_server"]["expected_build"]:
            print(f"WARNING: {s['id']} llama-server build {props.get('build_info')} differs from the frozen build",
                  file=sys.stderr)
        info["servers"].append({"id": s["id"], "llama_url": url, "llama_pid": procs[s["id"]].pid if s["id"] in procs else None,
                                "local": _is_local(s), "np": props.get("total_slots"), "ctx": s["ctx"],
                                "n_ctx_per_slot": props.get("default_generation_settings", {}).get("n_ctx"),
                                "model_startup_s": startup, "build_info": props.get("build_info")})
    # 2. one gateway per server (on this machine)
    gw = CLUSTER["gateway"]
    for s, si in zip(servers, info["servers"]):
        listen = f"127.0.0.1:{s['gateway_port']}"
        args = [str(ROOT / gw["binary"]), "--listen", listen, "--upstream", si["llama_url"],
                "--policy", setup["gateway_policy"], "--n-slots", str(s["np"]), "--server-id", s["id"],
                "--log-dir", str(log_dir / f"gateway_{s['id']}"), "--run-id", run_id,
                "--public-url", f"http://{listen}", "--save-budget-mb", str(gw["save_budget_mb"])]
        if _is_local(s):
            args += ["--slot-save-dir", str(RUN / "slots" / s["id"])]
        log = open(log_dir / f"gateway_{s['id']}.log", "a")
        p = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        (RUN / f"gateway_{s['id']}.pid").write_text(str(p.pid))
        _wait(f"http://{listen}/health", p, timeout=30)
        si["gateway_url"] = f"http://{listen}"
        si["gateway_pid"] = p.pid
    # 3. llm-router
    rc = CLUSTER["router"]
    saturation = rc.get("saturation_inflight") or min(s["np"] for s in servers)
    lines = ["server:", f"  addr: \"127.0.0.1:{rc['port']}\"", "  read_timeout: 60s", "  write_timeout: 0s",
             "  shutdown_timeout: 10s", "router:", f"  strategy: {setup['router_strategy']}",
             f"  chunk_size: {rc['chunk_size']}", f"  min_match_chunks: {rc['min_match_chunks']}",
             f"  saturation_inflight: {saturation}", "workers:"]
    for s, si in zip(servers, info["servers"]):
        lines += [f"  - id: {s['id']}", f"    url: {si['gateway_url']}", f"    kv_budget: {s['ctx'] // 4}",
                  "    max_inflight: 0", f"    timeout: {rc['worker_timeout']}"]
    lines += ["logging:", "  level: info", "  format: json", "metrics:", "  enabled: true",
              f"  addr: \"127.0.0.1:{rc['metrics_port']}\""]
    cfg_path = log_dir / "router.yaml"
    cfg_path.write_text("\n".join(lines) + "\n")
    binary = ROOT / rc["binary"]
    if not binary.exists():
        raise FileNotFoundError(f"{binary} missing: run scripts/setup_llm_router.sh")
    log = open(log_dir / "router.log", "a")
    p = subprocess.Popen([str(binary), "--config", str(cfg_path)], stdout=log, stderr=subprocess.STDOUT,
                         start_new_session=True)
    (RUN / "router.pid").write_text(str(p.pid))
    _wait(f"http://127.0.0.1:{rc['port']}/healthz", p, timeout=30)
    info.update(router_url=f"http://127.0.0.1:{rc['port']}", router_pid=p.pid,
                router_metrics_url=f"http://127.0.0.1:{rc['metrics_port']}/metrics",
                router_commit=_router_commit(), router_saturation_inflight=saturation,
                total_slots=sum(si["np"] for si in info["servers"]),
                n_ctx_per_slot=min(si["n_ctx_per_slot"] for si in info["servers"]),
                model_startup_s=max(si["model_startup_s"] for si in info["servers"]))
    (log_dir / "stack.json").write_text(json.dumps(info, indent=1))
    return info


def _router_commit():
    try:
        return subprocess.run(["git", "-C", str(ROOT / "third_party" / "llm-router"), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def collect_stats(info):
    """Final per-server gateway counters and router metrics (best effort)."""
    out = {"gateways": {}, "router_metrics": None}
    for si in info["servers"]:
        try:
            out["gateways"][si["id"]] = httpx.get(f"{si['gateway_url']}/gateway/stats", timeout=5).json()
        except httpx.HTTPError:
            pass
    try:
        out["router_metrics"] = httpx.get(info["router_metrics_url"], timeout=5).text
    except httpx.HTTPError:
        pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["start", "stop"])
    ap.add_argument("setup", nargs="?")
    ap.add_argument("--profile", default="one_mac")
    ap.add_argument("--log-dir", default=str(RUN / "manual"))
    args = ap.parse_args()
    if args.cmd == "stop":
        stop()
        print("stopped")
    else:
        print(json.dumps(start(args.setup, args.log_dir, profile=args.profile), indent=1))


if __name__ == "__main__":
    main()
