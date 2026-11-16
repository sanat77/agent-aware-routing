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
