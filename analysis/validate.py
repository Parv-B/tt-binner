#!/usr/bin/env python3
"""Monte-Carlo characterization of the BINNER estimators.

Draws many independent synthetic populations at N=20 and N=8 (the two headline
sizes in docs/VARIATION_MODEL.md), runs the full ``binner_analysis`` pipeline on
each, and compares every recovered parameter with the known injected truth
(``binner_analysis.validate_against_truth``). This is what actually tells us
whether an estimator is unbiased and whether its stated confidence interval has
the coverage it claims -- a single population (however large) cannot answer
either question, because you don't know if you got a lucky or unlucky draw.

Usage:
    python analysis/validate.py --seeds 20 --out analysis
    python analysis/validate.py --seeds 20 --ns 20 8 --B 400 --out analysis

Writes ``<out>/VALIDATION.md`` plus PNGs in ``<out>/validation_figures/``. Also
writes ``<out>/validation_mc_population.csv`` and
``<out>/validation_mc_per_chip.csv`` (every per-seed row, for further analysis).

If a docs/VARIATION_MODEL.md target bound turns out not to be achievable even at
N=20 with an honest estimator, this script does NOT edit that doc -- it reports
the achieved bound plainly in VALIDATION.md's "target reality check" section and
in this run's stdout, so a human decides whether to relax the target or improve
the estimator.
"""
from __future__ import annotations

import argparse
import math
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import binner_analysis as ba
import synth_population as sp

plt.rcParams.update({"font.size": 8, "figure.dpi": 110, "axes.grid": True,
                     "grid.alpha": 0.3, "savefig.bbox": "tight"})

# Stated docs/VARIATION_MODEL.md targets, N=20. Reused from binner_analysis.TARGETS
# (single source of truth) rather than redefined here.
TARGETS = ba.TARGETS


def run_one(n: int, seed: int, B: int, tmp_root: str, stage5: bool, faults: bool) -> dict | None:
    """Generate one synthetic population, run the pipeline, validate against truth.

    Returns the ``validate_against_truth`` dict plus ``n``/``seed``, or None on
    an unhandled failure (recorded by the caller, not silently dropped).
    """
    d = os.path.join(tmp_root, f"n{n}_s{seed}")
    pl, ph = sp.load_placement(None)
    cfg = sp.SynthConfig(n=n, seed=seed, placement=pl, placement_is_placeholder=ph,
                         stage5=stage5, faults=faults and n >= 14)
    sp.generate(cfg, d, write_truth=True)
    R = ba.analyze(d, B=B, seed=seed)
    v = ba.validate_against_truth(R, d)
    v["n"], v["seed"] = n, seed
    shutil.rmtree(d, ignore_errors=True)
    return v


def collect(ns: list[int], n_seeds: int, B: int, seed0: int, stage5: bool, faults: bool,
           verbose: bool = True) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    pop_rows, chip_rows, failures = [], [], []
    with tempfile.TemporaryDirectory(prefix="binner_mc_") as tmp:
        for n in ns:
            for i in range(n_seeds):
                seed = seed0 + i
                t0 = time.time()
                try:
                    v = run_one(n, seed, B, tmp, stage5, faults)
                except Exception as e:  # a failed draw is itself a finding, not swallowed
                    failures.append({"n": n, "seed": seed, "error": repr(e)})
                    if verbose:
                        print(f"  N={n} seed={seed}: FAILED ({e!r})", file=sys.stderr)
                    continue
                pp = v["population"].copy(); pp["n"], pp["seed"] = n, seed
                pc = v["per_chip"].copy(); pc["n"], pc["seed"] = n, seed
                pop_rows.append(pp)
                chip_rows.append(pc)
                if verbose:
                    print(f"  N={n} seed={seed}: {time.time() - t0:.1f}s")
    pop = pd.concat(pop_rows, ignore_index=True) if pop_rows else pd.DataFrame()
    chip = pd.concat(chip_rows, ignore_index=True) if chip_rows else pd.DataFrame()
    return pop, chip, failures


