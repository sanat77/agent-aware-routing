//! Session-aware slot management (step 2).
//!
//! The gateway sits in front of ONE llama-server with N slots. llama.cpp owns the KV tensors; this module
//! only decides which slot a session's request runs on, and uses llama.cpp's own slot commands
//! (`erase`, `save`, `restore`) to keep the cache of live sessions and drop the cache of finished ones.
//!
//! Victim order when a session needs a slot it does not already hold:
//!   1. an empty slot
//!   2. a slot held by a FINISHED session        -> erase it first (nothing worth keeping)
//!   3. a slot held by a session WAITING on a tool (longest waiting first) -> save it to disk, then reuse
//!   4. a slot held by an ACTIVE but idle session (least recently used)    -> save it to disk, then reuse
//! A session whose cache was saved to disk gets it restored into the slot it is given.
//!
//! The same bookkeeping runs in passthrough mode (S1/S2) from observed slot usage, so the "memory held by
//! finished sessions" and "live sessions evicted while dead caches stayed resident" metrics are comparable.

use std::collections::HashMap;
use std::time::Instant;

#[derive(Copy, Clone, Debug, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SessState {
    Active,
    Waiting,
    Finished,
}

#[derive(Clone, Debug)]
pub struct SavedFile {
    pub name: String,
    pub bytes: u64,
    pub tokens: u64,
    pub at: Instant,
}

#[derive(Clone, Debug)]
pub struct Session {
    pub state: SessState,
    pub parent: Option<String>,
    pub role: Option<String>,
    /// Slot whose current content belongs to this session (None if overwritten or never assigned).
    pub slot: Option<usize>,
    pub saved: Option<SavedFile>,
    pub last_seen: Instant,
    pub waiting_since: Option<Instant>,
    pub expected_wait_ms: Option<f64>,
    pub tokens: u64,
    pub requests: u64,
}

impl Session {
    fn new(now: Instant) -> Self {
        Self { state: SessState::Active, parent: None, role: None, slot: None, saved: None, last_seen: now,
               waiting_since: None, expected_wait_ms: None, tokens: 0, requests: 0 }
    }
}

