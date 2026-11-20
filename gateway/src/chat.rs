//! OpenAI chat-completions adapter. llm-router only speaks `/v1/chat/completions`; the gateway renders the
//! messages with the model's chat template and runs them through llama-server's native `/completion`
//! endpoint, which reports the serving slot and per-request cache statistics that the chat endpoint omits.

use serde_json::{json, Value};

const PASS_THROUGH: &[&str] = &[
    "temperature", "top_k", "top_p", "min_p", "seed", "stop", "cache_prompt", "n_keep", "repeat_penalty",
    "presence_penalty", "frequency_penalty", "json_schema", "grammar", "n_probs", "samplers", "ignore_eos",
];

pub fn to_completion_body(chat: &Value, prompt: String) -> Value {
    let mut b = json!({ "prompt": prompt });
    for k in PASS_THROUGH {
        if let Some(v) = chat.get(*k) {
            b[*k] = v.clone();
        }
    }
    if let Some(n) = chat.get("max_completion_tokens").or_else(|| chat.get("max_tokens")).or_else(|| chat.get("n_predict")) {
        b["n_predict"] = n.clone();
    }
    if let Some(rf) = chat.get("response_format") {
        match rf.get("type").and_then(|t| t.as_str()) {
            Some("json_schema") => {
                if let Some(s) = rf.get("json_schema").and_then(|j| j.get("schema")) {
                    b["json_schema"] = s.clone();
                }
            }
            Some("json_object") => {
                b["json_schema"] = rf.get("schema").cloned().unwrap_or_else(|| json!({}));
            }
            _ => {}
        }
    }
    b
}

pub fn finish_reason(stop_type: &Value) -> &'static str {
    match stop_type.as_str() {
        Some("limit") => "length",
        _ => "stop",
    }
}

pub fn to_chat_response(request_id: &str, content: &str, final_chunk: &Value, gateway: &Value) -> Value {
    let t = &final_chunk["timings"];
    let prompt_n = t["prompt_n"].as_u64().unwrap_or(0);
    let cache_n = t["cache_n"].as_u64().unwrap_or(0);
    let predicted = t["predicted_n"].as_u64().unwrap_or(0);
    json!({
        "id": format!("chatcmpl-{request_id}"),
        "object": "chat.completion",
        "model": final_chunk.get("model").cloned().unwrap_or(Value::Null),
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": finish_reason(&final_chunk["stop_type"]),
        }],
        "usage": {
            "prompt_tokens": prompt_n + cache_n,
            "completion_tokens": predicted,
            "total_tokens": prompt_n + cache_n + predicted,
            "prompt_tokens_details": {"cached_tokens": cache_n},
        },
        "timings": final_chunk["timings"],
        "id_slot": final_chunk["id_slot"],
        "stop_type": final_chunk["stop_type"],
        "gateway": gateway,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn maps_openai_fields_to_native() {
        let chat = json!({
            "model": "x", "messages": [], "max_tokens": 64, "temperature": 0.0, "seed": 7, "cache_prompt": true,
            "response_format": {"type": "json_schema", "json_schema": {"name": "a", "schema": {"type": "object"}}},
            "stream": true
        });
        let b = to_completion_body(&chat, "P".into());
        assert_eq!(b["prompt"], "P");
        assert_eq!(b["n_predict"], 64);
        assert_eq!(b["seed"], 7);
        assert_eq!(b["json_schema"], json!({"type": "object"}));
        assert!(b.get("stream").is_none());
        assert!(b.get("messages").is_none());
    }

    #[test]
    fn max_completion_tokens_wins() {
        let b = to_completion_body(&json!({"max_tokens": 5, "max_completion_tokens": 9}), "".into());
        assert_eq!(b["n_predict"], 9);
    }

    #[test]
    fn chat_response_reports_cached_tokens() {
        let fc = json!({"timings": {"prompt_n": 3, "cache_n": 97, "predicted_n": 5}, "stop_type": "eos", "id_slot": 1});
        let r = to_chat_response("r1", "hi", &fc, &json!({}));
        assert_eq!(r["usage"]["prompt_tokens"], 100);
        assert_eq!(r["usage"]["prompt_tokens_details"]["cached_tokens"], 97);
        assert_eq!(r["choices"][0]["finish_reason"], "stop");
        assert_eq!(r["choices"][0]["message"]["content"], "hi");
    }
}
