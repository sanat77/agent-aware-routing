"""Run one agent session (episode) end to end: workspace -> LangGraph agent -> hidden evaluation.

Produces
  * <out_dir>/episodes/<episode_id>.json      per-episode result + metadata
  * <out_dir>/traces/<episode_id>.jsonl.gz    serialized inference requests (for trace replay)
  * <out_dir>/events.jsonl                    agent-side event stream (appended, thread-safe)
"""
import gzip
import json
import os
import shutil
import threading
import time
from pathlib import Path

from langgraph.types import Command

from faultlab.injector import build_workspace, evaluate

from .graph import SessionContext, build_graph
from .llm import GatewayClient
from .prompts import ACTION_SCHEMA_SHA, SYSTEM_PROMPT_SHA
from .tools import RepoTools

_EVENT_LOCK = threading.Lock()
# Set when the benchmark is being shut down: in-flight episodes must not be recorded (they are re-run on resume).
ABORT = threading.Event()


class Recorder:
    def __init__(self, episode, out_dir, run_id, config_name):
        self.episode = episode
        self.out_dir = Path(out_dir)
        self.run_id = run_id
        self.config_name = config_name
        self.model_calls = []
        self.tool_calls = []
        self.waits = []
        self.errors = []
        self.trace = []
        self._last_response_t = None
        self._pending_wait = 0.0
        self.t0 = time.time()

    def _event(self, kind, **fields):
        rec = {"t": time.time(), "run_id": self.run_id, "config": self.config_name,
               "episode_id": self.episode["episode_id"], "session_id": self.episode["session_id"],
               "kind": kind, **fields}
        with _EVENT_LOCK, open(self.out_dir / "events.jsonl", "a") as f:
            f.write(json.dumps(rec) + "\n")

    def model_call(self, step, prompt, n_predict, response):
        now = time.time()
        timings = response.get("timings") or {}
        gw = response.get("gateway") or {}
        sent_at = now - response.get("client_latency_ms", 0) / 1000
        gap = None if self._last_response_t is None else sent_at - self._last_response_t
        rec = {
            "step": step, "request_id": response.get("request_id"), "sent_offset_s": sent_at - self.t0,
            "gap_since_prev_response_s": gap, "client_latency_ms": response.get("client_latency_ms"),
            "attempts": response.get("attempts"), "served_slot": response.get("id_slot"),
            "prompt_chars": len(prompt), "prompt_n": timings.get("prompt_n"), "cache_n": timings.get("cache_n"),
            "prompt_ms": timings.get("prompt_ms"), "predicted_n": timings.get("predicted_n"),
            "predicted_ms": timings.get("predicted_ms"), "stop_type": response.get("stop_type"),
            "ttft_ms": gw.get("ttft_ms"), "gateway_queue_ms": gw.get("gateway_queue_ms"),
            "est_upstream_queue_ms": gw.get("est_upstream_queue_ms"),
            "routing_decision_us": gw.get("routing_decision_us"), "gateway_overhead_ms": gw.get("gateway_overhead_ms"),
            "decision_reason": gw.get("decision_reason"), "requested_slot": gw.get("requested_slot"),
        }
        self.model_calls.append(rec)
        self.trace.append({"step": step, "request_id": rec["request_id"], "sent_offset_s": rec["sent_offset_s"],
                           "gap_since_prev_response_s": gap, "tool_wait_before_s": self._pending_wait,
                           "prompt": prompt, "n_predict": n_predict,
                           "schema_sha": ACTION_SCHEMA_SHA, "recorded_content": response.get("content", ""),
                           "recorded_predicted_n": timings.get("predicted_n"),
                           "recorded_prompt_tokens": (timings.get("prompt_n") or 0) + (timings.get("cache_n") or 0)})
        self._pending_wait = 0.0
        self._last_response_t = now
        self._event("model_call", **rec)

    def model_error(self, step, error):
        self.errors.append({"step": step, "error": error})
        self._event("model_error", step=step, error=error)

    def tool(self, name, args, ok, seconds, origin, output_chars):
        rec = {"tool": name, "ok": ok, "seconds": seconds, "origin": origin, "output_chars": output_chars,
               "args_keys": sorted(args)}
        self.tool_calls.append(rec)
        self._event("tool_call", **rec)

    def wait(self, seconds):
        self.waits.append(seconds)
        self._pending_wait += seconds
        self._event("tool_wait", seconds=seconds)


