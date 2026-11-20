//! InferenceGateway: an Axum service between the agent application (or llm-router) and ONE llama-server.
//!
//! * `POST /completion`              native llama.cpp completion (policy decides `id_slot` / `cache_prompt`)
//! * `POST /v1/chat/completions`     OpenAI chat API (used behind llm-router); rendered with the model's
//!                                   chat template and executed through `/completion`
//! * `POST /v1/sessions/{id}/events` agent lifecycle events (tool waits, completion, failure)
//! * `GET  /gateway/stats`           aggregates + session-manager counters and slot occupancy
//! * `GET  /gateway/config`          active configuration
//! * `GET  /slots`, `GET /metrics`   proxied from llama-server
//! * `GET  /health`
#![recursion_limit = "512"]

mod chat;
mod config;
mod metrics;
mod policy;
mod sessions;
mod upstream;

use axum::{
    extract::{Path, State},
    http::{HeaderMap, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use clap::Parser;
use config::{Config, PolicyKind};
use metrics::{now_unix_ms, MetricsCollector};
use serde_json::{json, Value};
use sessions::{Manager, Plan, SavedFile, SessState, Victim};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::{Mutex, Notify};

struct AppState {
    cfg: Config,
    client: reqwest::Client,
    metrics: MetricsCollector,
    seq: AtomicU64,
    in_flight: AtomicU64,
    manager: Mutex<Manager>,
    slot_freed: Notify,
    public_url: String,
}

fn header(h: &HeaderMap, name: &str) -> Option<String> {
    h.get(name).and_then(|v| v.to_str().ok()).map(|s| s.to_string())
}

/// Outcome of the session manager's slot acquisition (session_cache policy only).
#[derive(Default)]
struct Acquired {
    slot: usize,
    plan: &'static str,
    victim: Option<String>,
    restored: bool,
    queue_ms: f64,
    save_ms: f64,
    restore_ms: f64,
    erase_ms: f64,
    action_errors: Vec<String>,
}

fn delete_saved(st: &AppState, name: &str) {
    if let Some(dir) = &st.cfg.slot_save_dir {
        let _ = std::fs::remove_file(std::path::Path::new(dir).join(name));
    }
}

/// Enforce the on-disk budget for saved session caches: drop the oldest files first.
fn enforce_save_budget(st: &AppState, m: &mut Manager, keep: &str) {
    let budget = st.cfg.save_budget_mb * 1024 * 1024;
    while m.saved_bytes > budget {
        let oldest = m.sessions.iter()
            .filter(|(sid, s)| s.saved.is_some() && sid.as_str() != keep)
            .min_by_key(|(_, s)| s.saved.as_ref().unwrap().at)
            .map(|(sid, _)| sid.clone());
        let Some(sid) = oldest else { break };
        let f = m.sessions.get_mut(&sid).unwrap().saved.take().unwrap();
        m.saved_bytes = m.saved_bytes.saturating_sub(f.bytes);
        m.counters.saved_files_deleted += 1;
        delete_saved(st, &f.name);
    }
}

async fn acquire_slot(st: &AppState, sid: &str, parent: Option<String>, role: Option<String>) -> Acquired {
    let t0 = Instant::now();
    let ticket = st.seq.fetch_add(1, Ordering::SeqCst);
    let mut counted_wait = false;
    loop {
        let plan;
        {
            let mut m = st.manager.lock().await;
            let now = Instant::now();
            m.touch(sid, parent.clone(), role.clone(), now);
            plan = m.plan(sid, now);
            match &plan {
                Plan::Warm { slot } => {
                    m.slots[*slot].busy = true;
                    m.counters.requests += 1;
                    m.counters.warm += 1;
                    if counted_wait {
                        m.counters.wait_ms_total += upstream::ms(t0);
                    }
                    return Acquired { slot: *slot, plan: "warm", queue_ms: upstream::ms(t0), ..Default::default() };
                }
                Plan::Assign { slot, .. } => {
                    m.slots[*slot].busy = true; // reserve before any slot I/O
                    m.counters.requests += 1;
                    if counted_wait {
                        m.counters.wait_ms_total += upstream::ms(t0);
                    }
                }
                Plan::Wait => {
                    if !counted_wait {
                        m.counters.waits += 1;
                        counted_wait = true;
                    }
                }
            }
        }
        let Plan::Assign { slot, victim, restore } = plan else {
            // all slots busy: wait for a release (re-check periodically in case a wake-up was missed)
            let _ = tokio::time::timeout(Duration::from_millis(100), st.slot_freed.notified()).await;
            let _ = ticket;
            continue;
        };
        let mut a = Acquired { slot, queue_ms: upstream::ms(t0), ..Default::default() };
        match &victim {
            Victim::Empty => a.plan = "empty",
            Victim::Dead(v) => {
                a.plan = "over_dead";
                a.victim = Some(v.clone());
                let t = Instant::now();
                match upstream::slot_action(&st.client, &st.cfg.upstream, slot, "erase", None).await {
                    Ok(_) => st.manager.lock().await.counters.erases += 1,
                    Err(e) => a.action_errors.push(e),
                }
                a.erase_ms = upstream::ms(t);
                st.manager.lock().await.counters.assigned_over_dead += 1;
            }
            Victim::Live(v) => {
                a.plan = "over_live";
                a.victim = Some(v.clone());
                let name = sessions::session_filename(v);
                let t = Instant::now();
                let res = upstream::slot_action(&st.client, &st.cfg.upstream, slot, "save", Some(&name)).await;
                a.save_ms = upstream::ms(t);
                let mut m = st.manager.lock().await;
                m.counters.assigned_over_live += 1;
                m.counters.save_ms_total += a.save_ms;
                match res {
                    Ok(body) => {
                        m.counters.saves += 1;
                        let bytes = body["n_written"].as_u64().unwrap_or(0);
                        let tokens = body["n_saved"].as_u64().unwrap_or(0);
                        if let Some(vs) = m.sessions.get_mut(v) {
                            let old = vs.saved.replace(SavedFile { name, bytes, tokens, at: Instant::now() });
                            let old_bytes = old.map(|f| f.bytes).unwrap_or(0);
                            m.saved_bytes = m.saved_bytes.saturating_sub(old_bytes) + bytes;
                        }
                        enforce_save_budget(st, &mut m, v);
                    }
                    Err(e) => {
                        m.counters.save_failures += 1;
                        a.action_errors.push(e);
                    }
                }
            }
        }
        if let Some(file) = restore {
            let t = Instant::now();
            let res = upstream::slot_action(&st.client, &st.cfg.upstream, slot, "restore", Some(&file)).await;
            a.restore_ms = upstream::ms(t);
            let mut m = st.manager.lock().await;
            m.counters.restore_ms_total += a.restore_ms;
            match res {
                Ok(_) => {
                    m.counters.restores += 1;
                    a.restored = true;
                }
                Err(e) => {
                    m.counters.restore_failures += 1;
                    a.action_errors.push(e);
                }
            }
            // the restored state now lives in the slot; the file is stale from here on
            if let Some(s) = m.sessions.get_mut(sid) {
                if let Some(f) = s.saved.take() {
                    m.saved_bytes = m.saved_bytes.saturating_sub(f.bytes);
                    delete_saved(st, &f.name);
                }
            }
        }
        {
            let mut m = st.manager.lock().await;
            if a.plan == "empty" {
                m.counters.assigned_empty += 1;
            }
            m.occupy(slot, sid);
        }
        return a;
    }
}

/// Shared execution path for /completion and /v1/chat/completions. Returns (status, content, final_chunk, record).
async fn run_inference(st: &Arc<AppState>, headers: &HeaderMap, mut body: Value, api: &str,
                       t_arrival: Instant, extra_pre_ms: f64) -> (StatusCode, String, Value, Value) {
    let arrival_unix_ms = now_unix_ms() - upstream::ms(t_arrival);
    let seq = st.seq.fetch_add(1, Ordering::SeqCst);
    let session_id = header(headers, "x-session-id");
    let parent = header(headers, "x-parent-session-id");
    let role = header(headers, "x-agent-role");
    let request_id = header(headers, "x-request-id").unwrap_or_else(|| format!("gw-{seq}"));
    let in_flight_at_arrival = st.in_flight.fetch_add(1, Ordering::SeqCst);

    // ---- routing decision (timed: this is the Rust routing overhead, excluding queueing and slot I/O) ----
    let t_route = Instant::now();
    let decision = policy::decide_baseline(st.cfg.policy, session_id.as_deref(), st.cfg.n_slots);
    if let Some(slot) = decision.slot {
        body["id_slot"] = json!(slot);
    }
    if let Some(cp) = decision.cache_prompt {
        body["cache_prompt"] = json!(cp);
    }
    let mut routing_decision_us = t_route.elapsed().as_secs_f64() * 1e6;
    let mut acq: Option<Acquired> = None;
    if st.cfg.policy == PolicyKind::SessionCache {
        if let Some(sid) = session_id.as_deref() {
            let t_plan = Instant::now();
            let a = acquire_slot(st, sid, parent.clone(), role.clone()).await;
            routing_decision_us += (upstream::ms(t_plan) - a.queue_ms - a.save_ms - a.restore_ms - a.erase_ms).max(0.0) * 1000.0;
            body["id_slot"] = json!(a.slot);
            acq = Some(a);
        }
    }
    let prompt_chars = body["prompt"].as_str().map(|s| s.len()).unwrap_or(0);

    let t_dispatch = Instant::now();
    let up = upstream::stream_completion(&st.client, &st.cfg.upstream, body).await;
    st.in_flight.fetch_sub(1, Ordering::SeqCst);
    let fc = &up.final_chunk;
    let timings = &fc["timings"];
    let prompt_n = timings["prompt_n"].as_u64().unwrap_or(0);
    let cache_n = timings["cache_n"].as_u64().unwrap_or(0);
    let predicted_n = timings["predicted_n"].as_u64().unwrap_or(0);
    let served_slot = fc["id_slot"].as_u64().map(|s| s as usize);

    // ---- session bookkeeping (all policies: identical occupancy accounting for metrics) ----
    {
        let mut m = st.manager.lock().await;
        let now = Instant::now();
        if let Some(sid) = session_id.as_deref() {
            match (&acq, served_slot) {
                (Some(a), _) => {
                    if up.final_chunk.is_null() {
                        m.slots[a.slot].busy = false;
                        m.clear_slot(a.slot);
                    } else {
                        m.release(a.slot, sid, prompt_n + cache_n + predicted_n, now);
                    }
                }
                (None, Some(slot)) if slot < m.slots.len() => {
                    m.touch(sid, parent.clone(), role.clone(), now);
                    m.occupy(slot, sid);
                    m.release(slot, sid, prompt_n + cache_n + predicted_n, now);
                    m.counters.requests += 1;
                }
                _ => {}
            }
        }
    }
    st.slot_freed.notify_waiters();

    let gateway_total_ms = upstream::ms(t_arrival);
    let pre_dispatch_ms = (t_dispatch - t_arrival).as_secs_f64() * 1000.0;
    let prompt_ms = timings["prompt_ms"].as_f64().unwrap_or(0.0);
    let predicted_per_token_ms = timings["predicted_per_token_ms"].as_f64().unwrap_or(0.0);
    // llama-server does not expose per-request queue time; estimate it as the part of upstream TTFT that
    // is neither prompt processing nor the first decode step.
    let est_upstream_queue_ms = (up.upstream_ttft_ms - prompt_ms - predicted_per_token_ms).max(0.0);
    let a = acq.unwrap_or_default();
    let record = json!({
        "run_id": st.cfg.run_id,
        "policy": st.cfg.policy,
        "server_id": st.cfg.server_id,
        "events_url": format!("{}/v1/sessions", st.public_url),
        "api": api,
        "seq": seq,
        "request_id": request_id,
        "session_id": session_id,
        "parent_session_id": parent,
        "agent_role": role,
        "episode_id": header(headers, "x-episode-id"),
        "step": header(headers, "x-step").and_then(|s| s.parse::<i64>().ok()),
        "arrival_unix_ms": arrival_unix_ms,
        "in_flight_at_arrival": in_flight_at_arrival,
        "requested_slot": decision.slot.or(if a.plan.is_empty() { None } else { Some(a.slot) }),
        "decision_reason": if a.plan.is_empty() { decision.reason } else { a.plan },
        "victim_session": a.victim,
        "restored": a.restored,
        "save_ms": a.save_ms,
        "restore_ms": a.restore_ms,
        "erase_ms": a.erase_ms,
        "slot_action_errors": a.action_errors,
        "served_slot": fc["id_slot"],
        "prompt_chars": prompt_chars,
        "prompt_tokens": prompt_n + cache_n,
        "prompt_n": prompt_n,
        "cache_n": cache_n,
        "prompt_ms": prompt_ms,
        "predicted_n": timings["predicted_n"],
        "predicted_ms": timings["predicted_ms"],
        "stop_type": fc["stop_type"],
        "truncated": fc["truncated"],
        "gateway_queue_ms": a.queue_ms,
        "routing_decision_us": routing_decision_us,
        "template_ms": extra_pre_ms,
        "pre_dispatch_ms": pre_dispatch_ms,
        "upstream_ttft_ms": up.upstream_ttft_ms,
        "upstream_total_ms": up.upstream_total_ms,
        "est_upstream_queue_ms": est_upstream_queue_ms,
        "ttft_ms": pre_dispatch_ms + up.upstream_ttft_ms,
        "gateway_total_ms": gateway_total_ms,
        "gateway_overhead_ms": (gateway_total_ms - up.upstream_total_ms - a.queue_ms - a.save_ms - a.restore_ms - a.erase_ms).max(0.0),
        "status": up.status,
        "error": up.error,
    });
    st.metrics.record_request(&record);
    let status = if up.error.is_some() && up.final_chunk.is_null() {
        StatusCode::from_u16(if up.status >= 400 { up.status } else { 502 }).unwrap_or(StatusCode::BAD_GATEWAY)
    } else {
        StatusCode::OK
    };
    (status, up.content, up.final_chunk, record)
}

async fn completion(State(st): State<Arc<AppState>>, headers: HeaderMap, Json(body): Json<Value>) -> impl IntoResponse {
    let t_arrival = Instant::now();
    let (status, content, fc, record) = run_inference(&st, &headers, body, "completion", t_arrival, 0.0).await;
    let response = json!({
        "content": content,
        "id_slot": fc["id_slot"],
        "timings": fc["timings"],
        "tokens_cached": fc["tokens_cached"],
        "tokens_evaluated": fc["tokens_evaluated"],
        "tokens_predicted": fc["tokens_predicted"],
        "stop_type": fc["stop_type"],
        "truncated": fc["truncated"],
        "error": record["error"],
        "gateway": record,
    });
    with_server_header(&st, (status, Json(response)).into_response())
}

async fn chat_completions(State(st): State<Arc<AppState>>, headers: HeaderMap, Json(chat): Json<Value>) -> Response {
    let t_arrival = Instant::now();
    let t_tpl = Instant::now();
    let prompt = match upstream::apply_template(&st.client, &st.cfg.upstream, &chat["messages"]).await {
        Ok(p) => p,
        Err(e) => {
            let body = json!({"error": {"message": e, "type": "template_error"}});
            return with_server_header(&st, (StatusCode::BAD_GATEWAY, Json(body)).into_response());
        }
    };
    let template_ms = upstream::ms(t_tpl);
    let body = chat::to_completion_body(&chat, prompt);
    let (status, content, fc, record) = run_inference(&st, &headers, body, "chat", t_arrival, template_ms).await;
    let response = if status == StatusCode::OK {
        chat::to_chat_response(record["request_id"].as_str().unwrap_or(""), &content, &fc, &record)
    } else {
        json!({"error": {"message": record["error"], "type": "upstream_error"}, "gateway": record})
    };
    with_server_header(&st, (status, Json(response)).into_response())
}

fn with_server_header(st: &AppState, mut resp: Response) -> Response {
    if let Ok(v) = HeaderValue::from_str(&st.cfg.server_id) {
        resp.headers_mut().insert("x-gateway-server", v);
    }
    resp
}

async fn session_event(State(st): State<Arc<AppState>>, Path(id): Path<String>, Json(body): Json<Value>) -> impl IntoResponse {
    let event = body["event"].as_str().unwrap_or("").to_string();
    let mut erased: Option<usize> = None;
    {
        let mut m = st.manager.lock().await;
        let now = Instant::now();
        match event.as_str() {
            "session_start" => {
                let parent = body["parent_session_id"].as_str().map(|s| s.to_string());
                let role = body["agent_role"].as_str().map(|s| s.to_string());
                m.touch(&id, parent, role, now);
            }
            "tool_wait_start" => m.set_state(&id, SessState::Waiting, body["expected_wait_ms"].as_f64(), now),
            "tool_wait_end" => m.set_state(&id, SessState::Active, None, now),
            "completed" | "failed" | "finished" => {
                m.set_state(&id, SessState::Finished, None, now);
                if st.cfg.policy == PolicyKind::SessionCache {
                    if let Some(slot) = m.erasable_after_finish(&id) {
                        m.slots[slot].busy = true; // reserve while erasing
                        erased = Some(slot);
                    }
                    if let Some(f) = m.sessions.get_mut(&id).and_then(|s| s.saved.take()) {
                        m.saved_bytes = m.saved_bytes.saturating_sub(f.bytes);
                        m.counters.saved_files_deleted += 1;
                        delete_saved(&st, &f.name);
                    }
                }
            }
            _ => {}
        }
    }
    if let Some(slot) = erased {
        let ok = upstream::slot_action(&st.client, &st.cfg.upstream, slot, "erase", None).await.is_ok();
        let mut m = st.manager.lock().await;
        m.slots[slot].busy = false;
        if ok {
            m.clear_slot(slot);
            m.counters.erases += 1;
            m.counters.erases_on_finish += 1;
        }
        drop(m);
        st.slot_freed.notify_waiters();
    }
    let rec = json!({
        "run_id": st.cfg.run_id,
        "policy": st.cfg.policy,
        "server_id": st.cfg.server_id,
        "unix_ms": now_unix_ms(),
        "session_id": id,
        "event": body["event"],
        "erased_slot": erased,
        "body": body,
    });
    st.metrics.record_event(rec);
    Json(json!({"ok": true, "server_id": st.cfg.server_id}))
}

async fn proxy_get(st: &AppState, path: &str) -> (StatusCode, String) {
    match st.client.get(format!("{}{}", st.cfg.upstream, path)).send().await {
        Ok(r) => (StatusCode::from_u16(r.status().as_u16()).unwrap_or(StatusCode::OK), r.text().await.unwrap_or_default()),
        Err(e) => (StatusCode::BAD_GATEWAY, e.to_string()),
    }
}

async fn slots(State(st): State<Arc<AppState>>) -> impl IntoResponse {
    proxy_get(&st, "/slots").await
}

async fn upstream_metrics(State(st): State<Arc<AppState>>) -> impl IntoResponse {
    proxy_get(&st, "/metrics").await
}

async fn stats(State(st): State<Arc<AppState>>) -> impl IntoResponse {
    let m = st.manager.lock().await;
    Json(json!({"policy": st.cfg.policy, "server_id": st.cfg.server_id, "aggregates": st.metrics.snapshot(),
                "in_flight": st.in_flight.load(Ordering::SeqCst), "session_manager": m.counters,
                "occupancy": m.snapshot()}))
}

async fn show_config(State(st): State<Arc<AppState>>) -> impl IntoResponse {
    Json(json!({"policy": st.cfg.policy, "n_slots": st.cfg.n_slots, "upstream": st.cfg.upstream,
                "run_id": st.cfg.run_id, "log_dir": st.cfg.log_dir, "server_id": st.cfg.server_id,
                "slot_save_dir": st.cfg.slot_save_dir, "save_budget_mb": st.cfg.save_budget_mb}))
}

async fn health() -> impl IntoResponse {
    Json(json!({"status": "ok"}))
}

#[tokio::main]
async fn main() {
    let mut cfg = Config::parse();
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(cfg.upstream_timeout_s))
        .pool_max_idle_per_host(64)
        .build()
        .expect("http client");
    // Verify the slot count against the runtime rather than trusting the flag.
    if let Ok(r) = client.get(format!("{}/props", cfg.upstream)).send().await {
        if let Ok(v) = r.json::<Value>().await {
            if let Some(n) = v["total_slots"].as_u64() {
                if n as usize != cfg.n_slots {
                    eprintln!("warning: --n-slots {} but upstream reports total_slots={n}; using {n}", cfg.n_slots);
                }
                cfg.n_slots = n as usize;
            }
        }
    }
    let metrics = MetricsCollector::new(&cfg.log_dir).expect("log dir");
    let listen = cfg.listen.clone();
    let public_url = cfg.public_url.clone().unwrap_or_else(|| format!("http://{listen}"));
    let n_slots = cfg.n_slots;
    let state = Arc::new(AppState {
        cfg, client, metrics, seq: AtomicU64::new(0), in_flight: AtomicU64::new(0),
        manager: Mutex::new(Manager::new(n_slots)), slot_freed: Notify::new(), public_url,
    });
    if state.cfg.snapshot_interval_ms > 0 {
        let st = state.clone();
        tokio::spawn(async move {
            let mut tick = tokio::time::interval(Duration::from_millis(st.cfg.snapshot_interval_ms));
            loop {
                tick.tick().await;
                let snap = {
                    let m = st.manager.lock().await;
                    json!({"unix_ms": now_unix_ms(), "server_id": st.cfg.server_id, "occupancy": m.snapshot(),
                           "counters": m.counters})
                };
                st.metrics.log("occupancy", snap);
            }
        });
    }
    let app = Router::new()
        .route("/completion", post(completion))
        .route("/v1/chat/completions", post(chat_completions))
        .route("/v1/sessions/{id}/events", post(session_event))
        .route("/gateway/stats", get(stats))
        .route("/gateway/config", get(show_config))
        .route("/slots", get(slots))
        .route("/metrics", get(upstream_metrics))
        .route("/health", get(health))
        .with_state(state.clone());
    let listener = tokio::net::TcpListener::bind(&listen).await.expect("bind");
    eprintln!("gateway {} listening on {listen} policy={:?} n_slots={}", state.cfg.server_id, state.cfg.policy,
              state.cfg.n_slots);
    axum::serve(listener, app).await.expect("serve");
}
