"""Client for the inference gateway (which fronts llama-server's native /completion endpoint)."""
import json
import time
import uuid

import httpx


class ModelCallError(Exception):
    pass


class GatewayClient:
    def __init__(self, base_url, timeout=900.0, max_retries=2):
        self.base_url = base_url.rstrip("/")
        self.http = httpx.Client(timeout=httpx.Timeout(timeout, connect=10.0))
        self.max_retries = max_retries

    def complete(self, prompt, *, session_id, episode_id, step, n_predict, json_schema=None, request_id=None):
        """Returns dict(content, timings, gateway, client_latency_ms, request_id, attempts)."""
        request_id = request_id or f"{session_id}-s{step}-{uuid.uuid4().hex[:6]}"
        body = {"prompt": prompt, "n_predict": n_predict, "temperature": 0.0, "top_k": 1, "seed": 1234,
                "cache_prompt": True}
        if json_schema is not None:
            body["json_schema"] = json_schema
        headers = {"x-session-id": session_id, "x-request-id": request_id, "x-episode-id": episode_id,
                   "x-step": str(step)}
        last_err = None
        for attempt in range(self.max_retries + 1):
            t0 = time.perf_counter()
            try:
                r = self.http.post(f"{self.base_url}/completion", json=body, headers=headers)
                latency = (time.perf_counter() - t0) * 1000
                data = r.json()
                if r.status_code == 200 and data.get("timings"):
                    data["client_latency_ms"] = latency
                    data["request_id"] = request_id
                    data["attempts"] = attempt + 1
                    return data
                last_err = f"status {r.status_code}: {json.dumps(data)[:300]}"
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                last_err = f"{type(exc).__name__}: {exc}"
            time.sleep(1.0 + attempt)
        raise ModelCallError(last_err)

    def event(self, session_id, event, **fields):
        try:
            self.http.post(f"{self.base_url}/v1/sessions/{session_id}/events",
                           json={"event": event, **fields}, timeout=5.0)
        except httpx.HTTPError:
            pass

    def close(self):
        self.http.close()
