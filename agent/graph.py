"""LangGraph orchestration of the repository-repair agent.

Graph:  START -> bootstrap -> agent --(tool call)--> tools -> tool_wait -> agent
                                   |--(finish)-----> verify --(pass)--> END
                                                            |--(fail, budget left)--> agent
        agent --(budget / context / timeout / model error)--> END

`tool_wait` implements tool-execution pauses. In resumable mode it calls LangGraph's `interrupt()`, which
checkpoints the session (InMemorySaver, thread_id = session id) and returns control to the session runner;
the runner sleeps for the scheduled tool delay and resumes the graph with `Command(resume=...)`.
"""
import json
import operator
import time
from typing import Annotated, Any, Optional, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .helpers import run_explorer, run_reviewer
from .llm import ModelCallError
from .prompts import (ACTION_SCHEMA, SYSTEM_PROMPT, chat_messages, initial_user_message, render_chatml,
                      tool_result_message)


class AgentState(TypedDict, total=False):
    messages: list
    step: int
    tool_index: int
    pending: Optional[dict]
    pending_wait_s: float
    status: str
    outcome: str
    final_summary: str
    verify_attempts: int
    reviews: int
    last_prompt_tokens: int
    seen_calls: list
    log: Annotated[list, operator.add]


class SessionContext:
    """Per-session, non-checkpointed dependencies (tools, model client, recorders)."""

    def __init__(self, *, episode, tools, client, recorder, options):
        self.episode = episode
        self.tools = tools
        self.client = client
        self.recorder = recorder
        self.opt = options
        self.started = time.time()
        self.turns = {}

    def header(self, session_id):
        if self.opt.get("context_mode") != "rewrite_header":
            return None
        elapsed = int(time.time() - self.started)
        turn = self.turns.get(session_id, 0) + 1
        return f"[session {session_id} | nonce {self.episode['prompt_nonce']} | turn {turn} | elapsed {elapsed}s]"

    def model_call(self, *, session_id, role, step, system, messages, schema, n_predict):
        """One inference request for any agent in this episode (lead or helper). Raises ModelCallError."""
        header = self.header(session_id)
        lead = self.episode["session_id"]
        parent = None if session_id == lead else lead
        kw = dict(session_id=session_id, episode_id=self.episode["episode_id"], step=step, n_predict=n_predict,
                  json_schema=schema, parent_session_id=parent, agent_role=role)
        if self.opt.get("api") == "chat":
            payload = chat_messages(system, messages, header=header)
            try:
                resp = self.client.complete(messages=payload, **kw)
            except ModelCallError as exc:
                self.recorder.model_error(step=step, error=str(exc), session_id=session_id)
                raise
        else:
            payload = render_chatml(system, messages, header=header)
            try:
                resp = self.client.complete(payload, **kw)
            except ModelCallError as exc:
                self.recorder.model_error(step=step, error=str(exc), session_id=session_id)
                raise
        self.turns[session_id] = self.turns.get(session_id, 0) + 1
        self.recorder.model_call(step=step, prompt=payload, n_predict=n_predict, response=resp,
                                 session_id=session_id, parent_session_id=parent, role=role, schema=schema)
        return resp

    def lifecycle(self, session_id, event, parent=None, role=None, **fields):
        self.client.event(session_id, event, parent_session_id=parent, agent_role=role, **fields)
        self.recorder.lifecycle(session_id=session_id, event=event, parent=parent, role=role)


def _header(ctx, state):
    return ctx.header(ctx.episode["session_id"])


