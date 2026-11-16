"""Generate the immutable 1,000-episode master manifest.

Layout
  * 5 workloads x 200 episodes. Workload w receives variations [8w, 8w+8) of every one of the 25 bug categories,
    so every workload sees every category exactly 8 times and no (category, variation) pair repeats.
  * Global order interleaves workloads (episode i -> workload i % 5) and, within a workload, walks "rounds" that
    each contain all 25 categories in a seeded order. Every prefix (50, 100, 500, 1000) is therefore stratified.
  * Tiers: [0,50) [50,100) [100,500) [500,1000). Cumulative execution runs tiers in order.
  * Within a (tier, workload) the episodes are chunked into groups; a group is one arrival wave with its own
    concurrency, arrival offsets and per-tool-call delay schedule.

Usage: python -m bench.manifest [--out manifests/master_manifest.jsonl]
"""
import argparse
import hashlib
import json
import math
import random
from pathlib import Path

from faultlab.catalog import CATEGORIES, VARIATIONS_PER_CATEGORY
from faultlab.injector import episode_spec

MASTER_SEED = 20261115
WORKLOADS = ("repeated_prefix", "concurrent", "tool_wait", "bursty", "unique_prefix")
TIERS = ((0, 50), (50, 100), (100, 500), (500, 1000))
MAX_TOOL_CALLS = 24

WORKLOAD_SPEC = {
    # purpose, concurrency (active-session cap), group size, arrival rule, tool-delay rule, prompt mode
    "repeated_prefix": dict(purpose="prompt-cache reuse across turns and across sessions sharing one system prompt",
                            concurrency=[1], group_size=[5], arrival="closed_loop", delay=("zero",),
                            context_mode="append", unique_nonce=False, resumable=False),
    "concurrent": dict(purpose="slot competition with 2/4/8 simultaneous sessions",
                       concurrency=[2, 4, 8], group_size=[2, 4, 8], arrival="simultaneous_jitter_1s",
                       delay=("uniform", 0.0, 1.0), context_mode="append", unique_nonce=False, resumable=False),
    "tool_wait": dict(purpose="cache retention across long tool waits with LangGraph interrupt/resume",
                      concurrency=[4], group_size=[4], arrival="stagger_2s", delay=("lognormal", 6.0, 0.6, 1.0, 30.0),
                      context_mode="append", unique_nonce=False, resumable=True),
    "bursty": dict(purpose="bursts larger than the slot count, causing queueing and cache pressure",
                   concurrency=[8], group_size=[10], arrival="burst_0.5s", delay=("uniform", 0.0, 0.5),
                   context_mode="append", unique_nonce=False, resumable=False),
    "unique_prefix": dict(purpose="control: unique per-session preamble and a per-turn header defeat prefix reuse",
                          concurrency=[4], group_size=[4], arrival="stagger_1s", delay=("uniform", 0.0, 1.0),
                          context_mode="rewrite_header", unique_nonce=True, resumable=False),
}


def _seed(*parts):
    return int(hashlib.sha256(":".join(map(str, (MASTER_SEED, *parts))).encode()).hexdigest()[:12], 16)


def _delays(rule, rng):
    kind = rule[0]
    if kind == "zero":
        return [0.0] * MAX_TOOL_CALLS
    if kind == "uniform":
        return [round(rng.uniform(rule[1], rule[2]), 3) for _ in range(MAX_TOOL_CALLS)]
    if kind == "lognormal":
        median, sigma, lo, hi = rule[1:]
        return [round(min(hi, max(lo, rng.lognormvariate(math.log(median), sigma))), 3)
                for _ in range(MAX_TOOL_CALLS)]
    raise ValueError(kind)


def _arrivals(rule, n, rng):
    if rule in ("closed_loop",):
        return [0.0] * n
    if rule == "simultaneous_jitter_1s":
        return sorted(round(rng.uniform(0, 1.0), 3) for _ in range(n))
    if rule == "stagger_2s":
        return [round(2.0 * i + rng.uniform(0, 0.2), 3) for i in range(n)]
    if rule == "stagger_1s":
        return [round(1.0 * i + rng.uniform(0, 0.2), 3) for i in range(n)]
    if rule == "burst_0.5s":
        return sorted(round(rng.uniform(0, 0.5), 3) for _ in range(n))
    raise ValueError(rule)


