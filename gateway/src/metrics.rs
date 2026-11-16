//! MetricsCollector: per-request JSONL records, lifecycle events, and in-memory aggregates.

use serde_json::{json, Value};
use std::collections::HashMap;
use std::fs::{create_dir_all, OpenOptions};
use std::io::{BufWriter, Write};
use std::path::PathBuf;
use std::sync::Mutex;
use tokio::sync::mpsc;

pub struct MetricsCollector {
    tx: mpsc::UnboundedSender<(String, Value)>,
    agg: Mutex<Aggregates>,
}

#[derive(Default, serde::Serialize)]
pub struct Aggregates {
    pub requests: u64,
    pub errors: u64,
    pub prompt_tokens: u64,
    pub cached_tokens: u64,
    pub predicted_tokens: u64,
    pub per_slot_requests: HashMap<i64, u64>,
    pub routing_overhead_us_total: f64,
    pub gateway_overhead_ms_total: f64,
    pub events: u64,
}

impl MetricsCollector {
    pub fn new(log_dir: &str) -> std::io::Result<Self> {
        let dir = PathBuf::from(log_dir);
        create_dir_all(&dir)?;
        let (tx, mut rx) = mpsc::unbounded_channel::<(String, Value)>();
        let dir2 = dir.clone();
        // Single writer thread: keeps file IO off the request path and preserves ordering.
        std::thread::spawn(move || {
            let mut files: HashMap<String, BufWriter<std::fs::File>> = HashMap::new();
            while let Some((stream, record)) = rx.blocking_recv() {
                let f = files.entry(stream.clone()).or_insert_with(|| {
                    let path = dir2.join(format!("{stream}.jsonl"));
                    BufWriter::new(OpenOptions::new().create(true).append(true).open(path).expect("open log"))
                });
                let _ = writeln!(f, "{}", record);
                let _ = f.flush();
            }
        });
        Ok(Self { tx, agg: Mutex::new(Aggregates::default()) })
    }

    pub fn log(&self, stream: &str, record: Value) {
        let _ = self.tx.send((stream.to_string(), record));
    }

    pub fn record_request(&self, rec: &Value) {
        {
            let mut a = self.agg.lock().unwrap();
            a.requests += 1;
            if rec["error"].is_string() {
                a.errors += 1;
            }
            a.prompt_tokens += rec["prompt_tokens"].as_u64().unwrap_or(0);
            a.cached_tokens += rec["cache_n"].as_u64().unwrap_or(0);
            a.predicted_tokens += rec["predicted_n"].as_u64().unwrap_or(0);
            *a.per_slot_requests.entry(rec["served_slot"].as_i64().unwrap_or(-1)).or_insert(0) += 1;
            a.routing_overhead_us_total += rec["routing_decision_us"].as_f64().unwrap_or(0.0);
            a.gateway_overhead_ms_total += rec["gateway_overhead_ms"].as_f64().unwrap_or(0.0);
        }
        self.log("requests", rec.clone());
    }

    pub fn record_event(&self, rec: Value) {
        self.agg.lock().unwrap().events += 1;
        self.log("events", rec);
    }

    pub fn snapshot(&self) -> Value {
        let a = self.agg.lock().unwrap();
        json!(&*a)
    }
}

pub fn now_unix_ms() -> f64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs_f64() * 1000.0
}
