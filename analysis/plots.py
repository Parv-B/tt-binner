"""Figure generation for the BINNER analysis report.

Every function takes the ``analyze()`` result dict ``R`` and a figures directory,
saves a small PNG, and returns its filename (relative to the figures directory)
or ``None`` if there is not enough data to draw it. Kept separate from
``binner_analysis.py`` so the estimator library has no plotting dependency beyond
what's already required (matplotlib is only imported here and in the report/CLI).
"""
from __future__ import annotations

import math
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import stats

import binner_analysis as ba

DPI = 110
plt.rcParams.update({"font.size": 8, "figure.dpi": DPI, "axes.grid": True,
                     "grid.alpha": 0.3, "savefig.bbox": "tight"})


def _save(fig, out_dir, name):
    path = os.path.join(out_dir, name)
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    return name


def _ci_err(vals, cis):
    """Convert [lo, hi] pairs to matplotlib yerr (2, N) around ``vals``."""
    lo = np.array([c[0] if c is not None and np.isfinite(c[0]) else v for c, v in zip(cis, vals)])
    hi = np.array([c[1] if c is not None and np.isfinite(c[1]) else v for c, v in zip(cis, vals)])
    return np.abs(np.vstack([np.array(vals) - lo, hi - np.array(vals)]))


# ----------------------------------------------------------------------------------
def plot_die_to_die(R, out_dir, key="f_inv_mean_25C", label="INV ring mean (25 C corrected)"):
    pcm = R["per_chip"]
    if key not in pcm or pcm[key].notna().sum() < 3:
        return None
    v = pcm[key].dropna().values / 1e6
    n = len(v)
    fig, ax = plt.subplots(1, 3, figsize=(9, 2.8))
    ax[0].hist(v, bins=min(max(int(math.sqrt(n)) + 2, 4), 12), color="#3b6fa0", edgecolor="white")
    ax[0].set_xlabel("MHz"); ax[0].set_ylabel("# dies"); ax[0].set_title(f"{label} histogram (N={n})")
    vs = np.sort(v)
    cdf = (np.arange(n) + 0.5) / n
    ax[1].step(vs, cdf, where="post", color="#3b6fa0")
    ax[1].set_xlabel("MHz"); ax[1].set_ylabel("empirical CDF"); ax[1].set_title("CDF")
    (osm, osr), (slope, intercept, r) = stats.probplot(v, dist="norm")
    ax[2].scatter(osm, osr, s=14, color="#3b6fa0")
    ax[2].plot(osm, slope * osm + intercept, color="#c0504d", lw=1)
    ax[2].set_xlabel("normal quantile"); ax[2].set_ylabel("MHz")
    ax[2].set_title(f"normal prob. plot (r={r:.3f})")
    fig.suptitle(f"Die-to-die distribution: {label}", y=1.05)
    fig.tight_layout()
    return _save(fig, out_dir, f"d2d_{key}.png")


def plot_np_skew(R, out_dir):
    npk = R.get("np", {})
    if not npk.get("ok"):
        return None
    t = npk["per_chip"]
    if len(t) < 1:
        return None
    fig, ax = plt.subplots(figsize=(4.6, 4.2))
    for c, r in t.iterrows():
        ax.errorbar(r["s_n"], r["s_p"], xerr=ba.Z90 * r["se_s_n"], yerr=ba.Z90 * r["se_s_p"],
                    fmt="o", ms=4, color="#3b6fa0", ecolor="#3b6fa0", alpha=0.4, capsize=2)
        cov = np.array([[r["se_s_n"] ** 2, r["cov_np"]], [r["cov_np"], r["se_s_p"] ** 2]])
        _ellipse(ax, (r["s_n"], r["s_p"]), cov, 4.605, color="#3b6fa0", alpha=0.15)  # 90% chi2(2)
    lim = max(0.02, np.nanmax(np.abs(t[["s_n", "s_p"]].values)) * 1.3)
    ax.plot([-lim, lim], [-lim, lim], "--", color="gray", lw=0.8, label="s_n = s_p (no skew)")
    ax.axhline(0, color="gray", lw=0.5); ax.axvline(0, color="gray", lw=0.5)
    ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim)
    ax.set_xlabel("s_n (relative NMOS drive shift)")
    ax.set_ylabel("s_p (relative PMOS drive shift)")
    ax.set_title(f"N/P corner per die (90% ellipse), N={len(t)}")
    ax.legend(fontsize=7, loc="upper left")
    ax.set_aspect("equal")
    fig.tight_layout()
    return _save(fig, out_dir, "np_skew.png")


