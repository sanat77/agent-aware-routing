"""Parse llama-server (-lv 4) logs for slot-selection and prompt-cache events.

Only lines that build b11669 actually prints are used; see docs/runtime/FINDINGS.md.
"""
import re
from collections import Counter

RE_SELECT = re.compile(r"slot get_availabl: id\s+(\d+) \| task -?\d+ \| selected slot by (LCP similarity|LRU|id)")
RE_REUSE = re.compile(r"slot\s+operator\(\): id\s+(\d+) \| task (\d+) \| cached n_tokens = (\d+), memory_seq_rm \[(\d+), end\)")
RE_SAVE = re.compile(r"prompt_save:\s+- saving prompt with length (\d+), total state size = ([\d.]+) MiB")
RE_STATE = re.compile(r"cache state: (\d+) prompts, ([\d.]+) MiB")
RE_LOAD_CAND = re.compile(r"load:\s+- prompt with length\s+(\d+), lcp =\s+(\d+), f_keep = ([\d.-]+), f_sim = ([\d.-]+)")
RE_FOUND = re.compile(r"load:\s+- found better prompt", re.I)
RE_ALREADY = re.compile(r"prompt is already in the cache")
RE_SKIP_SAVE = re.compile(r"saving idle slot to prompt cache")


def parse(path):
    sel = Counter()
    saves = 0
    saved_mib = 0.0
    saved_tokens = 0
    max_state_mib = 0.0
    max_state_prompts = 0
    candidates = 0
    restores = 0
    already = 0
    idle_saves = 0
    full_resets = 0
    reuse_events = 0
    try:
        f = open(path, errors="replace")
    except FileNotFoundError:
        return {"available": False}
    with f:
        for line in f:
            if "get_availabl" in line:
                m = RE_SELECT.search(line)
                if m:
                    sel[m.group(2)] += 1
            m = RE_REUSE.search(line)
            if m:
                reuse_events += 1
                if int(m.group(3)) == 0:
                    full_resets += 1
                continue
            m = RE_SAVE.search(line)
            if m:
                saves += 1
                saved_tokens += int(m.group(1))
                saved_mib += float(m.group(2))
                continue
            m = RE_STATE.search(line)
            if m:
                max_state_prompts = max(max_state_prompts, int(m.group(1)))
                max_state_mib = max(max_state_mib, float(m.group(2)))
                continue
            if RE_LOAD_CAND.search(line):
                candidates += 1
            if RE_FOUND.search(line):
                restores += 1
            if RE_ALREADY.search(line):
                already += 1
            if RE_SKIP_SAVE.search(line):
                idle_saves += 1
    return {
        "available": True,
        "slot_selection": dict(sel),
        "prompt_cache_saves": saves,
        "prompt_cache_saved_tokens": saved_tokens,
        "prompt_cache_saved_mib": round(saved_mib, 1),
        "prompt_cache_max_state_mib": max_state_mib,
        "prompt_cache_max_prompts": max_state_prompts,
        "prompt_cache_restore_candidates": candidates,
        "prompt_cache_restores_logged": restores,
        "prompt_cache_duplicate_skips": already,
        "idle_slot_save_attempts": idle_saves,
        "tasks": reuse_events,
        "tasks_with_zero_reuse": full_resets,
    }
