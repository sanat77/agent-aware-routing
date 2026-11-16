//! InferenceGateway: an Axum service between the agent application and llama-server.
//!
//! * `POST /completion`              forward a completion (policy decides `id_slot` / `cache_prompt`)
//! * `POST /v1/sessions/{id}/events` agent lifecycle events (tool waits, completion, failure)
//! * `GET  /gateway/stats`           in-memory aggregates
//! * `GET  /gateway/config`          active configuration
//! * `GET  /slots`, `GET /metrics`   proxied from llama-server
//! * `GET  /health`

mod config;
mod metrics;
mod policy;
mod upstream;

use axum::{
    extract::{Path, State},
    http::{HeaderMap, StatusCode},
    response::IntoResponse,
    routing::{get, post},
    Json, Router,
};
use clap::Parser;
use config::Config;
use metrics::{now_unix_ms, MetricsCollector};
use serde_json::{json, Value};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

struct AppState {
    cfg: Config,
    client: reqwest::Client,
    metrics: MetricsCollector,
    seq: AtomicU64,
    in_flight: AtomicU64,
}

fn header(h: &HeaderMap, name: &str) -> Option<String> {
    h.get(name).and_then(|v| v.to_str().ok()).map(|s| s.to_string())
}

async fn completion(State(st): State<Arc<AppState>>, headers: HeaderMap, Json(mut body): Json<Value>) -> impl IntoResponse {
    let t_arrival = Instant::now();
    let arrival_unix_ms = now_unix_ms();
    let seq = st.seq.fetch_add(1, Ordering::SeqCst);
    let session_id = header(&headers, "x-session-id");
    let request_id = header(&headers, "x-request-id").unwrap_or_else(|| format!("gw-{seq}"));
    let in_flight_at_arrival = st.in_flight.fetch_add(1, Ordering::SeqCst);

    // ---- routing decision (timed: this is the Rust routing overhead) ----
    let t_route = Instant::now();
    let decision = policy::decide_baseline(st.cfg.policy, session_id.as_deref(), st.cfg.n_slots);
    if let Some(slot) = decision.slot {
        body["id_slot"] = json!(slot);
    }
    if let Some(cp) = decision.cache_prompt {
        body["cache_prompt"] = json!(cp);
    }
    let routing_decision_us = t_route.elapsed().as_secs_f64() * 1e6;
    let prompt_chars = body["prompt"].as_str().map(|s| s.len()).unwrap_or(0);

    let t_dispatch = Instant::now();
    let up = upstream::stream_completion(&st.client, &st.cfg.upstream, body).await;
    st.in_flight.fetch_sub(1, Ordering::SeqCst);
    let gateway_total_ms = upstream::ms(t_arrival);
    let pre_dispatch_ms = (t_dispatch - t_arrival).as_secs_f64() * 1000.0;

    let fc = &up.final_chunk;
    let timings = &fc["timings"];
    let prompt_n = timings["prompt_n"].as_u64().unwrap_or(0);
    let cache_n = timings["cache_n"].as_u64().unwrap_or(0);
    let prompt_ms = timings["prompt_ms"].as_f64().unwrap_or(0.0);
    let predicted_per_token_ms = timings["predicted_per_token_ms"].as_f64().unwrap_or(0.0);
    // llama-server does not expose per-request queue time; estimate it as the part of upstream TTFT that
    // is neither prompt processing nor the first decode step.
    let est_upstream_queue_ms = (up.upstream_ttft_ms - prompt_ms - predicted_per_token_ms).max(0.0);
    let record = json!({
        "run_id": st.cfg.run_id,
        "policy": st.cfg.policy,
        "seq": seq,
        "request_id": request_id,
        "session_id": session_id,
        "episode_id": header(&headers, "x-episode-id"),
        "step": header(&headers, "x-step").and_then(|s| s.parse::<i64>().ok()),
        "arrival_unix_ms": arrival_unix_ms,
        "in_flight_at_arrival": in_flight_at_arrival,
        "requested_slot": decision.slot,
        "decision_reason": decision.reason,
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
        "gateway_queue_ms": 0.0,
        "routing_decision_us": routing_decision_us,
        "pre_dispatch_ms": pre_dispatch_ms,
        "upstream_ttft_ms": up.upstream_ttft_ms,
        "upstream_total_ms": up.upstream_total_ms,
        "est_upstream_queue_ms": est_upstream_queue_ms,
        "ttft_ms": pre_dispatch_ms + up.upstream_ttft_ms,
        "gateway_total_ms": gateway_total_ms,
        "gateway_overhead_ms": (gateway_total_ms - up.upstream_total_ms).max(0.0),
        "status": up.status,
        "error": up.error,
    });
    st.metrics.record_request(&record);

    let status = if up.error.is_some() && up.final_chunk.is_null() {
        StatusCode::from_u16(if up.status >= 400 { up.status } else { 502 }).unwrap_or(StatusCode::BAD_GATEWAY)
    } else {
        StatusCode::OK
    };
    let response = json!({
        "content": up.content,
        "id_slot": fc["id_slot"],
        "timings": fc["timings"],
        "tokens_cached": fc["tokens_cached"],
        "tokens_evaluated": fc["tokens_evaluated"],
        "tokens_predicted": fc["tokens_predicted"],
        "stop_type": fc["stop_type"],
        "truncated": fc["truncated"],
        "error": up.error,
        "gateway": record,
    });
    (status, Json(response))
}

async fn session_event(State(st): State<Arc<AppState>>, Path(id): Path<String>, Json(body): Json<Value>) -> impl IntoResponse {
    let rec = json!({
        "run_id": st.cfg.run_id,
        "policy": st.cfg.policy,
        "unix_ms": now_unix_ms(),
        "session_id": id,
        "event": body["event"],
        "body": body,
    });
    st.metrics.record_event(rec);
    Json(json!({"ok": true}))
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
    Json(json!({"policy": st.cfg.policy, "aggregates": st.metrics.snapshot(),
                "in_flight": st.in_flight.load(Ordering::SeqCst)}))
}

async fn show_config(State(st): State<Arc<AppState>>) -> impl IntoResponse {
    Json(json!({"policy": st.cfg.policy, "n_slots": st.cfg.n_slots, "upstream": st.cfg.upstream,
                "run_id": st.cfg.run_id, "log_dir": st.cfg.log_dir}))
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
    let state = Arc::new(AppState { cfg, client, metrics, seq: AtomicU64::new(0), in_flight: AtomicU64::new(0) });
    let app = Router::new()
        .route("/completion", post(completion))
        .route("/v1/sessions/{id}/events", post(session_event))
        .route("/gateway/stats", get(stats))
        .route("/gateway/config", get(show_config))
        .route("/slots", get(slots))
        .route("/metrics", get(upstream_metrics))
        .route("/health", get(health))
        .with_state(state.clone());
    let listener = tokio::net::TcpListener::bind(&listen).await.expect("bind");
    eprintln!("gateway listening on {listen} policy={:?} n_slots={}", state.cfg.policy, state.cfg.n_slots);
    axum::serve(listener, app).await.expect("serve");
}