def _ellipse(ax, center, cov, chi2_val, **kw):
    if not np.all(np.isfinite(cov)) or np.linalg.det(cov) <= 0:
        return
    vals, vecs = np.linalg.eigh(cov)
    vals = np.clip(vals, 0, None)
    theta = np.linspace(0, 2 * np.pi, 60)
    circle = np.vstack([np.cos(theta), np.sin(theta)]) * np.sqrt(vals * chi2_val)[:, None]
    pts = vecs @ circle
    ax.fill(center[0] + pts[0], center[1] + pts[1], **kw)


def plot_fmax_regression(R, out_dir):
    ch = R.get("chain", {})
    fits = ch.get("fits", {})
    if not fits:
        return None
    fig, ax = plt.subplots(1, 2, figsize=(8, 3.2))
    any_fmax, any_dch = False, False
    cmap = plt.get_cmap("tab20")
    for i, (c, fd) in enumerate(fits.items()):
        col = cmap(i % 20)
        if "fmax" in fd:
            n_, L, U, bc = fd["fmax"]
            mid = np.where(np.isfinite(U), (L + U) / 2 * 1e9, np.nan)
            err = np.where(np.isfinite(U), (U - L) / 2 * 1e9, 0)
            ax[0].errorbar(n_, mid, yerr=err, fmt="o", ms=3, color=col, ecolor=col, alpha=0.6, capsize=2)
            nn = np.linspace(n_.min(), n_.max(), 20)
            ax[0].plot(nn, (bc[0] + bc[1] * nn) * 1e9, "-", color=col, lw=0.7, alpha=0.7)
            any_fmax = True
        if "dch" in fd:
            n_, hp = fd["dch"]
            ax[1].scatter(n_, hp * 1e9, s=10, color=col, alpha=0.6)
            any_dch = True
    ax[0].set_xlabel("tap stage count n_k"); ax[0].set_ylabel("1/Fmax_k (ns)")
    ax[0].set_title("Fmax-vs-tap censored fit (per die)")
    ax[1].set_xlabel("tap stage count n_k"); ax[1].set_ylabel("DCH ring half-period (ns)")
    ax[1].set_title("DCH ring cross-check")
    if not (any_fmax or any_dch):
        plt.close(fig)
        return None
    fig.tight_layout()
    return _save(fig, out_dir, "fmax_tap_regression.png")


def plot_gradient(R, out_dir):
    wd = R.get("within_die", {})
    if not wd.get("ok") or len(wd["per_chip"]) < 1:
        return None
    ct = wd["per_chip"]
    fig, ax = plt.subplots(figsize=(4.4, 4.2))
    ax.quiver(np.zeros(len(ct)), np.zeros(len(ct)), ct["g_x"], ct["g_y"],
             angles="xy", scale_units="xy", scale=1, color="#3b6fa0", alpha=0.5, width=0.004)
    gt = wd.get("gradient_test", {})
    if gt.get("n", 0) >= 3:
        ax.quiver([0], [0], [gt["mean_gx"]], [gt["mean_gy"]], angles="xy", scale_units="xy",
                 scale=1, color="#c0504d", width=0.01, label="population mean")
        ax.legend(fontsize=7)
    lim = max(0.01, np.nanmax(np.abs(ct[["g_x", "g_y"]].values)) * 1.2)
    ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim)
    ax.axhline(0, color="gray", lw=0.5); ax.axvline(0, color="gray", lw=0.5)
    ax.set_xlabel("g_x (delay-factor gradient, per unit x)")
    ax.set_ylabel("g_y (delay-factor gradient, per unit y)")
    ax.set_title(f"Per-die systematic gradient vectors, N={len(ct)}")
    ax.set_aspect("equal")
    fig.tight_layout()
    return _save(fig, out_dir, "gradient_vectors.png")


