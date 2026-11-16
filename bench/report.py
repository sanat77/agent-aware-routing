"""Aggregate results into JSON/CSV, paired statistics, charts and markdown tables.

Usage:
  python -m bench.report --configs no_cache,native_cache,session_affinity --name baseline
  python -m bench.report --configs no_cache,native_cache,session_affinity,agent_aware_rust --name final
Outputs: reports/generated/<name>_tables.md, reports/generated/<name>_metrics.json, reports/assets/<name>/*.png,
         <results_dir>/<kind>/summary.json and per_episode.csv for every config.
"""
import argparse
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .analyze import analyze_e2e, analyze_replay, per_episode_table  # noqa: E402
from .stats import compare  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EXP = json.loads((ROOT / "configs" / "experiments.json").read_text())
LABELS = {"no_cache": "A no-cache", "native_cache": "B native", "session_affinity": "C affinity",
          "agent_aware_rust": "D agent-aware"}
COLORS = {"no_cache": "#9e9e9e", "native_cache": "#1f77b4", "session_affinity": "#ff7f0e", "agent_aware_rust": "#2ca02c"}
WORKLOADS = ("repeated_prefix", "concurrent", "tool_wait", "bursty", "unique_prefix")


def results_dir(cfg):
    return ROOT / EXP["configs"][cfg]["results_dir"]


def _fmt(v, nd=1):
    if v is None:
        return "n/a"
    if isinstance(v, float):
        if abs(v) >= 1000:
            return f"{v:,.0f}"
        return f"{v:.{nd}f}"
    return str(v)


def _s(m, key="mean", nd=1):
    if not isinstance(m, dict) or m.get("n", 0) == 0:
        return "n/a"
    return _fmt(m.get(key), nd)


def _r(m, pct=True):
    if not isinstance(m, dict) or m.get("value") is None:
        return "n/a"
    return f"{m['value'] * 100:.1f}% ({m['num']}/{m['n']})" if pct else _fmt(m["value"], 2)


def metric_rows(S, kind):
    """(label, extractor) rows for the 20-metric table."""
    lat_key = "5_end_to_end_task_latency_s" if kind == "e2e" else "5_end_to_end_session_latency_s"
    tpm_key = "10_completed_tasks_per_minute" if kind == "e2e" else "10_completed_sessions_per_minute"
    rows = []
    if kind == "e2e":
        rows += [("1 Task success rate", lambda s: _r(s["1_task_success_rate"])),
                 ("2 Hidden test pass rate", lambda s: _r(s["2_hidden_test_pass_rate"])),
                 ("3 Regression-free patch rate", lambda s: _r(s["3_regression_free_patch_rate"])),
                 ("4 Tool-call success rate", lambda s: _r(s["4_tool_call_success_rate"]))]
    else:
        rows += [("1-4 Correctness", lambda s: "not measured in replay (agent decisions are fixed)")]
    rows += [
        ("5 E2E latency p50 / p95 / p99 (s)", lambda s: f"{_s(s[lat_key], 'median')} / {_s(s[lat_key], 'p95')} / {_s(s[lat_key], 'p99')}"),
        ("6 TTFT p50 / p95 / p99 (ms)", lambda s: f"{_s(s['6_ttft_ms'], 'median', 0)} / {_s(s['6_ttft_ms'], 'p95', 0)} / {_s(s['6_ttft_ms'], 'p99', 0)}"),
        ("7 Prefill latency mean / p95 (ms)", lambda s: f"{_s(s['7_prefill_latency_ms'], 'mean', 0)} / {_s(s['7_prefill_latency_ms'], 'p95', 0)}"),
        ("8 Session-resumption latency mean / p95 (ms)", lambda s: f"{_s(s['8_session_resumption_latency_ms'], 'mean', 0)} / {_s(s['8_session_resumption_latency_ms'], 'p95', 0)} (n={s['8_session_resumption_latency_ms'].get('n', 0)})"),
        ("9 Queue wait mean / p95 (ms)", lambda s: f"{_s(s['9_queue_wait_ms'], 'mean', 0)} / {_s(s['9_queue_wait_ms'], 'p95', 0)}"),
        (f"10 {'Successful tasks' if kind == 'e2e' else 'Sessions'} per minute", lambda s: _fmt(s[tpm_key]["value"], 3)),
        ("11 Eligible-request cache-hit rate", lambda s: _r(s["11_eligible_cache_hit_rate"])),
        ("12 Prefix-cache reuse ratio", lambda s: _r(s["12_prefix_cache_reuse_ratio"])),
        ("13 Recomputed prompt tokens (total)", lambda s: _fmt(float(s["13_recomputed_prompt_tokens"]["total"]), 0)),
        ("14 Retention across tool waits (fully retained)", lambda s: _r(s["14_cache_retention_across_tool_waits"]["fully_retained_rate"])),
        ("15 Prefix-loss events / slot switches / host-cache saves", lambda s: f"{s['15_cache_eviction_and_slot_reset_events']['prefix_loss_events']} / {s['15_cache_eviction_and_slot_reset_events']['slot_switches']} / {s['15_cache_eviction_and_slot_reset_events'].get('prompt_cache_saves_to_host_ram')}"),
        ("16 Peak RSS llama / gateway (MiB)", lambda s: (f"{_fmt(s['16_peak_process_ram_mib'].get('llama'), 0)} / {_fmt(s['16_peak_process_ram_mib'].get('gateway'), 0)}" if isinstance(s['16_peak_process_ram_mib'], dict) and 'llama' in s['16_peak_process_ram_mib'] else "n/a")),
        ("17 Mean slot utilization / KV occupancy est.", lambda s: (f"{_fmt(s['17_slot_and_kv_utilization'].get('mean_slot_utilization'), 2)} / {_s(s['17_slot_and_kv_utilization'].get('kv_occupancy_estimate'), 'mean', 2)}" if s['17_slot_and_kv_utilization'].get('mean_slot_utilization') is not None else "n/a")),
        ("18 Slot busy max/mean ; request CV", lambda s: f"{_fmt(s['18_session_load_imbalance']['slot_busy_max_over_mean'], 2)} ; {_fmt(s['18_session_load_imbalance']['request_count_cv'], 2)}"),
        ("19 Routing decision (us) mean / gateway overhead (ms) mean", lambda s: f"{_s(s['19_rust_routing_overhead']['decision_us'], 'mean', 2)} / {_s(s['19_rust_routing_overhead']['gateway_overhead_ms'], 'mean', 2)}"),
        ("20 Model / tool / episode failure rate", lambda s: f"{_r(s['20_failure_rates']['model_request_failures'])} / {_r(s['20_failure_rates']['tool_failures']) if s['20_failure_rates'].get('tool_failures') else 'n/a'} / {_r(s['20_failure_rates']['episode_crashes'])}"),
    ]
    return rows


