"""Stable system prompt, tool definitions, JSON-schema for constrained decoding, and ChatML rendering.

Everything here is deterministic: identical inputs give byte-identical prompts, which is what lets
llama.cpp reuse cached prefixes across turns and across sessions.
"""
import hashlib
import json

SYSTEM_PROMPT = """You are RepoFixer, an autonomous software engineer working inside a Python repository.
Your job: fix the bug described in the issue by editing the application source under tracker/.
Never edit files under tests/ - the tests describe the correct behaviour.

Every turn you reply with exactly ONE JSON object:
{"reasoning": "<short reasoning>", "tool": "<tool name>", "tool_input": {...}}
The result of the tool is sent back to you in the next message.

Tools:
- list_files(path): list files under a directory ("." for the repository root).
- read_file(path, start_line, end_line): show numbered source lines (at most 80 lines per call).
- search_code(pattern, path): regular-expression search; returns "file:line: text" matches.
- run_tests(target): run pytest on a test file, a test id like tests/test_x.py::test_name, or "" for the whole suite.
- get_test_results(test): full output of the most recent test run, optionally only the part about one test name.
- apply_patch(path, start_line, end_line, new_text): replace lines start_line..end_line (inclusive, the numbers
  shown by read_file) with new_text. Write complete lines with their indentation, without line-number prefixes.
  Read the lines first so the range is exact. Every line in the range is replaced, so new_text must repeat any
  line in the range you want to keep. The tool shows the removed lines and the updated region afterwards.
- git_diff(): show all changes you have made so far.
- finish(summary): stop. Use it once the reproduction test and the full suite pass. The summary must explain the
  root cause and the fix in two or three sentences.

Method:
1. Read the issue and the failing reproduction test.
2. Find the code the test exercises (search_code, read_file).
3. State a hypothesis about the root cause in your reasoning.
4. Make the smallest correct fix with apply_patch.
5. Run the reproduction test, then the full suite with run_tests("").
6. Check git_diff, then finish. If a patch is rejected or tests still fail, read the error and try again."""

TOOL_NAMES = ("list_files", "read_file", "search_code", "run_tests", "get_test_results",
              "apply_patch", "git_diff", "finish")


def _obj(props, required=None):
    return {"type": "object", "properties": props, "required": list(required if required is not None else props),
            "additionalProperties": False}


S = {"type": "string"}
I = {"type": "integer", "minimum": 1}

TOOL_ARG_SCHEMAS = {
    "list_files": _obj({"path": S}),
    "read_file": _obj({"path": S, "start_line": I, "end_line": I}),
    "search_code": _obj({"pattern": S, "path": S}),
    "run_tests": _obj({"target": S}),
    "get_test_results": _obj({"test": S}),
    "apply_patch": _obj({"path": S, "start_line": I, "end_line": I, "new_text": S}),
    "git_diff": _obj({}, []),
    "finish": _obj({"summary": {"type": "string", "maxLength": 600}}),
}

# llama.cpp's JSON-schema grammar emits object keys in alphabetical order, so the key names are chosen to make
# the model write its reasoning first, then the tool name, then the tool input.
ACTION_SCHEMA = {
    "anyOf": [
        _obj({"reasoning": {"type": "string", "maxLength": 220}, "tool": {"const": name}, "tool_input": schema})
        for name, schema in TOOL_ARG_SCHEMAS.items()
    ]
}
ACTION_SCHEMA_SHA = hashlib.sha256(json.dumps(ACTION_SCHEMA, sort_keys=True).encode()).hexdigest()[:16]
SYSTEM_PROMPT_SHA = hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()[:16]


def initial_user_message(issue, file_listing, test_id, test_source, test_output):
    return (f"# Issue\n{issue.strip()}\n\n"
            f"# Repository files\n{file_listing.strip()}\n\n"
            f"# Reproduction test source\n{test_source.strip()}\n\n"
            f"# Reproduction test output: run_tests(\"{test_id}\")\n{test_output.strip()}\n\n"
            f"Start by locating the application code the test exercises. Reply with one JSON tool call.")


def tool_result_message(tool, text):
    return f"[{tool} result]\n{text.rstrip()}"


def render_chatml(system, messages, header=None):
    """Render a Qwen ChatML prompt ending with an open assistant turn.

    `header` (unique-prefix workload only) is placed before the system prompt, so it changes the very first
    tokens of the prompt and defeats prefix reuse when it differs between requests.
    """
    sys_text = f"{header}\n\n{system}" if header else system
    parts = [f"<|im_start|>system\n{sys_text}<|im_end|>\n"]
    for m in messages:
        parts.append(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n")
    parts.append("<|im_start|>assistant\n")
    return "".join(parts)


# ---------------------------------------------------------------------------------------------------------
# Multi-agent mode: short-lived helper sub-agents with their own sessions (parent = lead session).
# ---------------------------------------------------------------------------------------------------------

EXPLORER_PROMPT = """You are Explorer, a read-only sub-agent helping a lead engineer fix a bug in a Python repository.
Your only job: find where in tracker/ the bug described in the issue lives. You cannot edit files.

Every turn you reply with exactly ONE JSON object:
{"reasoning": "<short reasoning>", "tool": "<tool name>", "tool_input": {...}}

Tools:
- list_files(path): list files under a directory.
- read_file(path, start_line, end_line): show numbered source lines (at most 80 lines per call).
- search_code(pattern, path): regular-expression search; returns "file:line: text" matches.
- report(summary): stop and hand your findings to the lead. The summary must name the file, the line numbers
  and the suspected root cause in at most three sentences.

Be quick: you have at most four turns. Report as soon as you have located the faulty code."""

REVIEWER_PROMPT = """You are Reviewer, a sub-agent that checks a proposed bug fix before it is accepted.
You see the issue, the diff and the test results. Approve the fix if it addresses the root cause in the
application code without weakening behaviour elsewhere. Ask for a revision only for a concrete problem.

Reply with exactly ONE JSON object:
{"analysis": "<short analysis>", "decision": "approve" | "revise", "feedback": "<what to change, or empty>"}"""

EXPLORER_TOOLS = ("list_files", "read_file", "search_code", "report")
EXPLORER_SCHEMA = {
    "anyOf": [
        _obj({"reasoning": {"type": "string", "maxLength": 220}, "tool": {"const": name},
              "tool_input": (TOOL_ARG_SCHEMAS[name] if name != "report"
                             else _obj({"summary": {"type": "string", "maxLength": 500}}))})
        for name in EXPLORER_TOOLS
    ]
}
# keys chosen so llama.cpp's alphabetical key order is: analysis -> decision -> feedback
REVIEWER_SCHEMA = _obj({"analysis": {"type": "string", "maxLength": 300},
                        "decision": {"enum": ["approve", "revise"]},
                        "feedback": {"type": "string", "maxLength": 400}})
SCHEMA_SHAS = {
    "action": ACTION_SCHEMA_SHA,
    "explorer": hashlib.sha256(json.dumps(EXPLORER_SCHEMA, sort_keys=True).encode()).hexdigest()[:16],
    "reviewer": hashlib.sha256(json.dumps(REVIEWER_SCHEMA, sort_keys=True).encode()).hexdigest()[:16],
}
SCHEMAS = {"action": ACTION_SCHEMA, "explorer": EXPLORER_SCHEMA, "reviewer": REVIEWER_SCHEMA}


def chat_messages(system, messages, header=None):
    """OpenAI-style message list equivalent to render_chatml(system, messages, header)."""
    sys_text = f"{header}\n\n{system}" if header else system
    return [{"role": "system", "content": sys_text}] + [dict(m) for m in messages]
