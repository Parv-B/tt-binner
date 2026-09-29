#!/usr/bin/env python3
"""BINNER bring-up population analysis -- CLI.

    python analysis/run_analysis.py <csv_dir> --out <report_dir> \
        [--truth <truth_dir>] [--placement docs/reports/<sha>/placement.csv] \
        [--predictions <sdf_predictions.json>] [--model <model_overrides.json>] \
        [--B 1000] [--seed 0] [--fmax-bin-tap T7]

Writes to ``<report_dir>``:
    report.md            human-readable Markdown report (product/yield-engineer style)
    figures/*.png         small PNGs referenced by the report
    results.json          every estimate, machine-readable (see binner_analysis.to_jsonable)
    tables/*.csv           the same tables as flat CSVs, for spreadsheets / dashboards
    validation.json/.csv   present only when --truth is given

All statistics live in binner_analysis.py; this file only orchestrates ingestion,
figure generation (plots.py), report assembly (report.py) and file output, and
degrades gracefully (missing chips, missing placement, missing predictions, missing
truth are all optional).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import binner_analysis as ba
import plots
import report as report_mod


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv_dir", help="directory of binner_<chip_id>.csv files")
    ap.add_argument("--out", required=True, help="output report directory")
    ap.add_argument("--truth", help="directory with truth_<chip>.json / population_truth.json "
                                    "(validation mode; synthetic populations only)")
    ap.add_argument("--placement", help="placement CSV (item,x_norm,y_norm) from tools/place_extract.py; "
                                        "falls back to a documented placeholder grid if omitted")
    ap.add_argument("--predictions", help="SDF/SPICE-derived predictions JSON "
                                          "({item: {tt,ss,ff,lo,hi} Hz}); optional")
    ap.add_argument("--model", help="JSON of model overrides (deep-merged over binner_analysis.DEFAULT_MODEL, "
                                    "e.g. SDF-derived w_n/w_p sensitivities)")
    ap.add_argument("--bins", help="JSON of speed-bin definitions overriding binner_analysis.DEFAULT_BINS")
    ap.add_argument("--B", type=int, default=1000, help="bootstrap resamples (default 1000)")
    ap.add_argument("--seed", type=int, default=0, help="RNG seed for bootstrap reproducibility")
    ap.add_argument("--fmax-bin-tap", default="T7", help="which Fmax tap to speed-bin on (default T7)")
    a = ap.parse_args(argv)

    os.makedirs(a.out, exist_ok=True)
    fig_dir = os.path.join(a.out, "figures")
    tab_dir = os.path.join(a.out, "tables")
    os.makedirs(fig_dir, exist_ok=True)
    os.makedirs(tab_dir, exist_ok=True)

    bins = None
    if a.bins:
        with open(a.bins, encoding="utf-8") as fh:
            bins = json.load(fh)

    try:
        R = ba.analyze(a.csv_dir, placement_path=a.placement, model_path=a.model,
                       predictions_path=a.predictions, bins=bins, B=a.B, seed=a.seed,
                       fmax_bin_tap=a.fmax_bin_tap)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except Exception:
        print("error: analysis pipeline raised an unhandled exception:", file=sys.stderr)
        traceback.print_exc()
        return 1

    validation = None
    if a.truth:
        try:
            validation = ba.validate_against_truth(R, a.truth)
        except Exception:
            print("warning: --truth given but validation failed:", file=sys.stderr)
            traceback.print_exc()

    try:
        figs = plots.make_all(R, fig_dir)
    except Exception:
        print("warning: figure generation raised an exception; continuing with a text-only report:",
              file=sys.stderr)
        traceback.print_exc()
        figs = {}

    md = report_mod.build_report(R, figs, a.csv_dir, validation)
    with open(os.path.join(a.out, "report.md"), "w", encoding="utf-8") as fh:
        fh.write(md)

    payload = ba.to_jsonable(R)
    payload["issues"] = R["pop"].issues
    payload["chips"] = R["pop"].chips
    with open(os.path.join(a.out, "results.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1)

    _write_tables(R, tab_dir)

    if validation is not None:
        with open(os.path.join(a.out, "validation.json"), "w", encoding="utf-8") as fh:
            json.dump(ba.to_jsonable(validation), fh, indent=1)
        validation["population"].to_csv(os.path.join(a.out, "validation_population.csv"))
        validation["per_chip"].to_csv(os.path.join(a.out, "validation_per_chip.csv"))
        if len(validation["summary"]):
            validation["summary"].to_csv(os.path.join(a.out, "validation_summary.csv"), index=False)
        npass = sum(1 for v in validation["verdict"].values() if v)
        ntot = len(validation["verdict"])
        print(f"validation: {npass}/{ntot} checks PASS against docs/VARIATION_MODEL.md targets")

    print(f"wrote report to {os.path.join(a.out, 'report.md')}")
    print(f"  {len(figs)} figure(s), results.json, {len(os.listdir(tab_dir))} table(s)")
    return 0


def _write_tables(R: dict, tab_dir: str):
    import pandas as pd

    def dump(name, obj):
        if obj is None:
            return
        if isinstance(obj, dict) and "per_chip" in obj and hasattr(obj["per_chip"], "to_csv"):
            obj["per_chip"].to_csv(os.path.join(tab_dir, f"{name}_per_chip.csv"))
            return
        if hasattr(obj, "to_csv"):
            obj.to_csv(os.path.join(tab_dir, f"{name}.csv"))

    dump("completeness", R.get("completeness"))
    dump("per_chip", R.get("per_chip"))
    dump("ring_summary", R.get("ring_summary"))
    dump("within_die", R.get("within_die"))
    dump("np_skew", R.get("np"))
    dump("chain", R.get("chain"))
    dump("pred_cmp", R.get("pred_cmp"))
    for key in ("bins_ring", "bins_fmax"):
        b = R.get(key)
        if b:
            b["yield"].to_csv(os.path.join(tab_dir, f"{key}_yield.csv"))
            b["per_chip"].to_csv(os.path.join(tab_dir, f"{key}_per_chip.csv"))
    d2d_rows = []
    for col, d in R.get("d2d", {}).items():
        if "sd" in d:
            d2d_rows.append({"quantity": col, "label": d["label"], **{k: v for k, v in d.items() if not isinstance(v, list) or len(v) != 2 or k.startswith("shapiro")}})
    if d2d_rows:
        pd.DataFrame(d2d_rows).to_csv(os.path.join(tab_dir, "d2d_summary.csv"), index=False)
    p = R.get("puf", {})
    if p.get("ok"):
        pd.DataFrame({"bit": range(len(p["bit_aliasing"])), "aliasing": p["bit_aliasing"]}).to_csv(
            os.path.join(tab_dir, "puf_bit_aliasing.csv"), index=False)
        pd.DataFrame({"chip": p["chips"], "uniformity": [p["uniformity"][c] for c in p["chips"]],
                     "intra_ber": [p["intra_ber"][c] for c in p["chips"]]}).to_csv(
            os.path.join(tab_dir, "puf_per_chip.csv"), index=False)
    if R.get("pop") is not None:
        pd.DataFrame(R["pop"].issues).to_csv(os.path.join(tab_dir, "ingestion_issues.csv"), index=False)


if __name__ == "__main__":
    raise SystemExit(main())