def plot_bins(R, out_dir, key="bins_ring", title="Speed bin yield (INV ring, 25 C)"):
    b = R.get(key)
    if not b:
        return None
    y = b["yield"]
    order = [n for n, _ in b["limits"]] + [b.get("reject") or "REJECT-SLOW", "FUNCTIONAL-FAIL", "NO-DATA"]
    order = [o for o in order if o in y.index]
    y = y.loc[order]
    fig, ax = plt.subplots(figsize=(5.2, 3))
    x = np.arange(len(y))
    w = 0.35
    raw = y["bin_raw_yield"].values
    gb = y["bin_gb_yield"].values
    err_raw = _ci_err(raw, y["bin_raw_ci"].values)
    err_gb = _ci_err(gb, y["bin_gb_ci"].values)
    ax.bar(x - w / 2, raw, w, yerr=err_raw, capsize=2, label="no guard band", color="#9dc3e6")
    ax.bar(x + w / 2, gb, w, yerr=err_gb, capsize=2, label="with guard band", color="#3b6fa0")
    ax.set_xticks(x); ax.set_xticklabels(y.index, rotation=25, ha="right")
    ax.set_ylabel("yield (fraction of dies)")
    ax.set_title(title + f" (90% Clopper-Pearson CI)")
    ax.legend(fontsize=7)
    fig.tight_layout()
    return _save(fig, out_dir, f"{key}.png")


def plot_puf(R, out_dir):
    p = R.get("puf", {})
    if not p.get("ok"):
        return None
    fig, ax = plt.subplots(1, 2, figsize=(8, 3))
    alias = np.array(p["bit_aliasing"])
    ax[0].bar(np.arange(len(alias)), alias, color="#3b6fa0")
    ax[0].axhline(0.5, color="#c0504d", lw=1, ls="--", label="ideal 0.5")
    ax[0].set_xlabel("PUF bit index"); ax[0].set_ylabel("P(bit=1) across dies")
    ax[0].set_title(f"Bit aliasing (N={p['n_chips']} dies)")
    ax[0].legend(fontsize=7)
    hds = p.get("inter_hd_hist", [])
    if hds:
        ax[1].hist(hds, bins=min(max(len(hds) // 3, 4), 15), color="#3b6fa0", edgecolor="white")
        ax[1].axvline(0.5, color="#c0504d", lw=1, ls="--", label="expected 0.5")
        ax[1].set_xlabel("inter-chip Hamming distance (fraction of 16 bits)")
        ax[1].set_ylabel("# chip pairs")
        ax[1].set_title(f"Inter-chip HD ({p['inter_hd_pairs']} pairs)")
        ax[1].legend(fontsize=7)
    fig.tight_layout()
    return _save(fig, out_dir, "puf.png")


def plot_predictions(R, out_dir):
    pc = R.get("pred_cmp")
    if pc is None or not len(pc):
        return None
    pc = pc.sort_index()
    fig, ax = plt.subplots(figsize=(max(6, 0.22 * len(pc)), 3.4))
    x = np.arange(len(pc))
    ratios = pc["ratio_median"].values
    err = _ci_err(ratios, pc["ratio_ci"].values)
    ax.errorbar(x, ratios, yerr=err, fmt="o", ms=4, color="#3b6fa0", ecolor="#3b6fa0", capsize=2,
               label="measured / predicted (tt), 90% CI")
    lo = pc["band_lo_rel"].values
    hi = pc["band_hi_rel"].values
    ax.fill_between(x, lo, hi, step="mid", color="#c0504d", alpha=0.15, label="predicted ss..ff band")
    ax.axhline(1.0, color="gray", lw=0.8)
    ax.set_xticks(x); ax.set_xticklabels(pc.index, rotation=60, ha="right", fontsize=6)
    ax.set_ylabel("measured / predicted(tt)")
    ax.set_title("Predicted vs measured (25 C corrected)")
    ax.legend(fontsize=7)
    fig.tight_layout()
    return _save(fig, out_dir, "predicted_vs_measured.png")


def make_all(R, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    figs = {}
    figs["d2d_inv"] = plot_die_to_die(R, out_dir, "f_inv_mean_25C", "INV ring mean freq")
    figs["d2d_tstage"] = plot_die_to_die(R, out_dir, "t_stage", "chain stage delay t_stage")
    figs["np_skew"] = plot_np_skew(R, out_dir)
    figs["fmax_regression"] = plot_fmax_regression(R, out_dir)
    figs["gradient"] = plot_gradient(R, out_dir)
    figs["bins_ring"] = plot_bins(R, out_dir, "bins_ring", "Speed bin yield (INV ring, 25 C)")
    figs["bins_fmax"] = plot_bins(R, out_dir, "bins_fmax", f"Speed bin yield (Fmax {R.get('bins_fmax', {}).get('tap', '')})")
    figs["puf"] = plot_puf(R, out_dir)
    figs["predictions"] = plot_predictions(R, out_dir)
    return {k: v for k, v in figs.items() if v}