def build_graph(ctx):
    opt = ctx.opt
    max_steps = opt.get("max_steps", 12)
    n_predict = opt.get("n_predict", 512)
    ctx_limit = opt.get("ctx_tokens", 8192)
    deadline_s = opt.get("episode_timeout_s", 1200)
    delays = ctx.episode.get("tool_delays_s", [])
    visible = ctx.episode["visible_test"]
    multi = opt.get("agent_mode") == "multi"
    lead_role = "lead" if multi else None

    def run_tool(name, args, origin):
        ok, text, secs = ctx.tools.execute(name, args)
        ctx.recorder.tool(name=name, args=args, ok=ok, seconds=secs, origin=origin, output_chars=len(text))
        return ok, text

    def bootstrap(state):
        _, listing = run_tool("list_files", {"path": "."}, "bootstrap")
        test_file = visible.split("::", 1)[0]
        _, source = run_tool("read_file", {"path": test_file, "start_line": 1, "end_line": 80}, "bootstrap")
        _, test_out = run_tool("run_tests", {"target": visible}, "bootstrap")
        first = initial_user_message(ctx.episode["issue"], listing, visible, source, test_out)
        if multi:
            context = first.rsplit("\n\nStart by locating", 1)[0]
            summary, _ = run_explorer(ctx, context, 0)
            if summary:
                first = first.replace("\n\nStart by locating",
                                      f"\n\n# Explorer sub-agent findings\n{summary.strip()}\n\nStart by locating", 1)
        return {"messages": [{"role": "user", "content": first}], "step": 0, "tool_index": 0,
                "status": "running", "verify_attempts": 0, "pending": None, "pending_wait_s": 0.0,
                "seen_calls": []}

    def agent(state):
        step = state.get("step", 0)
        if step >= max_steps:
            return {"status": "failed", "outcome": "step_budget_exhausted"}
        if time.time() - ctx.started > deadline_s:
            return {"status": "failed", "outcome": "episode_timeout"}
        if state.get("last_prompt_tokens", 0) + n_predict > ctx_limit:
            return {"status": "failed", "outcome": "context_exhausted"}
        try:
            resp = ctx.model_call(session_id=ctx.episode["session_id"], role=lead_role, step=step,
                                  system=SYSTEM_PROMPT, messages=state["messages"], schema=ACTION_SCHEMA,
                                  n_predict=n_predict)
        except ModelCallError:
            return {"status": "failed", "outcome": "model_error", "step": step + 1}
        content = resp.get("content", "")
        timings = resp.get("timings") or {}
        prompt_tokens = int(timings.get("prompt_n", 0)) + int(timings.get("cache_n", 0))
        msgs = state["messages"] + [{"role": "assistant", "content": content}]
        update = {"messages": msgs, "step": step + 1,
                  "last_prompt_tokens": prompt_tokens + int(timings.get("predicted_n", 0))}
        try:
            action = json.loads(content)
            tool = action["tool"]
            args = action.get("tool_input") or {}
            if not isinstance(args, dict):
                raise ValueError("tool_input must be an object")
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            msgs.append({"role": "user", "content": tool_result_message(
                "parse", f"ERROR: your reply was not a valid tool call ({type(exc).__name__}). "
                         f"Reply with one JSON object.")})
            ctx.recorder.tool(name="<parse_error>", args={}, ok=False, seconds=0.0, origin="agent", output_chars=0)
            update["pending"] = None
            return update
        update["pending"] = {"tool": tool, "args": args, "thought": action.get("reasoning", "")}
        return update

    def route_after_agent(state):
        if state.get("status") != "running":
            return END
        pending = state.get("pending")
        if pending is None:
            return "agent"
        return "verify" if pending["tool"] == "finish" else "tools"

    def tools(state):
        p = state["pending"]
        ok, text = run_tool(p["tool"], p["args"], "agent")
        key = json.dumps([p["tool"], p["args"]], sort_keys=True)
        seen = list(state.get("seen_calls", []))
        if key in seen and p["tool"] not in ("run_tests", "git_diff"):
            text += ("\nNOTE: you already made this exact call earlier and got the same result. "
                     "Do something different (read the code you found, or patch it).")
        seen.append(key)
        idx = state.get("tool_index", 0)
        wait = float(delays[idx]) if idx < len(delays) else 0.0
        msgs = state["messages"] + [{"role": "user", "content": tool_result_message(p["tool"], text)}]
        return {"messages": msgs, "pending": None, "tool_index": idx + 1, "pending_wait_s": wait,
                "seen_calls": seen}

    def tool_wait(state):
        wait = state.get("pending_wait_s", 0.0)
        if wait <= 0:
            return {}
        sid = ctx.episode["session_id"]
        if opt.get("resumable", False):
            # Pause the graph; the session runner sleeps for `wait` seconds and resumes us.
            ctx.lifecycle(sid, "tool_wait_start", role=lead_role, expected_wait_ms=wait * 1000, mode="interrupt")
            resumed = interrupt({"wait_s": wait, "reason": "tool_delay"})
            ctx.lifecycle(sid, "tool_wait_end", role=lead_role, waited_ms=(resumed or {}).get("waited_ms"))
        else:
            ctx.lifecycle(sid, "tool_wait_start", role=lead_role, expected_wait_ms=wait * 1000, mode="inline")
            time.sleep(wait)
            ctx.lifecycle(sid, "tool_wait_end", role=lead_role, waited_ms=wait * 1000)
        ctx.recorder.wait(seconds=wait)
        return {"pending_wait_s": 0.0}

    def verify(state):
        p = state["pending"]
        _, repro = run_tool("run_tests", {"target": visible}, "verify")
        repro_ok = ctx.tools.last_test_passed
        suite_ok = False
        suite = ""
        if repro_ok:
            _, suite = run_tool("run_tests", {"target": ""}, "verify")
            suite_ok = ctx.tools.last_test_passed
        attempts = state.get("verify_attempts", 0) + 1
        if repro_ok and suite_ok:
            _, diff = run_tool("git_diff", {}, "verify")
            reviews = state.get("reviews", 0)
            if multi and reviews < 1:
                decision, feedback, _ = run_reviewer(ctx, ctx.episode["issue"], diff, suite, reviews)
                if decision == "revise" and feedback and state.get("step", 0) < max_steps:
                    note = (f"Reviewer sub-agent requested changes before accepting the fix:\n{feedback}\n"
                            f"Address the feedback (or call finish again if the fix is already correct).")
                    msgs = state["messages"] + [{"role": "user", "content": tool_result_message("review", note)}]
                    return {"messages": msgs, "verify_attempts": attempts, "reviews": reviews + 1, "pending": None}
                reviews += 1
            return {"status": "completed", "outcome": "verified", "verify_attempts": attempts,
                    "final_summary": p["args"].get("summary", ""), "pending": None, "reviews": reviews}
        msg = ("Verification failed: the reproduction test still fails.\n" + repro if not repro_ok
               else "Verification failed: the full test suite has failures.\n" + suite)
        msgs = state["messages"] + [{"role": "user", "content": tool_result_message("finish", msg)}]
        if state.get("step", 0) >= max_steps:
            return {"messages": msgs, "status": "failed", "outcome": "verify_failed_no_budget",
                    "verify_attempts": attempts, "final_summary": p["args"].get("summary", ""), "pending": None}
        return {"messages": msgs, "verify_attempts": attempts, "pending": None}

    def route_after_verify(state):
        return END if state.get("status") != "running" else "agent"

    g = StateGraph(AgentState)
    g.add_node("bootstrap", bootstrap)
    g.add_node("agent", agent)
    g.add_node("tools", tools)
    g.add_node("tool_wait", tool_wait)
    g.add_node("verify", verify)
    g.add_edge(START, "bootstrap")
    g.add_edge("bootstrap", "agent")
    g.add_conditional_edges("agent", route_after_agent, ["agent", "tools", "verify", END])
    g.add_edge("tools", "tool_wait")
    g.add_edge("tool_wait", "agent")
    g.add_conditional_edges("verify", route_after_verify, ["agent", END])
    return g.compile(checkpointer=InMemorySaver())
