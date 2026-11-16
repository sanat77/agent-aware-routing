"""Probe whether llama-server's host-RAM prompt cache (--cache-ram) restores evicted prefixes,
and how default slot selection (no id_slot) behaves. Appends to docs/runtime/cache_probe.json."""
import json
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8090"
LABEL = sys.argv[2] if len(sys.argv) > 2 else "default"


def chat(content, slot=None):
    body = {"messages": [{"role": "system", "content": content},
                         {"role": "user", "content": "Say ok."}],
            "max_tokens": 4, "temperature": 0, "cache_prompt": True}
    if slot is not None:
        body["id_slot"] = slot
    req = urllib.request.Request(BASE + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    out = json.loads(urllib.request.urlopen(req, timeout=300).read())
    t = out["timings"]
    return {"cache_n": t["cache_n"], "prompt_n": t["prompt_n"], "prompt_ms": round(t["prompt_ms"], 1)}


A = "Session A context. " + "alpha beta gamma delta " * 200
B = "Session B context. " + "one two three four five " * 200
C = "Session C context. " + "red green blue yellow " * 200
steps = []
steps.append(("A on slot0", chat(A, 0)))
steps.append(("B on slot0 (overwrites A)", chat(B, 0)))
steps.append(("A on slot0 again (RAM cache restore?)", chat(A, 0)))
steps.append(("C on slot1", chat(C, 1)))
steps.append(("A no id_slot (default selection)", chat(A)))
steps.append(("C no id_slot (default selection)", chat(C)))
steps.append(("B no id_slot (neither slot holds B)", chat(B)))
for name, r in steps:
    print(f"{name:45s} {r}")
try:
    prev = json.load(open("docs/runtime/cache_probe.json"))
except FileNotFoundError:
    prev = {}
prev[LABEL] = steps
json.dump(prev, open("docs/runtime/cache_probe.json", "w"), indent=1)