# ======================================================================================
def summarize_population(pop: pd.DataFrame) -> pd.DataFrame:
    """Per (parameter, n): bias, RMSE, relative RMSE, CI90 coverage, over MC seeds."""
    rows = []
    for (param, n), g in pop.groupby(["parameter", "n"]):
        g = g.dropna(subset=["estimate", "truth"])
        if not len(g):
            continue
        err = g["estimate"].values - g["truth"].values
        truth_nz = g["truth"].values
        with np.errstate(divide="ignore", invalid="ignore"):
            rel = np.where(truth_nz != 0, err / truth_nz, np.nan)
        cov = g["ci_covers"].dropna()
        rows.append({
            "parameter": param, "n": n, "n_seeds": len(g),
            "truth_typ": float(np.nanmedian(truth_nz)),
            "bias": float(np.mean(err)), "rmse": float(np.sqrt(np.mean(err ** 2))),
            "rel_rmse": float(np.sqrt(np.nanmean(rel ** 2))) if np.isfinite(rel).any() else np.nan,
            "ci90_coverage": float(cov.mean()) if len(cov) else np.nan,
            "n_ci_obs": len(cov),
        })
    return pd.DataFrame(rows)


def summarize_per_chip(chip: pd.DataFrame) -> pd.DataFrame:
    """Per (parameter, n): pooled over all (die, seed) -- bias, RMSE, CI90 coverage, target pass rate."""
    rows = []
    for (param, n), g in chip.groupby(["parameter", "n"]):
        g = g.dropna(subset=["estimate", "truth"])
        if not len(g):
            continue
        err = g["estimate"].values - g["truth"].values
        truth_nz = g["truth"].values
        with np.errstate(divide="ignore", invalid="ignore"):
            rel = np.where(truth_nz != 0, err / truth_nz, np.nan)
        cov = g["ci_covers"].dropna()
        pas = g["pass"].dropna()
        rows.append({
            "parameter": param, "n": n, "n_dies_total": len(g), "n_seeds": g["seed"].nunique(),
            "bias": float(np.mean(err)), "rmse": float(np.sqrt(np.mean(err ** 2))),
            "rel_rmse": float(np.sqrt(np.nanmean(rel ** 2))) if np.isfinite(rel).any() else np.nan,
            "ci90_coverage": float(cov.mean()) if len(cov) else np.nan,
            "target_pass_rate": float(pas.mean()) if len(pas) else np.nan,
        })
    return pd.DataFrame(rows)


def target_reality_check(pop_summary: pd.DataFrame, chip_summary: pd.DataFrame) -> list[dict]:
    """Compare the MC-measured achievable error at N=20 against docs/VARIATION_MODEL.md.

    Uses RMSE (not a single run's CI) as the honest achieved-error number, since
    RMSE over independent draws is exactly what "the estimator is within +/-X% of
    truth" means -- a single run's bootstrap CI answers a different question
    (how uncertain is THIS estimate), not "how close is this estimator to truth
    across repeated silicon lots."
    """
    checks = []
    mapping = [
        ("sigma_d2d implied by INV spread", pop_summary, "rel", TARGETS["sigma_d2d"][1], "sigma_d2d"),
        ("sigma_wid", pop_summary, "rel", TARGETS["sigma_wid"][1], "sigma_wid"),
        ("s_n-s_p", chip_summary, "abs", TARGETS["delta"][1], "s_n - s_p (per die)"),
        ("t_stage (Fmax cens.)", chip_summary, "rel", TARGETS["t_stage"][1], "t_stage (per die)"),
    ]
    for param, table, kind, bound, label in mapping:
        row20 = table[(table["parameter"] == param) & (table["n"] == 20)]
        if not len(row20):
            continue
        r = row20.iloc[0]
        achieved = r["rel_rmse"] if kind == "rel" else r["rmse"]
        target_str = f"+/-{bound * 100:.0f}%" if kind == "rel" else f"+/-{bound}"
        realistic = bool(achieved <= bound) if np.isfinite(achieved) else None
        checks.append({"parameter": label, "kind": kind, "target": target_str,
                       "achieved_rmse_at_N20": achieved, "target_bound": bound,
                       "realistic_at_N20": realistic})
    return checks


