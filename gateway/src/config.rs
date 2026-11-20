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
    /// Step 2 (setup S3): session-aware slot management. Finished sessions are erased first, paused
    /// sessions are saved to disk before their slot is reused and restored when they return.
    SessionCache,
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
    /// Identifier of the inference server this gateway fronts (reported in every response).
    #[arg(long, default_value = "w0")]
    pub server_id: String,
    /// URL at which agents reach this gateway for lifecycle events (defaults to http://<listen>).
    #[arg(long)]
    pub public_url: Option<String>,
    /// Local directory that llama-server uses for --slot-save-path. When set, the gateway deletes
    /// stale session files and enforces --save-budget-mb.
    #[arg(long)]
    pub slot_save_dir: Option<String>,
    /// Upper bound for bytes of saved session caches kept on disk (session_cache policy).
    #[arg(long, default_value_t = 12000)]
    pub save_budget_mb: u64,
    /// Interval for slot-occupancy snapshots written to occupancy.jsonl (0 disables).
    #[arg(long, default_value_t = 1000)]
    pub snapshot_interval_ms: u64,
}
