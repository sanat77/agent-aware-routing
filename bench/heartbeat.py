"""Progress lines for long runs: a 'still running' line every minute with live counts from the gateways and
the agents' event log, so a quiet terminal never looks stuck."""
import json
import os
import threading
import time
from pathlib import Path

import httpx

from .util import say


def last_event(events_path):
    """(age_s, description) of the newest line in an events.jsonl file (reads only the tail)."""
    p = Path(events_path)
    if not p.exists():
        return None, "no agent activity yet"
    with open(p, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - 4096))
        lines = f.read().decode(errors="replace").strip().splitlines()
    for line in reversed(lines):
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        what = ev.get("kind", "?")
        if what == "tool_call":
            what = f"tool {ev.get('tool')}"
        elif what == "model_call":
            what = f"model call (step {ev.get('step')}, {ev.get('role') or 'agent'})"
        elif what == "lifecycle":
            what = f"{ev.get('event')} {ev.get('role') or ''}".strip()
        return time.time() - ev.get("t", time.time()), f"{ev.get('episode_id')} {what}"
    return None, "no agent activity yet"


def gateway_summary(info):
    parts = []
    for si in info.get("servers", []):
        try:
            d = httpx.get(f"{si['gateway_url']}/gateway/stats", timeout=3).json()
            occ = d.get("occupancy") or {}
            busy = sum(1 for s in occ.get("slots", []) if s.get("busy"))
            parts.append(f"{si['id']}: {d['aggregates']['requests']} requests, {d.get('in_flight', 0)} in flight, "
                         f"{len(occ.get('slots', []))} slots")
            _ = busy
        except (httpx.HTTPError, KeyError, ValueError):
            parts.append(f"{si['id']}: not responding")
    return "; ".join(parts)


class Heartbeat:
    def __init__(self, label, info, done_fn, total, events_path=None, interval=60):
        self.label, self.info, self.done_fn, self.total = label, info, done_fn, total
        self.events_path, self.interval = events_path, interval
        self.t0 = time.time()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.wait(self.interval):
            try:
                elapsed = (time.time() - self.t0) / 60
                line = f"[{self.label}] still running ({elapsed:.0f} min): {self.done_fn()}/{self.total} done | " \
                       f"{gateway_summary(self.info)}"
                if self.events_path:
                    age, what = last_event(self.events_path)
                    line += f" | last agent activity: {what}" + (f" ({age:.0f}s ago)" if age is not None else "")
                say(line)
            except Exception as exc:  # noqa: BLE001 - progress output must never break a run
                say(f"[{self.label}] heartbeat error: {exc!r}")