# ======================================================================================
def plot_bias_rmse(summary: pd.DataFrame, params: list[str], out_dir: str, name: str,
                   value_col: str = "rmse", ylabel: str = "RMSE") -> str | None:
    s = summary[summary["parameter"].isin(params)]
    if not len(s):
        return None
    ns = sorted(s["n"].unique())
    params = [p for p in params if p in s["parameter"].values]
    fig, ax = plt.subplots(figsize=(max(5, 0.9 * len(params)), 3.2))
    x = np.arange(len(params))
    w = 0.8 / max(len(ns), 1)
    for i, n in enumerate(ns):
        vals = [s[(s.parameter == p) & (s.n == n)][value_col].mean() for p in params]
        ax.bar(x + i * w - 0.4 + w / 2, vals, w, label=f"N={n}")
    ax.set_xticks(x); ax.set_xticklabels(params, rotation=30, ha="right", fontsize=7)
    ax.set_ylabel(ylabel)
    ax.set_title(f"{ylabel} by Monte-Carlo (independent synthetic populations)")
    ax.legend(fontsize=7)
    fig.tight_layout()
    path = os.path.join(out_dir, name)
    fig.savefig(path)
    plt.close(fig)
    return os.path.basename(path)


def plot_coverage(summary: pd.DataFrame, params: list[str], out_dir: str, name: str, nominal=0.90) -> str | None:
    s = summary[summary["parameter"].isin(params)]
    if not len(s):
        return None
    ns = sorted(s["n"].unique())
    params = [p for p in params if p in s["parameter"].values]
    fig, ax = plt.subplots(figsize=(max(5, 0.9 * len(params)), 3.2))
    x = np.arange(len(params))
    w = 0.8 / max(len(ns), 1)
    for i, n in enumerate(ns):
        vals = [s[(s.parameter == p) & (s.n == n)]["ci90_coverage"].mean() for p in params]
        ax.bar(x + i * w - 0.4 + w / 2, vals, w, label=f"N={n}")
    ax.axhline(nominal, color="#c0504d", lw=1, ls="--", label=f"nominal {nominal:.0%}")
    ax.set_xticks(x); ax.set_xticklabels(params, rotation=30, ha="right", fontsize=7)
    ax.set_ylabel("empirical CI90 coverage")
    ax.set_ylim(0, 1.05)
    ax.set_title("Bootstrap/analytic CI coverage vs nominal 90% (Monte-Carlo)")
    ax.legend(fontsize=7)
    fig.tight_layout()
    path = os.path.join(out_dir, name)
    fig.savefig(path)
    plt.close(fig)
    return os.path.basename(path)


def plot_sigma_d2d_dist(pop: pd.DataFrame, out_dir: str) -> str | None:
    s = pop[pop["parameter"] == "sigma_d2d implied by INV spread"]
    if not len(s):
        return None
    fig, ax = plt.subplots(figsize=(5, 3.2))
    for n, g in s.groupby("n"):
        ax.hist(g["estimate"], bins=max(int(math.sqrt(len(g))), 4), alpha=0.55, label=f"N={n} ({len(g)} seeds)")
    truth = s["truth"].iloc[0]
    ax.axvline(truth, color="#c0504d", lw=1.5, ls="--", label=f"truth = {truth:.4f}")
    ax.set_xlabel("sigma_d2d estimate"); ax.set_ylabel("# Monte-Carlo seeds")
    ax.set_title("Sampling distribution of sigma_d2d across independent populations")
    ax.legend(fontsize=7)
    fig.tight_layout()
    path = os.path.join(out_dir, "mc_sigma_d2d_dist.png")
    fig.savefig(path)
    plt.close(fig)
    return os.path.basename(path)