def table(summaries, kind, configs):
    head = "| Metric | " + " | ".join(LABELS[c] for c in configs) + " |\n|---|" + "---|" * len(configs) + "\n"
    body = ""
    for label, fn in metric_rows(summaries, kind):
        cells = []
        for c in configs:
            try:
                cells.append(fn(summaries[c]))
            except (KeyError, TypeError):
                cells.append("n/a")
        body += f"| {label} | " + " | ".join(cells) + " |\n"
    return head + body


def workload_table(summaries, kind, configs):
    lat_key = "5_end_to_end_task_latency_s" if kind == "e2e" else "5_end_to_end_session_latency_s"
    out = ""
    for w in WORKLOADS:
        if not all(w in summaries[c].get("by_workload", {}) for c in configs):
            continue
        out += f"\n**{w}** (n={summaries[configs[0]]['by_workload'][w]['episodes']} per config)\n\n"
        out += "| Metric | " + " | ".join(LABELS[c] for c in configs) + " |\n|---|" + "---|" * len(configs) + "\n"
        rows = []
        if kind == "e2e":
            rows.append(("Task success", lambda s: _r(s["1_task_success_rate"])))
        rows += [
            ("E2E latency mean / p95 (s)", lambda s: f"{_s(s[lat_key])} / {_s(s[lat_key], 'p95')}"),
            ("TTFT mean / p95 (ms)", lambda s: f"{_s(s['6_ttft_ms'], 'mean', 0)} / {_s(s['6_ttft_ms'], 'p95', 0)}"),
            ("Prefill mean (ms)", lambda s: _s(s["7_prefill_latency_ms"], "mean", 0)),
            ("Queue wait mean (ms)", lambda s: _s(s["9_queue_wait_ms"], "mean", 0)),
            ("Cache-hit rate (eligible)", lambda s: _r(s["11_eligible_cache_hit_rate"])),
            ("Prefix reuse ratio", lambda s: _r(s["12_prefix_cache_reuse_ratio"])),
            ("Recomputed tokens", lambda s: _fmt(float(s["13_recomputed_prompt_tokens"]["total"]), 0)),
            ("Resumption latency mean (ms)", lambda s: _s(s["8_session_resumption_latency_ms"], "mean", 0)),
            ("Prefix-loss events", lambda s: str(s["15_cache_eviction_and_slot_reset_events"]["prefix_loss_events"])),
        ]
        for label, fn in rows:
            out += f"| {label} | " + " | ".join(fn(summaries[c]["by_workload"][w]) for c in configs) + " |\n"
    return out


