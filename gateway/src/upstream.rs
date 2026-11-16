//! Streaming client for llama-server's native `/completion` endpoint.
//!
//! The gateway always streams from upstream so it can timestamp the first generated token (TTFT),
//! then returns one aggregated JSON document to the caller.

use futures_util::StreamExt;
use serde_json::Value;
use std::time::Instant;

#[derive(Debug, Default, Clone, serde::Serialize)]
pub struct UpstreamResult {
    pub status: u16,
    pub content: String,
    /// Final chunk from llama-server (timings, id_slot, tokens_cached, stop_type ...)
    pub final_chunk: Value,
    /// ms from sending the upstream request to the first streamed token
    pub upstream_ttft_ms: f64,
    /// ms from sending the upstream request to the end of the stream
    pub upstream_total_ms: f64,
    pub error: Option<String>,
}

pub async fn stream_completion(client: &reqwest::Client, base: &str, mut body: Value) -> UpstreamResult {
    body["stream"] = Value::Bool(true);
    let started = Instant::now();
    let mut out = UpstreamResult::default();
    let resp = match client.post(format!("{base}/completion")).json(&body).send().await {
        Ok(r) => r,
        Err(e) => {
            out.status = 502;
            out.error = Some(format!("upstream connect: {e}"));
            out.upstream_total_ms = ms(started);
            return out;
        }
    };
    out.status = resp.status().as_u16();
    if !resp.status().is_success() {
        let text = resp.text().await.unwrap_or_default();
        out.error = Some(format!("upstream status {}: {}", out.status, truncate(&text, 500)));
        out.upstream_total_ms = ms(started);
        return out;
    }
    let mut stream = resp.bytes_stream();
    let mut buf: Vec<u8> = Vec::with_capacity(8192);
    let mut first = true;
    while let Some(chunk) = stream.next().await {
        let chunk = match chunk {
            Ok(c) => c,
            Err(e) => {
                out.error = Some(format!("upstream stream: {e}"));
                break;
            }
        };
        buf.extend_from_slice(&chunk);
        // SSE events are separated by a blank line; each data line holds one JSON object.
        while let Some(pos) = find_line_end(&buf) {
            let line: Vec<u8> = buf.drain(..pos + 1).collect();
            let line = String::from_utf8_lossy(&line);
            let line = line.trim();
            let Some(data) = line.strip_prefix("data:") else { continue };
            let data = data.trim();
            if data.is_empty() || data == "[DONE]" {
                continue;
            }
            let Ok(v) = serde_json::from_str::<Value>(data) else { continue };
            if v.get("error").is_some() {
                out.error = Some(truncate(&v["error"].to_string(), 500));
            }
            if let Some(piece) = v.get("content").and_then(|c| c.as_str()) {
                if first && v.get("stop") != Some(&Value::Bool(true)) {
                    out.upstream_ttft_ms = ms(started);
                    first = false;
                }
                out.content.push_str(piece);
            }
            if v.get("stop") == Some(&Value::Bool(true)) {
                if first {
                    out.upstream_ttft_ms = ms(started);
                    first = false;
                }
                out.final_chunk = v;
            }
        }
    }
    out.upstream_total_ms = ms(started);
    if out.final_chunk.is_null() && out.error.is_none() {
        out.error = Some("upstream stream ended without final chunk".into());
    }
    out
}

fn find_line_end(buf: &[u8]) -> Option<usize> {
    buf.iter().position(|b| *b == b'\n')
}

pub fn ms(t: Instant) -> f64 {
    t.elapsed().as_secs_f64() * 1000.0
}

pub fn truncate(s: &str, n: usize) -> String {
    if s.len() <= n {
        s.to_string()
    } else {
        let mut end = n;
        while !s.is_char_boundary(end) {
            end -= 1;
        }
        format!("{}...", &s[..end])
    }
}
