"""Provenance recorded in every run.json: git commit, dirty state of frozen paths, invocation history."""
import json
import os
import signal
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FROZEN_PATHS = ["agent", "bench", "faultlab", "miniissuetracker", "gateway/src", "gateway/Cargo.toml",
                "configs", "manifests", "scripts"]


def git_info():
    def run(*args):
        try:
            return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None
    dirty = run("status", "--porcelain", "--", *FROZEN_PATHS)
    return {"commit": run("rev-parse", "HEAD"), "tag": run("describe", "--tags", "--always"),
            "frozen_paths_dirty": bool(dirty), "dirty_files": (dirty or "").splitlines()[:20]}


def write_run_json(path, meta, invocation_wall_s):
    """Accumulate wall time and invocation history across resumed runs."""
    path = Path(path)
    prev = {}
    if path.exists():
        try:
            prev = json.loads(path.read_text())
        except json.JSONDecodeError:
            prev = {}
    invocations = prev.get("invocations", [])
    invocations.append({"ended_at": time.time(), "wall_s": invocation_wall_s, "git": git_info(),
                        "status": meta.get("status")})
    meta = dict(meta)
    meta["wall_s"] = sum(i["wall_s"] for i in invocations)
    meta["invocations"] = invocations
    meta["git"] = invocations[-1]["git"]
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, indent=1, default=str))
    os.replace(tmp, path)
    return meta


def install_termination_handler(finalize):
    """On SIGTERM/SIGINT: record the interrupted invocation (finalize) and exit at once.

    os._exit stops worker threads immediately, so no in-flight episode can be recorded as a failure caused by the
    shutdown; those episodes are simply re-run on resume. The caller's shell stops the inference stack afterwards.
    """
    def handler(signum, frame):
        try:
            finalize("interrupted")
            print(f"received signal {signum}; progress saved, exiting (re-run to resume)", flush=True)
        except BaseException:  # noqa: BLE001 - e.g. BrokenPipeError when the terminal's tee is already gone
            pass
        finally:
            os._exit(128 + signum)
    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)