def run_episode(episode, *, out_dir, gateway_url, run_id, config_name, workspace_root, options,
                keep_workspace=False, scheduled_start=None):
    out_dir = Path(out_dir)
    (out_dir / "episodes").mkdir(parents=True, exist_ok=True)
    (out_dir / "traces").mkdir(parents=True, exist_ok=True)
    ws = Path(workspace_root) / episode["episode_id"]
    if ws.exists():
        shutil.rmtree(ws)
    t_start = time.time()
    build_workspace(episode["bug_category"], episode["bug_variation"], ws)
    client = GatewayClient(gateway_url)
    recorder = Recorder(episode, out_dir, run_id, config_name)
    tools = RepoTools(ws)
    ctx = SessionContext(episode=episode, tools=tools, client=client, recorder=recorder, options=options)
    graph = build_graph(ctx)
    cfg = {"configurable": {"thread_id": episode["session_id"]}, "recursion_limit": 400}
    client.event(episode["session_id"], "session_start", episode_id=episode["episode_id"],
                 workload=episode["workload"])
    state = None
    interrupts = 0
    resume_latencies = []
    crash = None
    try:
        result = graph.invoke({"messages": []}, cfg)
        while "__interrupt__" in result:
            interrupts += 1
            wait_s = result["__interrupt__"][0].value["wait_s"]
            t_pause = time.time()
            time.sleep(wait_s)  # session is checkpointed and idle while the "tool" runs
            t_resume = time.time()
            result = graph.invoke(Command(resume={"waited_ms": (t_resume - t_pause) * 1000}), cfg)
            resume_latencies.append(t_resume)
        state = result
    except Exception as exc:  # noqa: BLE001
        crash = f"{type(exc).__name__}: {exc}"
        snap = graph.get_state(cfg)
        state = dict(snap.values) if snap else {}
    t_agent_done = time.time()
    if ABORT.is_set():
        client.close()
        return {"episode_id": episode["episode_id"], "workload": episode["workload"], "status": "aborted"}
    status = (state or {}).get("status", "failed") if not crash else "failed"
    outcome = (state or {}).get("outcome", "crash" if crash else "unknown")
    client.event(episode["session_id"], "completed" if status == "completed" else "failed", outcome=outcome)
    diff = tools.diff_full()
    evaluation = evaluate(ws, episode["bug_category"], episode["bug_variation"])
    t_end = time.time()

    # Session-resumption latency: time from resuming after a tool wait to the first token of the next call.
    resumption = []
    calls = recorder.model_calls
    for t_res in resume_latencies:
        nxt = [c for c in calls if c["sent_offset_s"] + recorder.t0 >= t_res - 0.05]
        if nxt and nxt[0].get("ttft_ms") is not None:
            c = nxt[0]
            resumption.append((c["sent_offset_s"] + recorder.t0 - t_res) * 1000 + c["ttft_ms"])

    result = {
        "run_id": run_id, "config": config_name, "episode_id": episode["episode_id"],
        "session_id": episode["session_id"], "workload": episode["workload"],
        "bug_category": episode["bug_category"], "bug_variation": episode["bug_variation"],
        "fault_id": episode.get("fault_id"), "status": status, "outcome": outcome, "crash": crash,
        "scheduled_start": scheduled_start, "started_at": t_start,
        "session_wait_s": None if scheduled_start is None else max(0.0, t_start - scheduled_start),
        "agent_latency_s": t_agent_done - t_start, "total_latency_s": t_end - t_start,
        "evaluation_s": t_end - t_agent_done,
        "model_calls": len(calls), "tool_calls": len([t for t in recorder.tool_calls if t["origin"] == "agent"]),
        "tool_calls_ok": len([t for t in recorder.tool_calls if t["origin"] == "agent" and t["ok"]]),
        "tool_seconds": sum(t["seconds"] for t in recorder.tool_calls),
        "tool_wait_seconds": sum(recorder.waits), "interrupts": interrupts,
        "resumption_latency_ms": resumption,
        "model_errors": recorder.errors,
        "input_tokens": sum((c["prompt_n"] or 0) + (c["cache_n"] or 0) for c in calls),
        "cached_tokens": sum(c["cache_n"] or 0 for c in calls),
        "recomputed_tokens": sum(c["prompt_n"] or 0 for c in calls),
        "output_tokens": sum(c["predicted_n"] or 0 for c in calls),
        "final_summary": (state or {}).get("final_summary", ""),
        "diff": diff[:20000], "evaluation": evaluation,
        "calls": calls, "tools": recorder.tool_calls,
        "prompt_versions": {"system_prompt_sha": SYSTEM_PROMPT_SHA, "action_schema_sha": ACTION_SCHEMA_SHA},
        "options": options,
    }
    # The trace is written first and the episode JSON last (atomically): the JSON marks the episode complete.
    if ABORT.is_set():
        client.close()
        return {"episode_id": episode["episode_id"], "workload": episode["workload"], "status": "aborted"}
    trace_path = out_dir / "traces" / f"{episode['episode_id']}.jsonl.gz"
    with gzip.open(str(trace_path) + ".tmp", "wt") as f:
        for t in recorder.trace:
            f.write(json.dumps(t) + "\n")
    os.replace(str(trace_path) + ".tmp", trace_path)
    ep_path = out_dir / "episodes" / f"{episode['episode_id']}.json"
    ep_path.with_suffix(".json.tmp").write_text(json.dumps(result, indent=1))
    os.replace(ep_path.with_suffix(".json.tmp"), ep_path)
    if not keep_workspace:
        shutil.rmtree(ws, ignore_errors=True)
    client.close()
    return result