def paired_table(rows, configs, baseline, kind):
    metrics = [("mean_ttft_ms", "ratio"), ("sum_prefill_ms", "ratio"), ("recomputed_tokens", "ratio"),
               ("mean_queue_ms", "ratio")]
    if kind == "e2e":
        metrics = [("agent_latency_s", "ratio"), ("task_success", "diff")] + metrics
    else:
        metrics = [("session_latency_s", "ratio")] + metrics
    out = f"Paired by episode ID against **{LABELS[baseline]}**; 95% bootstrap CI over episodes (10,000 resamples).\n\n"
    out += "| Config | Metric | n | candidate mean | baseline mean | difference | 95% CI |\n|---|---|---|---|---|---|---|\n"
    result = {}
    for c in configs:
        if c == baseline:
            continue
        cmp = compare(rows[c], rows[baseline], metrics)
        result[c] = cmp
        for key, kind_ in metrics:
            r = cmp.get(key)
            if not r:
                continue
            if kind_ == "ratio":
                diff = f"{r['pct_diff']:+.1f}%"
                ci = f"[{r['ci95_pct'][0]:+.1f}%, {r['ci95_pct'][1]:+.1f}%]"
            else:
                diff = f"{r['diff'] * 100:+.1f} pp"
                ci = f"[{r['ci95'][0] * 100:+.1f}, {r['ci95'][1] * 100:+.1f}] pp"
            star = " *" if r["significant"] else ""
            out += (f"| {LABELS[c]} | {key} | {r['n']} | {_fmt(r['mean_candidate'], 2)} | {_fmt(r['mean_baseline'], 2)} "
                    f"| {diff}{star} | {ci} |\n")
    out += "\n`*` = 95% CI excludes zero.\n"
    return out, result


def charts(summaries, rows, configs, kind, assets, tag):
    assets.mkdir(parents=True, exist_ok=True)
    files = []
    lat_key = "agent_latency_s" if kind == "e2e" else "session_latency_s"
    # 1. per-workload grouped bars for key metrics
    specs = [("mean_ttft_ms", "Mean TTFT per episode (ms)"), ("recomputed_tokens", "Recomputed prompt tokens per episode"),
             (lat_key, "End-to-end latency (s)"), ("mean_queue_ms", "Mean queue wait per request (ms)")]
    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    for ax, (key, title) in zip(axes.flat, specs):
        width = 0.8 / len(configs)
        for i, c in enumerate(configs):
            vals = []
            for w in WORKLOADS:
                v = [r[key] for r in rows[c] if r["workload"] == w and r.get(key) is not None]
                vals.append(np.mean(v) if v else 0)
            ax.bar(np.arange(len(WORKLOADS)) + i * width, vals, width, label=LABELS[c], color=COLORS[c])
        ax.set_xticks(np.arange(len(WORKLOADS)) + width * (len(configs) - 1) / 2)
        ax.set_xticklabels(WORKLOADS, rotation=15, fontsize=8)
        ax.set_title(title, fontsize=10)
    axes[0, 0].legend(fontsize=8)
    fig.suptitle(f"{tag}: per-workload means ({kind})")
    fig.tight_layout()
    p = assets / f"{kind}_workload_bars.png"
    fig.savefig(p, dpi=120)
    plt.close(fig)
    files.append(p)
    # 2. CDFs of E2E latency and TTFT
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    for c in configs:
        for ax, key in zip(axes, (lat_key, "mean_ttft_ms")):
            v = np.sort([r[key] for r in rows[c] if r.get(key) is not None])
            if len(v):
                ax.plot(v, np.arange(1, len(v) + 1) / len(v), label=LABELS[c], color=COLORS[c])
    axes[0].set_xlabel(f"{lat_key}")
    axes[1].set_xlabel("mean TTFT per episode (ms)")
    for ax in axes:
        ax.set_ylabel("CDF")
        ax.grid(alpha=0.3)
    axes[0].legend(fontsize=8)
    fig.tight_layout()
    p = assets / f"{kind}_latency_cdf.png"
    fig.savefig(p, dpi=120)
    plt.close(fig)
    files.append(p)
    # 3. cache behaviour
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    for i, c in enumerate(configs):
        s = summaries[c]
        hit = [((s["by_workload"].get(w, {}).get("11_eligible_cache_hit_rate") or {}).get("value") or 0) for w in WORKLOADS]
        reuse = [((s["by_workload"].get(w, {}).get("12_prefix_cache_reuse_ratio") or {}).get("value") or 0) for w in WORKLOADS]
        width = 0.8 / len(configs)
        axes[0].bar(np.arange(len(WORKLOADS)) + i * width, hit, width, label=LABELS[c], color=COLORS[c])
        axes[1].bar(np.arange(len(WORKLOADS)) + i * width, reuse, width, label=LABELS[c], color=COLORS[c])
    for ax, t in zip(axes, ("Eligible-request cache-hit rate", "Prefix-cache reuse ratio")):
        ax.set_xticks(np.arange(len(WORKLOADS)) + 0.4 - 0.4 / len(configs))
        ax.set_xticklabels(WORKLOADS, rotation=15, fontsize=8)
        ax.set_ylim(0, 1)
        ax.set_title(t, fontsize=10)
    axes[0].legend(fontsize=8)
    fig.tight_layout()
    p = assets / f"{kind}_cache.png"
    fig.savefig(p, dpi=120)
    plt.close(fig)
    files.append(p)
    # 4. slot utilisation
    fig, ax = plt.subplots(figsize=(7, 3.5))
    for i, c in enumerate(configs):
        u = summaries[c]["17_slot_and_kv_utilization"].get("slot_utilization") or {}
        keys = sorted(u, key=lambda k: int(k))
        ax.bar(np.arange(len(keys)) + i * 0.8 / len(configs), [u[k] for k in keys], 0.8 / len(configs),
               label=LABELS[c], color=COLORS[c])
    ax.set_xlabel("slot")
    ax.set_ylabel("busy fraction")
    ax.legend(fontsize=8)
    fig.tight_layout()
    p = assets / f"{kind}_slot_utilization.png"
    fig.savefig(p, dpi=120)
    plt.close(fig)
    files.append(p)
    return files


