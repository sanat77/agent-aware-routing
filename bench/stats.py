"""Paired comparisons and bootstrap confidence intervals (episodes are the resampling unit)."""
import numpy as np

N_BOOT = 10000
SEED = 7


def paired(rows_a, rows_b, key):
    """Return aligned arrays (a, b) for episodes present in both with non-null values."""
    b_by = {r["episode_id"]: r for r in rows_b}
    a_vals, b_vals, ids = [], [], []
    for r in rows_a:
        o = b_by.get(r["episode_id"])
        if o is None or r.get(key) is None or o.get(key) is None:
            continue
        a_vals.append(float(r[key]))
        b_vals.append(float(o[key]))
        ids.append(r["episode_id"])
    return np.array(a_vals), np.array(b_vals), ids


def bootstrap_ratio(a, b, n_boot=N_BOOT, seed=SEED):
    """Percentage difference of means (a vs baseline b) with a 95% paired-bootstrap CI."""
    if len(a) == 0 or b.sum() == 0:
        return None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(a), size=(n_boot, len(a)))
    am = a[idx].mean(axis=1)
    bm = b[idx].mean(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratios = am / bm - 1.0
    ratios = ratios[np.isfinite(ratios)]
    point = a.mean() / b.mean() - 1.0
    lo, hi = np.percentile(ratios, [2.5, 97.5])
    return {"n": int(len(a)), "mean_candidate": float(a.mean()), "mean_baseline": float(b.mean()),
            "pct_diff": float(point * 100), "ci95_pct": [float(lo * 100), float(hi * 100)],
            "significant": bool(lo > 0 or hi < 0)}


def bootstrap_diff(a, b, n_boot=N_BOOT, seed=SEED):
    """Absolute paired mean difference (a - b) with 95% CI; used for rates such as task success."""
    if len(a) == 0:
        return None
    rng = np.random.default_rng(seed)
    d = a - b
    idx = rng.integers(0, len(d), size=(n_boot, len(d)))
    means = d[idx].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {"n": int(len(d)), "mean_candidate": float(a.mean()), "mean_baseline": float(b.mean()),
            "diff": float(d.mean()), "ci95": [float(lo), float(hi)], "significant": bool(lo > 0 or hi < 0)}


def compare(rows_cand, rows_base, metrics):
    """metrics: list of (key, 'ratio'|'diff')."""
    out = {}
    for key, kind in metrics:
        a, b, _ = paired(rows_cand, rows_base, key)
        out[key] = bootstrap_ratio(a, b) if kind == "ratio" else bootstrap_diff(a, b)
    return out
