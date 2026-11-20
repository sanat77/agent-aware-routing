//! Baseline routing policies. They only decide two request fields: `id_slot` and `cache_prompt`.
//! KV tensors always stay inside llama.cpp.

use crate::config::PolicyKind;

#[derive(Debug, Clone, serde::Serialize)]
pub struct Decision {
    /// Slot to pin (`id_slot`), or None to let llama.cpp choose.
    pub slot: Option<usize>,
    /// Value forced into `cache_prompt`, or None to leave the request unchanged.
    pub cache_prompt: Option<bool>,
    pub reason: &'static str,
}

/// 64-bit FNV-1a: stable across processes and machines (unlike std's randomized SipHash).
pub fn fnv1a(s: &str) -> u64 {
    let mut h: u64 = 0xcbf29ce484222325;
    for b in s.as_bytes() {
        h ^= *b as u64;
        h = h.wrapping_mul(0x100000001b3);
    }
    h
}

pub fn decide_baseline(kind: PolicyKind, session_id: Option<&str>, n_slots: usize) -> Decision {
    match kind {
        PolicyKind::NoCache => Decision { slot: None, cache_prompt: Some(false), reason: "no_cache" },
        PolicyKind::Passthrough => Decision { slot: None, cache_prompt: None, reason: "native" },
        PolicyKind::SessionAffinity => match session_id {
            Some(sid) => Decision {
                slot: Some((fnv1a(sid) % n_slots as u64) as usize),
                cache_prompt: None,
                reason: "hash_affinity",
            },
            None => Decision { slot: None, cache_prompt: None, reason: "no_session_header" },
        },
        // Slot choice for session_cache is made by sessions::Manager; nothing to force here.
        PolicyKind::SessionCache => Decision { slot: None, cache_prompt: None, reason: "session_cache" },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fnv_is_stable() {
        assert_eq!(fnv1a(""), 0xcbf29ce484222325);
        assert_eq!(fnv1a("a"), 0xaf63dc4c8601ec8c);
    }

    #[test]
    fn affinity_is_sticky_and_in_range() {
        for i in 0..100 {
            let sid = format!("sess-{i}");
            let a = decide_baseline(PolicyKind::SessionAffinity, Some(&sid), 4);
            let b = decide_baseline(PolicyKind::SessionAffinity, Some(&sid), 4);
            assert_eq!(a.slot, b.slot);
            assert!(a.slot.unwrap() < 4);
        }
    }

    #[test]
    fn no_cache_forces_flag() {
        let d = decide_baseline(PolicyKind::NoCache, Some("x"), 4);
        assert_eq!(d.cache_prompt, Some(false));
        assert_eq!(d.slot, None);
    }

    #[test]
    fn passthrough_changes_nothing() {
        let d = decide_baseline(PolicyKind::Passthrough, Some("x"), 4);
        assert_eq!(d.cache_prompt, None);
        assert_eq!(d.slot, None);
    }
}