#[derive(Clone, Debug, Default)]
pub struct Slot {
    pub occupant: Option<String>,
    pub busy: bool,
    pub tokens: u64,
    pub last_used: Option<Instant>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Victim {
    /// The slot is empty.
    Empty,
    /// Held by a finished session: erase before reuse.
    Dead(String),
    /// Held by a live session: save its cache to disk before reuse.
    Live(String),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Plan {
    /// The session's own cache is resident in an idle slot.
    Warm { slot: usize },
    /// Take `slot` (evicting `victim`), optionally restoring the session's saved cache file into it.
    Assign { slot: usize, victim: Victim, restore: Option<String> },
    /// Every slot is busy with an in-flight request.
    Wait,
}

#[derive(Clone, Debug, Default, serde::Serialize)]
pub struct Counters {
    pub requests: u64,
    pub warm: u64,
    pub assigned_empty: u64,
    pub assigned_over_dead: u64,
    pub assigned_over_live: u64,
    pub restores: u64,
    pub restore_failures: u64,
    pub saves: u64,
    pub save_failures: u64,
    pub erases: u64,
    pub erases_on_finish: u64,
    pub waits: u64,
    pub wait_ms_total: f64,
    pub save_ms_total: f64,
    pub restore_ms_total: f64,
    pub saved_files_deleted: u64,
    /// A live session's slot was reused for another session (its cache left the slot).
    pub live_evictions: u64,
    /// ... while another slot was holding a finished session's cache at that moment (avoidable).
    pub avoidable_live_evictions: u64,
    pub dead_evictions: u64,
}

pub struct Manager {
    pub sessions: HashMap<String, Session>,
    pub slots: Vec<Slot>,
    pub saved_bytes: u64,
    pub counters: Counters,
}

impl Manager {
    pub fn new(n_slots: usize) -> Self {
        Self { sessions: HashMap::new(), slots: vec![Slot::default(); n_slots], saved_bytes: 0,
               counters: Counters::default() }
    }

    pub fn touch(&mut self, sid: &str, parent: Option<String>, role: Option<String>, now: Instant) -> &mut Session {
        let s = self.sessions.entry(sid.to_string()).or_insert_with(|| Session::new(now));
        if s.parent.is_none() {
            s.parent = parent;
        }
        if s.role.is_none() {
            s.role = role;
        }
        s.last_seen = now;
        if s.state != SessState::Active {
            s.state = SessState::Active;
            s.waiting_since = None;
        }
        s
    }

    fn state_of(&self, sid: &str) -> SessState {
        self.sessions.get(sid).map(|s| s.state).unwrap_or(SessState::Finished)
    }

    /// Pure planning step: no side effects. Deterministic for a given state.
    pub fn plan(&self, sid: &str, now: Instant) -> Plan {
        if let Some(sess) = self.sessions.get(sid) {
            if let Some(slot) = sess.slot {
                let s = &self.slots[slot];
                if s.occupant.as_deref() == Some(sid) && !s.busy {
                    return Plan::Warm { slot };
                }
            }
        }
        let restore = self.sessions.get(sid).and_then(|s| s.saved.as_ref()).map(|f| f.name.clone());
        let idle: Vec<usize> = (0..self.slots.len()).filter(|&i| !self.slots[i].busy).collect();
        if idle.is_empty() {
            return Plan::Wait;
        }
        // 1. empty
        if let Some(&i) = idle.iter().find(|&&i| self.slots[i].occupant.is_none()) {
            return Plan::Assign { slot: i, victim: Victim::Empty, restore };
        }
        // 2. finished occupant (largest first: frees the most dead tokens)
        let mut dead: Vec<usize> = idle.iter().copied()
            .filter(|&i| self.state_of(self.slots[i].occupant.as_deref().unwrap()) == SessState::Finished)
            .collect();
        dead.sort_by_key(|&i| (std::cmp::Reverse(self.slots[i].tokens), i));
        if let Some(&i) = dead.first() {
            let v = self.slots[i].occupant.clone().unwrap();
            return Plan::Assign { slot: i, victim: Victim::Dead(v), restore };
        }
        // 3. waiting on a tool, longest waiting first
        let mut waiting: Vec<(u128, usize)> = idle.iter().copied()
            .filter_map(|i| {
                let occ = self.slots[i].occupant.as_deref().unwrap();
                let s = self.sessions.get(occ)?;
                (s.state == SessState::Waiting)
                    .then(|| (now.duration_since(s.waiting_since.unwrap_or(s.last_seen)).as_micros(), i))
            })
            .collect();
        waiting.sort_by_key(|&(age, i)| (std::cmp::Reverse(age), i));
        if let Some(&(_, i)) = waiting.first() {
            let v = self.slots[i].occupant.clone().unwrap();
            return Plan::Assign { slot: i, victim: Victim::Live(v), restore };
        }
        // 4. least recently used active-idle slot
        let i = *idle.iter()
            .min_by_key(|&&i| (self.slots[i].last_used.map(|t| now.duration_since(t)).map(|d| u128::MAX - d.as_micros()).unwrap_or(0), i))
            .unwrap();
        let v = self.slots[i].occupant.clone().unwrap();
        Plan::Assign { slot: i, victim: Victim::Live(v), restore }
    }

    fn any_other_dead(&self, except: usize) -> bool {
        self.slots.iter().enumerate().any(|(i, s)| {
            i != except && !s.busy && s.occupant.as_deref().map(|o| self.state_of(o) == SessState::Finished).unwrap_or(false)
        })
    }

    /// Record that `slot` now holds `sid` (called when a plan is committed, or when a passthrough request
    /// reports which slot served it). Updates eviction counters.
    pub fn occupy(&mut self, slot: usize, sid: &str) {
        let prev = self.slots[slot].occupant.clone();
        if let Some(p) = prev.as_deref() {
            if p != sid {
                match self.state_of(p) {
                    SessState::Finished => self.counters.dead_evictions += 1,
                    _ => {
                        self.counters.live_evictions += 1;
                        if self.any_other_dead(slot) {
                            self.counters.avoidable_live_evictions += 1;
                        }
                    }
                }
                if let Some(ps) = self.sessions.get_mut(p) {
                    if ps.slot == Some(slot) {
                        ps.slot = None;
                    }
                }
            }
        }
        // a session's cache lives in at most one slot we track
        if let Some(s) = self.sessions.get_mut(sid) {
            if let Some(old) = s.slot {
                if old != slot && self.slots[old].occupant.as_deref() == Some(sid) {
                    self.slots[old].occupant = None;
                    self.slots[old].tokens = 0;
                }
            }
            s.slot = Some(slot);
        }
        self.slots[slot].occupant = Some(sid.to_string());
    }

    pub fn release(&mut self, slot: usize, sid: &str, tokens: u64, now: Instant) {
        let s = &mut self.slots[slot];
        s.busy = false;
        s.tokens = tokens;
        s.last_used = Some(now);
        if let Some(sess) = self.sessions.get_mut(sid) {
            sess.tokens = tokens;
            sess.last_seen = now;
            sess.requests += 1;
        }
    }

    pub fn set_state(&mut self, sid: &str, state: SessState, expected_wait_ms: Option<f64>, now: Instant) {
        let s = self.sessions.entry(sid.to_string()).or_insert_with(|| Session::new(now));
        s.state = state;
        s.last_seen = now;
        match state {
            SessState::Waiting => {
                s.waiting_since = Some(now);
                s.expected_wait_ms = expected_wait_ms;
            }
            _ => s.waiting_since = None,
        }
    }

    /// Slot to erase right away because its finished occupant left it idle.
    pub fn erasable_after_finish(&self, sid: &str) -> Option<usize> {
        let s = self.sessions.get(sid)?;
        let slot = s.slot?;
        let st = &self.slots[slot];
        (st.occupant.as_deref() == Some(sid) && !st.busy).then_some(slot)
    }

    pub fn clear_slot(&mut self, slot: usize) {
        if let Some(occ) = self.slots[slot].occupant.take() {
            if let Some(s) = self.sessions.get_mut(&occ) {
                if s.slot == Some(slot) {
                    s.slot = None;
                }
            }
        }
        self.slots[slot].tokens = 0;
    }

    pub fn dead_tokens_resident(&self) -> u64 {
        self.slots.iter()
            .filter(|s| s.occupant.as_deref().map(|o| self.state_of(o) == SessState::Finished).unwrap_or(false))
            .map(|s| s.tokens)
            .sum()
    }

    pub fn snapshot(&self) -> serde_json::Value {
        let slots: Vec<serde_json::Value> = self.slots.iter().enumerate().map(|(i, s)| {
            let st = s.occupant.as_deref().map(|o| self.state_of(o));
            serde_json::json!({"slot": i, "occupant": s.occupant, "state": st, "busy": s.busy, "tokens": s.tokens})
        }).collect();
        let live = self.sessions.values().filter(|s| s.state != SessState::Finished).count();
        let waiting = self.sessions.values().filter(|s| s.state == SessState::Waiting).count();
        serde_json::json!({
            "slots": slots,
            "dead_tokens_resident": self.dead_tokens_resident(),
            "live_sessions": live,
            "waiting_sessions": waiting,
            "saved_files": self.sessions.values().filter(|s| s.saved.is_some()).count(),
            "saved_tokens": self.sessions.values().filter_map(|s| s.saved.as_ref()).map(|f| f.tokens).sum::<u64>(),
            "saved_bytes": self.saved_bytes,
        })
    }
}

/// File name llama-server accepts for slot save/restore (no path separators).
pub fn session_filename(sid: &str) -> String {
    let clean: String = sid.chars().map(|c| if c.is_ascii_alphanumeric() || c == '-' || c == '_' { c } else { '_' }).collect();
    format!("sess_{clean}.bin")
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    fn mgr(n: usize) -> (Manager, Instant) {
        (Manager::new(n), Instant::now())
    }

    fn put(m: &mut Manager, slot: usize, sid: &str, state: SessState, tokens: u64, t: Instant) {
        m.touch(sid, None, None, t);
        m.occupy(slot, sid);
        m.release(slot, sid, tokens, t);
        m.set_state(sid, state, None, t);
    }

    #[test]
    fn warm_slot_is_reused() {
        let (mut m, t) = mgr(2);
        put(&mut m, 1, "a", SessState::Active, 100, t);
        assert_eq!(m.plan("a", t), Plan::Warm { slot: 1 });
    }

    #[test]
    fn empty_slot_preferred_over_any_eviction() {
        let (mut m, t) = mgr(3);
        put(&mut m, 0, "dead", SessState::Finished, 500, t);
        put(&mut m, 1, "wait", SessState::Waiting, 500, t);
        assert_eq!(m.plan("new", t), Plan::Assign { slot: 2, victim: Victim::Empty, restore: None });
    }

    #[test]
    fn finished_session_evicted_before_live_ones() {
        let (mut m, t) = mgr(3);
        put(&mut m, 0, "live", SessState::Active, 900, t);
        put(&mut m, 1, "wait", SessState::Waiting, 900, t);
        put(&mut m, 2, "dead", SessState::Finished, 10, t);
        assert_eq!(m.plan("new", t), Plan::Assign { slot: 2, victim: Victim::Dead("dead".into()), restore: None });
    }

    #[test]
    fn longest_waiting_session_saved_before_active_idle() {
        let (mut m, t0) = mgr(3);
        put(&mut m, 0, "active", SessState::Active, 100, t0);
        put(&mut m, 1, "w_recent", SessState::Waiting, 100, t0);
        put(&mut m, 2, "w_old", SessState::Waiting, 100, t0);
        let t1 = t0 + Duration::from_secs(1);
        m.set_state("w_recent", SessState::Waiting, None, t1);
        let t2 = t0 + Duration::from_secs(5);
        assert_eq!(m.plan("new", t2), Plan::Assign { slot: 2, victim: Victim::Live("w_old".into()), restore: None });
    }

    #[test]
    fn lru_active_idle_when_nothing_else() {
        let (mut m, t0) = mgr(2);
        put(&mut m, 0, "old", SessState::Active, 100, t0);
        let t1 = t0 + Duration::from_secs(3);
        put(&mut m, 1, "recent", SessState::Active, 100, t1);
        assert_eq!(m.plan("new", t1), Plan::Assign { slot: 0, victim: Victim::Live("old".into()), restore: None });
    }

    #[test]
    fn busy_slots_are_never_planned() {
        let (mut m, t) = mgr(2);
        m.touch("a", None, None, t);
        m.occupy(0, "a");
        m.slots[0].busy = true;
        m.touch("b", None, None, t);
        m.occupy(1, "b");
        m.slots[1].busy = true;
        assert_eq!(m.plan("c", t), Plan::Wait);
        // the session's own slot being busy also means wait (one request per session at a time)
        assert_eq!(m.plan("a", t), Plan::Wait);
    }

    #[test]
    fn saved_session_is_restored_into_assigned_slot() {
        let (mut m, t) = mgr(1);
        put(&mut m, 0, "other", SessState::Finished, 10, t);
        m.touch("s", None, None, t);
        m.sessions.get_mut("s").unwrap().saved =
            Some(SavedFile { name: session_filename("s"), bytes: 1, tokens: 5, at: t });
        assert_eq!(m.plan("s", t), Plan::Assign { slot: 0, victim: Victim::Dead("other".into()),
                                                   restore: Some("sess_s.bin".into()) });
    }

    #[test]
    fn avoidable_eviction_is_counted() {
        let (mut m, t) = mgr(2);
        put(&mut m, 0, "live", SessState::Active, 100, t);
        put(&mut m, 1, "dead", SessState::Finished, 100, t);
        // a passthrough server reuses the LIVE slot although the dead one was available
        m.touch("new", None, None, t);
        m.occupy(0, "new");
        assert_eq!(m.counters.live_evictions, 1);
        assert_eq!(m.counters.avoidable_live_evictions, 1);
        assert_eq!(m.sessions["live"].slot, None);
    }

    #[test]
    fn dead_tokens_tracked_and_cleared() {
        let (mut m, t) = mgr(2);
        put(&mut m, 0, "d", SessState::Finished, 700, t);
        put(&mut m, 1, "l", SessState::Active, 300, t);
        assert_eq!(m.dead_tokens_resident(), 700);
        assert_eq!(m.erasable_after_finish("d"), Some(0));
        m.clear_slot(0);
        assert_eq!(m.dead_tokens_resident(), 0);
        assert_eq!(m.sessions["d"].slot, None);
    }

    #[test]
    fn moving_session_to_new_slot_frees_old_tracking() {
        let (mut m, t) = mgr(2);
        put(&mut m, 0, "s", SessState::Active, 100, t);
        m.occupy(1, "s");
        assert_eq!(m.slots[0].occupant, None);
        assert_eq!(m.sessions["s"].slot, Some(1));
    }

    #[test]
    fn request_reactivates_waiting_session() {
        let (mut m, t) = mgr(1);
        put(&mut m, 0, "s", SessState::Waiting, 100, t);
        m.touch("s", None, None, t);
        assert_eq!(m.sessions["s"].state, SessState::Active);
    }

    #[test]
    fn filenames_are_sanitized() {
        assert_eq!(session_filename("sess-0001-ab/../x"), "sess_sess-0001-ab____x.bin");
    }
}
