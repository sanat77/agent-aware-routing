"""Helper sub-agents for multi-agent mode. Each helper is its own LangGraph graph and its own inference
session (session id `<lead>-<role><n>`, parent = lead session). Helpers are short-lived: when they finish,
their cache is dead weight, which is exactly what session-aware caching is meant to reclaim.
"""
import json
import operator
from typing import Annotated, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from .llm import ModelCallError
from .prompts import EXPLORER_PROMPT, EXPLORER_SCHEMA, REVIEWER_PROMPT, REVIEWER_SCHEMA, tool_result_message

EXPLORER_MAX_CALLS = 4


class HelperState(TypedDict, total=False):
    messages: list
    calls: int
    pending: Optional[dict]
    result: Optional[dict]
    done: bool
    log: Annotated[list, operator.add]


def _call(ctx, sid, role, step, messages, system, schema, n_predict):
    return ctx.model_call(session_id=sid, role=role, step=step, system=system, messages=messages,
                          schema=schema, n_predict=n_predict)


def run_explorer(ctx, issue_context, index):
    """Returns (summary or None, session_id)."""
    lead = ctx.episode["session_id"]
    sid = f"{lead}-explore{index}"

    def think(state):
        calls = state.get("calls", 0)
        if calls >= EXPLORER_MAX_CALLS:
            return {"done": True}
        try:
            resp = _call(ctx, sid, "explorer", calls, state["messages"], EXPLORER_PROMPT, EXPLORER_SCHEMA, 320)
        except ModelCallError:
            return {"done": True, "calls": calls + 1}
        content = resp.get("content", "")
        msgs = state["messages"] + [{"role": "assistant", "content": content}]
        try:
            action = json.loads(content)
            tool, args = action["tool"], action.get("tool_input") or {}
        except (json.JSONDecodeError, KeyError, TypeError):
            msgs.append({"role": "user", "content": tool_result_message("parse", "ERROR: reply with one JSON object.")})
            return {"messages": msgs, "calls": calls + 1, "pending": None}
        if tool == "report":
            return {"messages": msgs, "calls": calls + 1, "done": True, "result": {"summary": args.get("summary", "")}}
        return {"messages": msgs, "calls": calls + 1, "pending": {"tool": tool, "args": args}}

    def act(state):
        p = state["pending"]
        ok, text, secs = ctx.tools.execute(p["tool"], p["args"])
        ctx.recorder.tool(name=p["tool"], args=p["args"], ok=ok, seconds=secs, origin="explorer",
                          output_chars=len(text))
        msgs = state["messages"] + [{"role": "user", "content": tool_result_message(p["tool"], text)}]
        return {"messages": msgs, "pending": None}

    def route(state):
        if state.get("done"):
            return END
        return "act" if state.get("pending") else "think"

    g = StateGraph(HelperState)
    g.add_node("think", think)
    g.add_node("act", act)
    g.add_edge(START, "think")
    g.add_conditional_edges("think", route, ["think", "act", END])
    g.add_edge("act", "think")
    graph = g.compile()
    ctx.lifecycle(sid, "session_start", parent=lead, role="explorer")
    first = (f"{issue_context}\n\nLocate the faulty code under tracker/ and report it. Reply with one JSON tool call.")
    out = graph.invoke({"messages": [{"role": "user", "content": first}], "calls": 0}, {"recursion_limit": 40})
    ctx.lifecycle(sid, "completed", parent=lead, role="explorer")
    result = out.get("result") or {}
    return (result.get("summary") or None), sid


def run_reviewer(ctx, issue, diff, test_summary, index):
    """Returns (decision, feedback, session_id). decision is 'approve' | 'revise' | None (reviewer failed)."""
    lead = ctx.episode["session_id"]
    sid = f"{lead}-review{index}"
    ctx.lifecycle(sid, "session_start", parent=lead, role="reviewer")
    msg = (f"# Issue\n{issue.strip()}\n\n# Proposed diff\n{diff.strip()[:3500]}\n\n"
           f"# Test results\n{test_summary.strip()[:800]}\n\nReview the fix and reply with one JSON object.")
    decision, feedback = None, ""
    try:
        resp = _call(ctx, sid, "reviewer", 0, [{"role": "user", "content": msg}], REVIEWER_PROMPT, REVIEWER_SCHEMA, 320)
        verdict = json.loads(resp.get("content", ""))
        decision = verdict.get("decision")
        feedback = verdict.get("feedback", "")
    except (ModelCallError, json.JSONDecodeError, TypeError, AttributeError):
        pass
    ctx.lifecycle(sid, "completed", parent=lead, role="reviewer")
    return decision, feedback, sid
