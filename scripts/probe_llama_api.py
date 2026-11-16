"""Probe the running llama-server to verify which cache/slot features actually exist.

Writes docs/runtime/api_probe.json. Run with a server on 127.0.0.1:8090.
"""
import json
import sys
import time
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8090"


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            raw = r.read().decode()
            status = r.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        status = e.code
    dt = time.perf_counter() - t0
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        out = raw
    return status, out, dt


tools = [{
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read a file",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
}]
long_sys = "You are a coding agent. " + ("Follow repository conventions carefully. " * 150)
msgs = [{"role": "system", "content": long_sys},
        {"role": "user", "content": "Read the file app/main.py using the tool."}]
report = {}
for i, (slot, cache) in enumerate([(0, True), (0, True), (1, True), (0, False)]):
    st, out, dt = call("POST", "/v1/chat/completions", {
        "messages": msgs, "tools": tools, "max_tokens": 64, "temperature": 0,
        "id_slot": slot, "cache_prompt": cache, "timings_per_token": False,
    })
    report[f"chat_{i}_slot{slot}_cache{cache}"] = {
        "status": st, "wall_s": dt,
        "keys": list(out.keys()) if isinstance(out, dict) else None,
        "timings": out.get("timings") if isinstance(out, dict) else None,
        "usage": out.get("usage") if isinstance(out, dict) else None,
        "message": out["choices"][0]["message"] if isinstance(out, dict) and "choices" in out else out,
    }
st, out, _ = call("GET", "/slots")
report["slots"] = out
st, out, _ = call("GET", "/metrics")
report["metrics"] = out
st, out, _ = call("POST", "/tokenize", {"content": "hello world"})
report["tokenize"] = out
st, out, _ = call("POST", "/slots/0?action=erase")
report["slot_erase"] = {"status": st, "body": out}
st, out, _ = call("POST", "/apply-template", {"messages": msgs[:1]})
report["apply_template"] = {"status": st, "body": str(out)[:300]}
json.dump(report, open("docs/runtime/api_probe.json", "w"), indent=1, default=str)
for k, v in report.items():
    print("==", k)
    print(json.dumps(v, default=str)[:1500])
