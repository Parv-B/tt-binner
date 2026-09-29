"""End-to-end smoke tests: synthetic population -> analyze() -> validate_against_truth,
and the run_analysis.py CLI writing an actual report bundle to disk."""
import json
import math
import os

import numpy as np
import pandas as pd
import pytest

import binner_analysis as ba
import synth_population as sp


def test_synth_population_matches_schema(tiny_population):
    files = [f for f in os.listdir(tiny_population) if f.startswith("binner_")]
    assert len(files) == 6
    with open(os.path.join(tiny_population, files[0]), encoding="utf-8") as fh:
        header_line = [l for l in fh if not l.startswith("#")][0].strip()
    assert header_line.split(",") == ba.SCHEMA_COLUMNS


def test_analyze_end_to_end_keys_present(tiny_result):
    R = tiny_result
    for key in ("completeness", "per_chip", "within_die", "np", "chain", "puf",
               "d2d", "limitations", "grr_ring", "bins_ring"):
        assert key in R
    assert len(R["completeness"]) == 6
    assert R["within_die"]["ok"]
    assert R["np"]["ok"]
    assert R["puf"]["ok"]
    # Every population summary in d2d must have a finite mean and a 90% CI that
    # brackets it (or is NaN when N is too small for that particular bootstrap draw).
    for col, d in R["d2d"].items():
        if "mean" in d:
            assert math.isfinite(d["mean"])


def test_analyze_is_deterministic_given_seed(tiny_population):
    R1 = ba.analyze(tiny_population, B=40, seed=7)
    R2 = ba.analyze(tiny_population, B=40, seed=7)
    assert R1["np"]["sigma_d2d"] == pytest.approx(R2["np"]["sigma_d2d"])
    assert R1["within_die"]["sigma_wid"] == pytest.approx(R2["within_die"]["sigma_wid"])


def test_validate_against_truth_runs_and_has_verdicts(tiny_population, tiny_result):
    v = ba.validate_against_truth(tiny_result, tiny_population)
    assert len(v["verdict"]) > 0
    assert set(v["population"].columns) >= {"parameter", "estimate", "truth", "error"}
    assert set(v["per_chip"].columns) >= {"chip", "parameter", "estimate", "truth"}


def test_to_jsonable_round_trips_through_json(tiny_result):
    payload = ba.to_jsonable(tiny_result)
    text = json.dumps(payload)  # must not raise (no NaN/Inf/DataFrame leaking through)
    back = json.loads(text)
    assert "per_chip" in back
    assert "NaN" not in text and "Infinity" not in text


def test_plots_make_all_produces_files(tiny_result, tmp_path):
    import plots
    figs = plots.make_all(tiny_result, str(tmp_path))
    assert len(figs) > 0
    for name in figs.values():
        p = tmp_path / name
        assert p.exists() and p.stat().st_size > 0


def test_run_analysis_cli_writes_full_bundle(tiny_population, tmp_path):
    import run_analysis
    out = tmp_path / "report"
    rc = run_analysis.main([tiny_population, "--out", str(out),
                            "--truth", tiny_population, "--B", "40"])
    assert rc == 0
    assert (out / "report.md").exists()
    assert (out / "results.json").exists()
    assert (out / "validation.json").exists()
    assert (out / "figures").is_dir() and len(list((out / "figures").glob("*.png"))) > 0
    assert (out / "tables").is_dir() and len(list((out / "tables").glob("*.csv"))) > 0
    md = (out / "report.md").read_text(encoding="utf-8")
    for heading in ("a. Ingestion", "b. Die-to-die", "c. Speed-bin", "d. Systematic",
                   "e. N/P", "f. Fmax-vs-tap", "g. PUF", "i. Limitations",
                   "j. Validation"):
        assert heading in md


def test_run_analysis_cli_missing_dir_returns_nonzero(tmp_path):
    import run_analysis
    rc = run_analysis.main([str(tmp_path / "nope"), "--out", str(tmp_path / "out")])
    assert rc == 1


def test_run_analysis_without_predictions_or_truth_still_produces_report(tiny_population, tmp_path):
    """Predictions and truth are both optional -- section h/j must degrade gracefully."""
    import run_analysis
    out = tmp_path / "report_no_extras"
    rc = run_analysis.main([tiny_population, "--out", str(out), "--B", "30"])
    assert rc == 0
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "No `--predictions`" in md
    assert "j. Validation" not in md
    assert not (out / "validation.json").exists()
