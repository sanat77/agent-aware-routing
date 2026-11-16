"""Background sampler: process RSS (llama-server, gateway, benchmark process) and llama-server slot state.

Writes JSONL samples to <log_dir>/monitor.jsonl every `interval` seconds.
Slot occupancy comes from GET /slots (is_processing, n_prompt_tokens). llama.cpp b11669 exposes no
KV-cells-used gauge, so KV occupancy is reported as an estimate: sum(slot n_prompt_tokens) / n_ctx.
"""
import json
import os
import subprocess
import threading
import time
from pathlib import Path

import httpx
import psutil


class Monitor:
    def __init__(self, log_dir, llama_url, pids, interval=0.5):
        self.path = Path(log_dir) / "monitor.jsonl"
        self.llama_url = llama_url
        self.pids = dict(pids)
        self.pids.setdefault("bench", os.getpid())
        self.interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.peak_rss = {k: 0 for k in self.pids}
        self.samples = 0

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=5)

    def _rss(self):
        out = {}
        for name, pid in self.pids.items():
            try:
                p = psutil.Process(pid)
                rss = p.memory_info().rss
                if name == "bench":
                    rss += sum(c.memory_info().rss for c in p.children(recursive=True)
                               if c.pid not in self.pids.values())
                out[name] = rss
            except psutil.Error:
                out[name] = None
        return out

    def _power(self):
        """Power source and thermal notes from pmset (sampled once a minute)."""
        out = {}
        try:
            batt = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=5).stdout
            out["on_ac_power"] = "AC Power" in batt
            out["battery"] = batt.splitlines()[1].strip() if len(batt.splitlines()) > 1 else None
            therm = subprocess.run(["pmset", "-g", "therm"], capture_output=True, text=True, timeout=5).stdout
            out["thermal"] = " | ".join(l.strip() for l in therm.splitlines() if l.strip())
        except (OSError, subprocess.SubprocessError):
            pass
        return out

    def _run(self):
        client = httpx.Client(timeout=2.0)
        last_power = 0.0
        with open(self.path, "a") as f:
            while not self._stop.is_set():
                t = time.time()
                rss = self._rss()
                for k, v in rss.items():
                    if v:
                        self.peak_rss[k] = max(self.peak_rss[k], v)
                slots = None
                try:
                    data = client.get(f"{self.llama_url}/slots").json()
                    slots = [{"id": s["id"], "busy": bool(s.get("is_processing")),
                              "n_prompt_tokens": s.get("n_prompt_tokens"), "n_ctx": s.get("n_ctx"),
                              "id_task": s.get("id_task")} for s in data]
                except (httpx.HTTPError, ValueError, KeyError, TypeError):
                    pass
                row = {"t": t, "rss": rss, "slots": slots}
                if t - last_power >= 60:
                    row["power"] = self._power()
                    last_power = t
                f.write(json.dumps(row) + "\n")
                f.flush()
                self.samples += 1
                self._stop.wait(self.interval)
