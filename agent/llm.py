"""Client for the inference path.

Two wire formats:
  * api="completion": llama.cpp-native `POST /completion` with a pre-rendered prompt (single-server
    baselines A/B/C, talking to our Rust gateway directly).
  * api="chat": OpenAI `POST /v1/chat/completions` with messages (cluster setups S1-S3, through llm-router,
    which only speaks the chat API). Each session-manager gateway reports its own events URL in the response,
    so lifecycle events reach every server that holds part of a session.
"""
import json
import time
import uuid

import httpx


class ModelCallError(Exception):
    pass


class GatewayClient:
    def __init__(self, base_url, timeout=900.0, max_retries=2, api="completion"):
        self.base_url = base_url.rstrip("/")
        self.http = httpx.Client(timeout=httpx.Timeout(timeout, connect=10.0))
        self.max_retries = max_retries
        self.api = api
        self.session_servers = {}  # session_id -> set of events URLs (chat api)

    def complete(self, prompt=None, *, messages=None, session_id, episode_id, step, n_predict, json_schema=None,
                 request_id=None, parent_session_id=None, agent_role=None):
        """Returns dict(content, timings, gateway, client_latency_ms, request_id, attempts, router_*)."""
        request_id = request_id or f"{session_id}-s{step}-{uuid.uuid4().hex[:6]}"
        sampling = {"temperature": 0.0, "top_k": 1, "seed": 1234, "cache_prompt": True}
        if self.api == "chat":
            url = f"{self.base_url}/v1/chat/completions"
            body = {"model": "local", "messages": messages, "max_tokens": n_predict, **sampling}
            if json_schema is not None:
                body["response_format"] = {"type": "json_schema",
                                           "json_schema": {"name": "action", "schema": json_schema}}
        else:
            url = f"{self.base_url}/completion"
            body = {"prompt": prompt, "n_predict": n_predict, **sampling}
            if json_schema is not None:
                body["json_schema"] = json_schema
        headers = {"x-session-id": session_id, "x-request-id": request_id, "x-episode-id": episode_id,
                   "x-step": str(step)}
        if parent_session_id:
            headers["x-parent-session-id"] = parent_session_id
        if agent_role:
            headers["x-agent-role"] = agent_role
        last_err = None
        for attempt in range(self.max_retries + 1):
            t0 = time.perf_counter()
            try:
                r = self.http.post(url, json=body, headers=headers)
                latency = (time.perf_counter() - t0) * 1000
                data = r.json()
                if r.status_code == 200 and data.get("timings"):
                    if self.api == "chat":
                        data["content"] = data["choices"][0]["message"]["content"]
                        gw = data.get("gateway") or {}
                        if gw.get("events_url"):
                            self.session_servers.setdefault(session_id, set()).add(gw["events_url"])
                    data["router_backend"] = r.headers.get("x-router-backend")
                    data["router_reason"] = r.headers.get("x-router-reason")
                    data["client_latency_ms"] = latency
                    data["request_id"] = request_id
                    data["attempts"] = attempt + 1
                    return data
                last_err = f"status {r.status_code}: {json.dumps(data)[:300]}"
            except (httpx.HTTPError, json.JSONDecodeError, KeyError, IndexError) as exc:
                last_err = f"{type(exc).__name__}: {exc}"
            time.sleep(1.0 + attempt)
        raise ModelCallError(last_err)

    def event(self, session_id, event, **fields):
        if self.api == "chat":
            targets = [f"{u}/{session_id}/events" for u in sorted(self.session_servers.get(session_id, ()))]
        else:
            targets = [f"{self.base_url}/v1/sessions/{session_id}/events"]
        for url in targets:
            try:
                self.http.post(url, json={"event": event, **fields}, timeout=5.0)
            except httpx.HTTPError:
                pass

    def close(self):
        self.http.close()
