"""Verify the native /completion endpoint: streaming chunks, id_slot, tokens_cached, timings, json_schema."""
import json
import sys
import time
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8090"
prompt = ("<|im_start|>system\nYou are a coding agent. Respond only with JSON.<|im_end|>\n"
          "<|im_start|>user\nCall the tool read_file on app/main.py<|im_end|>\n<|im_start|>assistant\n")
schema = {"type": "object", "properties": {"tool": {"type": "string", "enum": ["read_file", "finish"]},
                                           "args": {"type": "object"}}, "required": ["tool", "args"]}
for stream in (True, False):
    body = {"prompt": prompt, "n_predict": 48, "temperature": 0, "cache_prompt": True, "stream": stream,
            "json_schema": schema, "id_slot": -1}
    req = urllib.request.Request(BASE + "/completion", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=300) as r:
        if stream:
            first = None
            chunks = []
            for line in r:
                line = line.decode().strip()
                if not line.startswith("data:"):
                    continue
                if first is None:
                    first = time.perf_counter() - t0
                chunks.append(json.loads(line[5:]))
            print("first_chunk_s", round(first, 3), "n_chunks", len(chunks))
            print("first chunk:", json.dumps(chunks[0])[:400])
            last = chunks[-1]
            print("last chunk keys:", sorted(last.keys()))
            print({k: last.get(k) for k in ("id_slot", "tokens_cached", "tokens_evaluated", "stop_type", "timings")})
            print("text:", "".join(c.get("content", "") for c in chunks))
        else:
            out = json.loads(r.read())
            print("nonstream keys:", sorted(out.keys()))
            print({k: out.get(k) for k in ("id_slot", "tokens_cached", "tokens_evaluated", "timings", "content")})