def write_csv(rows, path):
    if not rows:
        return
    keys = list(rows[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def build(configs, name, kinds=("e2e", "replay"), baseline="native_cache", replay_subdir="replay", tiers=None):
    out_md = f"# Generated tables: {name}\n\n" + (f"Tiers included: {', '.join(tiers)}\n\n" if tiers else "")
    all_metrics = {}
    assets = ROOT / "reports" / "assets" / name
    for kind in kinds:
        summaries, rows = {}, {}
        for c in configs:
            base = results_dir(c)
            if kind == "e2e":
                if not (base / "e2e").exists():
                    continue
                summaries[c] = analyze_e2e(base, tiers)
                rows[c] = per_episode_table(base, "e2e", tiers)
            else:
                if not (base / replay_subdir).exists():
                    continue
                summaries[c] = analyze_replay(base, replay_subdir, tiers)
                rows[c] = per_episode_table(base, replay_subdir, tiers)
            if not rows[c]:
                summaries.pop(c)
                rows.pop(c)
                continue
            target = base / (kind if kind == "e2e" else replay_subdir)
            suffix = f"_{name}"
            (target / f"summary{suffix}.json").write_text(json.dumps(summaries[c], indent=1, default=str))
            write_csv(rows[c], target / f"per_episode{suffix}.csv")
        present = [c for c in configs if c in summaries]
        if not present:
            continue
        # restrict paired analysis to the common episode set
        common = set.intersection(*[{r["episode_id"] for r in rows[c]} for c in present])
        title = "End-to-end agent benchmark" if kind == "e2e" else "Controlled trace replay"
        out_md += f"## {title}\n\nEpisodes per config: " + ", ".join(
            f"{LABELS[c]}={summaries[c]['episodes']}" for c in present) + f"; common episode set = {len(common)}\n\n"
        out_md += table(summaries, kind, present) + "\n"
        out_md += "### Per-workload breakdown\n" + workload_table(summaries, kind, present) + "\n"
        if baseline in present and len(present) > 1:
            pt, pres = paired_table({c: [r for r in rows[c] if r["episode_id"] in common] for c in present},
                                    present, baseline, kind)
            out_md += "### Paired comparison\n\n" + pt + "\n"
            all_metrics[f"{kind}_paired"] = pres
        files = charts(summaries, rows, present, kind, assets, name)
        out_md += "\n".join(f"![{f.stem}](../assets/{name}/{f.name})" for f in files) + "\n\n"
        all_metrics[kind] = summaries
    gen = ROOT / "reports" / "generated"
    gen.mkdir(parents=True, exist_ok=True)
    (gen / f"{name}_tables.md").write_text(out_md)
    (gen / f"{name}_metrics.json").write_text(json.dumps(all_metrics, indent=1, default=str))
    print(f"wrote reports/generated/{name}_tables.md")
    return all_metrics


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--kinds", default="e2e,replay")
    ap.add_argument("--replay-subdir", default="replay")
    ap.add_argument("--tiers", default=None, help="comma list of tier dir names, e.g. tier0 or tier0,tier1")
    args = ap.parse_args()
    build(args.configs.split(","), args.name, tuple(args.kinds.split(",")), replay_subdir=args.replay_subdir,
          tiers=args.tiers.split(",") if args.tiers else None)


if __name__ == "__main__":
    main()
