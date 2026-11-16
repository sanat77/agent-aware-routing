use clap::{Parser, ValueEnum};

#[derive(Copy, Clone, Debug, PartialEq, Eq, ValueEnum, serde::Serialize)]
#[serde(rename_all = "snake_case")]
#[value(rename_all = "snake_case")]
pub enum PolicyKind {
    /// Baseline A: forward unchanged but force `cache_prompt=false`.
    NoCache,
    /// Baseline B: forward unchanged; llama.cpp chooses the slot (LCP similarity / LRU) and caches.
    Passthrough,
    /// Baseline C: pin every session to `fnv1a(session_id) % n_slots`.
    SessionAffinity,
}

#[derive(Parser, Debug, Clone)]
#[command(about = "Inference gateway for agent workloads in front of llama-server")]
pub struct Config {
    #[arg(long, default_value = "127.0.0.1:8080")]
    pub listen: String,
    #[arg(long, default_value = "http://127.0.0.1:8090")]
    pub upstream: String,
    #[arg(long, value_enum, default_value = "passthrough")]
    pub policy: PolicyKind,
    /// Number of llama-server slots (`-np`). Verified against GET /props at start-up.
    #[arg(long, default_value_t = 4)]
    pub n_slots: usize,
    /// Directory for JSONL request/event logs.
    #[arg(long, default_value = "gateway_logs")]
    pub log_dir: String,
    #[arg(long, default_value = "run")]
    pub run_id: String,
    /// Upstream request timeout (seconds).
    #[arg(long, default_value_t = 900)]
    pub upstream_timeout_s: u64,
}