# ======================================================================================
def build_validation_md(pop: pd.DataFrame, chip: pd.DataFrame, pop_summary: pd.DataFrame,
                        chip_summary: pd.DataFrame, checks: list[dict], failures: list[dict],
                        figs: dict, ns: list[int], n_seeds: int, B: int) -> str:
    from report import df_to_md  # reuse the same markdown-table helper as the main report
    out = []
    out.append("# BINNER estimator validation (Monte-Carlo)\n")
    out.append(f"Method: {n_seeds} independent synthetic populations per size (`analysis/synth_population.py`, "
               f"distinct RNG seeds), N in {ns}, analysed with `analysis/binner_analysis.py` "
               f"(bootstrap B={B}), compared against injected truth with "
               "`binner_analysis.validate_against_truth`. A single population's bootstrap CI answers "
               "'how uncertain is this one estimate'; repeating the whole draw-and-estimate pipeline "
               "many times is what actually measures bias, RMSE and whether the stated CI has the "
               "coverage it claims.\n")
    if failures:
        out.append(f"\n**{len(failures)} run(s) raised an unhandled exception and were excluded** "
                   "(listed at the end of this document) -- this is itself a robustness finding, not hidden.\n")

    out.append("\n## Population-level parameters (bias / RMSE / CI coverage over seeds)\n")
    out.append(df_to_md(pop_summary.sort_values(["parameter", "n"]),
                        cols=["parameter", "n", "n_seeds", "truth_typ", "bias", "rmse", "rel_rmse",
                              "ci90_coverage", "n_ci_obs"],
                        rename={"truth_typ": "truth (typ.)", "rel_rmse": "rel. RMSE",
                                "ci90_coverage": "CI90 coverage", "n_ci_obs": "n (CI obs)"}))

    out.append("\n## Per-chip parameters (pooled over all dies x seeds)\n")
    out.append(df_to_md(chip_summary.sort_values(["parameter", "n"]),
                        cols=["parameter", "n", "n_dies_total", "n_seeds", "bias", "rmse", "rel_rmse",
                              "ci90_coverage", "target_pass_rate"],
                        rename={"n_dies_total": "n (dies x seeds)", "rel_rmse": "rel. RMSE",
                                "ci90_coverage": "CI90 coverage", "target_pass_rate": "target pass rate"}))

    if figs.get("rmse_pop"):
        out.append(f"\n![Population RMSE](validation_figures/{figs['rmse_pop']})\n")
    if figs.get("rmse_chip"):
        out.append(f"\n![Per-chip RMSE](validation_figures/{figs['rmse_chip']})\n")
    if figs.get("coverage_pop"):
        out.append(f"\n![Population CI coverage](validation_figures/{figs['coverage_pop']})\n")
    if figs.get("coverage_chip"):
        out.append(f"\n![Per-chip CI coverage](validation_figures/{figs['coverage_chip']})\n")
    if figs.get("sigma_d2d_dist"):
        out.append(f"\n![sigma_d2d sampling distribution](validation_figures/{figs['sigma_d2d_dist']})\n")

    out.append("\n## Target reality check (docs/VARIATION_MODEL.md, N=20)\n")
    out.append("This script does not edit docs/VARIATION_MODEL.md. Where the achieved RMSE at N=20 "
               "exceeds the stated target, that is flagged here (and in the calling agent's final "
               "report) for a human to decide whether to relax the target, improve the estimator, or "
               "add more structures/repeats.\n")
    cdf = pd.DataFrame(checks)
    if len(cdf):
        cdf = cdf.assign(status=cdf["realistic_at_N20"].map(
            lambda x: "OK (within target)" if x else ("MISSED" if x is False else "n/a")))
        out.append(df_to_md(cdf, cols=["parameter", "target", "achieved_rmse_at_N20", "target_bound", "status"],
                            rename={"achieved_rmse_at_N20": "achieved RMSE @N=20"}))
        missed = cdf[cdf["status"] == "MISSED"]
        if len(missed):
            out.append("\n**Targets not met at N=20 by this Monte-Carlo:**\n")
            for _, r in missed.iterrows():
                out.append(f"- `{r['parameter']}`: target {r['target']}, achieved RMSE "
                           f"{r['achieved_rmse_at_N20']:.4g} (bound {r['target_bound']:.4g}). "
                           "See docs/VARIATION_MODEL.md; this is reported, not silently patched.")
    else:
        out.append("_No comparable rows (all target-mapped parameters missing from this run)._\n")

    if failures:
        out.append("\n## Failed runs\n")
        out.append(df_to_md(pd.DataFrame(failures)))

    out.append("\n## Degradation N=20 -> N=8\n")
    if 20 in pop_summary["n"].values and 8 in pop_summary["n"].values:
        rows = []
        for p in pop_summary["parameter"].unique():
            r20 = pop_summary[(pop_summary.parameter == p) & (pop_summary.n == 20)]
            r8 = pop_summary[(pop_summary.parameter == p) & (pop_summary.n == 8)]
            if len(r20) and len(r8):
                rows.append({"parameter": p, "rmse_N20": r20["rmse"].iloc[0], "rmse_N8": r8["rmse"].iloc[0],
                            "ratio_N8_over_N20": r8["rmse"].iloc[0] / r20["rmse"].iloc[0]
                            if r20["rmse"].iloc[0] else np.nan,
                            "cov_N20": r20["ci90_coverage"].iloc[0], "cov_N8": r8["ci90_coverage"].iloc[0]})
        out.append(df_to_md(pd.DataFrame(rows)))
        out.append("\nsqrt(20/8) = 1.58x is the naive sampling-noise expectation for RMSE inflation "
                   "going from N=20 to N=8, if nothing else changed; ratios well above that point to "
                   "additional small-N effects (e.g. REML/plane-fit degrees of freedom, bootstrap CI "
                   "width blow-up, censored-fit robustness).\n")

    return "\n".join(out) + "\n"


