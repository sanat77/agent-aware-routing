"""Verify llama-server slot save/restore/erase and /apply-template on the frozen build.

Start a server first (with --slot-save-path DIR), e.g. via bench.cluster, then:
  python scripts/probe_slot_actions.py http://127.0.0.1:8190
Writes docs/runtime/slot_actions_probe.json.
"""
import json
import sys
import time
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8190"


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            out = json.loads(r.read() or b"null")
            status = r.status
    except urllib.error.HTTPError as e:
        out, status = e.read().decode(), e.code
    return status, out, (time.perf_counter() - t0) * 1000


report = {}
msgs = [{"role": "system", "content": "You are a careful assistant. " + "Remember the facts. " * 300},
        {"role": "user", "content": "Say ok."}]
st, out, ms = call("POST", "/apply-template", {"messages": msgs})
report["apply_template"] = {"status": st, "ms": ms, "prompt_head": str(out.get("prompt", ""))[:120] if isinstance(out, dict) else out}
prompt = out["prompt"]


def complete(slot):
    st, o, ms = call("POST", "/completion", {"prompt": prompt, "n_predict": 4, "temperature": 0, "id_slot": slot,
                                             "cache_prompt": True})
    return {"status": st, "ms": round(ms, 1), "cache_n": o["timings"]["cache_n"], "prompt_n": o["timings"]["prompt_n"],
            "id_slot": o.get("id_slot")}


report["1_cold_on_slot0"] = complete(0)
st, out, ms = call("POST", "/slots/0?action=save", {"filename": "probe_session.bin"})
report["2_save_slot0"] = {"status": st, "ms": round(ms, 1), "body": out}
st, out, ms = call("POST", "/slots/0?action=erase")
report["3_erase_slot0"] = {"status": st, "ms": round(ms, 1), "body": out}
st, out, ms = call("POST", "/slots/1?action=restore", {"filename": "probe_session.bin"})
report["4_restore_into_slot1"] = {"status": st, "ms": round(ms, 1), "body": out}
report["5_request_on_slot1_after_restore"] = complete(1)
report["6_request_on_slot0_after_erase"] = complete(0)
st, out, _ = call("GET", "/slots")
report["7_slots"] = [{k: s.get(k) for k in ("id", "is_processing", "n_prompt_tokens")} for s in out] if isinstance(out, list) else out
st, out, ms = call("POST", "/v1/chat/completions", {"messages": msgs, "max_tokens": 4, "temperature": 0})
report["8_chat_keys"] = sorted(out.keys()) if isinstance(out, dict) else out
for k, v in report.items():
    print(k, json.dumps(v)[:400])
json.dump(report, open("docs/runtime/slot_actions_probe.json", "w"), indent=1)