def workload_queues():
    """Per workload, the ordered list of (category, variation) it will run."""
    queues = {}
    for w, workload in enumerate(WORKLOADS):
        items = []
        per_round = VARIATIONS_PER_CATEGORY // len(WORKLOADS)  # 8 rounds
        for r in range(per_round):
            cats = [c.name for c in CATEGORIES]
            random.Random(_seed("round", workload, r)).shuffle(cats)
            items.extend((cat, w * per_round + r) for cat in cats)
        queues[workload] = items
    return queues


def tier_of(i):
    for t, (lo, hi) in enumerate(TIERS):
        if lo <= i < hi:
            return t
    raise ValueError(i)


def build():
    queues = workload_queues()
    episodes = []
    counters = {w: 0 for w in WORKLOADS}
    for i in range(1000):
        workload = WORKLOADS[i % len(WORKLOADS)]
        cat, v = queues[workload][counters[workload]]
        counters[workload] += 1
        spec = episode_spec(cat, v)
        seed = _seed("episode", i)
        episodes.append({
            "episode_id": f"ep{i:04d}",
            "index": i,
            "tier": tier_of(i),
            "seed": seed,
            "workload": workload,
            "bug_category": cat,
            "bug_variation": v,
            "fault_id": spec["fault_id"],
            "repository_fixture": {"base": "miniissuetracker", "fault": f"{cat}/{spec['fault_id']}",
                                   "variation": v},
            "issue": spec["issue"],
            "visible_test": spec["visible_test"],
            "expected_result": {"visible_test": "pass", "hidden_bug_tests": "all_pass",
                                "regression_suite": "all_pass", "reference_fix": f"revert {spec['fault_id']}"},
            "session_id": f"sess-{i:04d}-{hashlib.sha1(str(seed).encode()).hexdigest()[:8]}",
            "prompt_nonce": hashlib.sha1(f"nonce:{seed}".encode()).hexdigest()[:16],
        })
    # groups, arrivals, delays, concurrency per (tier, workload)
    for t in range(len(TIERS)):
        for workload in WORKLOADS:
            spec = WORKLOAD_SPEC[workload]
            members = [e for e in episodes if e["tier"] == t and e["workload"] == workload]
            g = 0
            pos = 0
            while pos < len(members):
                size = spec["group_size"][g % len(spec["group_size"])]
                conc = spec["concurrency"][g % len(spec["concurrency"])]
                group = members[pos:pos + size]
                rng = random.Random(_seed("group", t, workload, g))
                arrivals = _arrivals(spec["arrival"], len(group), rng)
                for k, (e, a) in enumerate(zip(group, arrivals)):
                    drng = random.Random(_seed("delays", e["index"]))
                    e.update({
                        "group_id": f"t{t}-{workload}-g{g:03d}",
                        "group_position": k,
                        "group_size": len(group),
                        "concurrency": conc,
                        "arrival_offset_s": a,
                        "arrival_rule": spec["arrival"],
                        "tool_delays_s": _delays(spec["delay"], drng),
                        "context_mode": spec["context_mode"],
                        "unique_nonce": spec["unique_nonce"],
                        "resumable": spec["resumable"],
                    })
                pos += size
                g += 1
    return episodes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="manifests/master_manifest.jsonl")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    out = Path(args.out)
    episodes = build()
    text = "".join(json.dumps(e, sort_keys=True) + "\n" for e in episodes)
    digest = hashlib.sha256(text.encode()).hexdigest()
    if out.exists() and not args.force:
        existing = hashlib.sha256(out.read_bytes()).hexdigest()
        if existing != digest:
            raise SystemExit(f"{out} exists with a different digest ({existing}); refusing to overwrite (immutable)")
        print(f"manifest unchanged: {digest}")
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    meta = {"sha256": digest, "episodes": len(episodes), "master_seed": MASTER_SEED, "tiers": TIERS,
            "workloads": {w: {k: v for k, v in s.items()} for w, s in WORKLOAD_SPEC.items()},
            "per_workload": {w: sum(e["workload"] == w for e in episodes) for w in WORKLOADS},
            "per_category": {c.name: sum(e["bug_category"] == c.name for e in episodes) for c in CATEGORIES}}
    (out.parent / "master_manifest.meta.json").write_text(json.dumps(meta, indent=1))
    print(f"wrote {len(episodes)} episodes to {out} sha256={digest}")


def load(path="manifests/master_manifest.jsonl"):
    return [json.loads(l) for l in Path(path).read_text().splitlines()]


if __name__ == "__main__":
    main()