# ======================================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ns", type=int, nargs="+", default=[20, 8])
    ap.add_argument("--seeds", type=int, default=20, help="number of independent seeds per N")
    ap.add_argument("--seed0", type=int, default=1000, help="first seed (avoids colliding with docs/demo seeds)")
    ap.add_argument("--B", type=int, default=400, help="bootstrap resamples per run (kept modest x many runs)")
    ap.add_argument("--out", default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--stage5", action="store_true", default=True)
    ap.add_argument("--faults", action="store_true", default=False, help="inject screening test cases (N>=14 only)")
    a = ap.parse_args(argv)

    fig_dir = os.path.join(a.out, "validation_figures")
    os.makedirs(fig_dir, exist_ok=True)

    t0 = time.time()
    print(f"Monte-Carlo: N in {a.ns}, {a.seeds} seed(s) each, B={a.B} bootstrap resamples/run ...")
    pop, chip, failures = collect(a.ns, a.seeds, a.B, a.seed0, a.stage5, a.faults)
    print(f"done in {time.time() - t0:.0f}s ({len(pop)} population rows, {len(chip)} per-chip rows, "
         f"{len(failures)} failed run(s))")

    pop_summary = summarize_population(pop)
    chip_summary = summarize_per_chip(chip)
    checks = target_reality_check(pop_summary, chip_summary)

    figs = {}
    pop_params = [p for p in ("sigma_d2d (N/P GLS, MoM)", "sigma_d2d implied by INV spread", "sigma_wid",
                              "rho(s_n, s_p)", "PUF uniformity (mean)", "PUF inter-chip HD")
                  if p in pop_summary["parameter"].values]
    chip_params = [p for p in ("s_n", "s_p", "s_n-s_p", "g_x", "g_y", "t_stage (Fmax cens.)",
                               "t_stage (DCH ring)", "t_ov") if p in chip_summary["parameter"].values]
    figs["rmse_pop"] = plot_bias_rmse(pop_summary, pop_params, fig_dir, "mc_rmse_population.png")
    figs["rmse_chip"] = plot_bias_rmse(chip_summary, chip_params, fig_dir, "mc_rmse_per_chip.png")
    figs["coverage_pop"] = plot_coverage(pop_summary, pop_params, fig_dir, "mc_coverage_population.png")
    figs["coverage_chip"] = plot_coverage(chip_summary, chip_params, fig_dir, "mc_coverage_per_chip.png")
    figs["sigma_d2d_dist"] = plot_sigma_d2d_dist(pop, fig_dir)
    figs = {k: v for k, v in figs.items() if v}

    md = build_validation_md(pop, chip, pop_summary, chip_summary, checks, failures, figs,
                             a.ns, a.seeds, a.B)
    with open(os.path.join(a.out, "VALIDATION.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    pop.to_csv(os.path.join(a.out, "validation_mc_population.csv"), index=False)
    chip.to_csv(os.path.join(a.out, "validation_mc_per_chip.csv"), index=False)

    print(f"wrote {os.path.join(a.out, 'VALIDATION.md')} ({len(figs)} figures)")
    missed = [c for c in checks if c["realistic_at_N20"] is False]
    if missed:
        print("TARGET REALITY CHECK -- not met at N=20:")
        for c in missed:
            print(f"  {c['parameter']}: target {c['target']}, achieved RMSE {c['achieved_rmse_at_N20']:.4g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
