"""Tests for analysis/report.py's df_to_md table helper.

These are regression tests for a real bug found during development: a free-
standing ``headers=`` list that didn't match the DataFrame's actual column
count/order produced a Markdown table whose header row and data rows had a
different number of cells (silently misaligned when rendered). df_to_md now
ties display labels to real column names via ``cols``/``rename``.
"""
import numpy as np
import pandas as pd
import pytest

from report import build_report, df_to_md


def _row_cell_count(md_line: str) -> int:
    # "| a | b | c |" -> 3 cells
    return len([c for c in md_line.strip().split("|") if c != ""]) if md_line.strip() else 0


def test_header_and_data_rows_have_equal_cell_counts():
    df = pd.DataFrame({"a": [1, 2, 3], "b": [1.23456, np.nan, -7.1], "c": [[0.1, 0.2], None, [1, 2]]})
    md = df_to_md(df)
    lines = [l for l in md.splitlines() if l.strip()]
    header_cells = _row_cell_count(lines[0])
    for line in lines[2:]:
        assert _row_cell_count(line) == header_cells


def test_cols_selects_and_orders_real_columns():
    df = pd.DataFrame({"z": [1], "a": [2], "m": [3]})
    md = df_to_md(df, cols=["a", "z"])
    header = [l for l in md.splitlines() if l.strip()][0]
    assert header == "| a | z |"


def test_cols_with_unknown_column_raises():
    df = pd.DataFrame({"a": [1]})
    with pytest.raises(KeyError):
        df_to_md(df, cols=["a", "does_not_exist"])


def test_rename_only_relabels_does_not_reorder():
    df = pd.DataFrame({"a": [1], "b": [2]})
    md = df_to_md(df, rename={"b": "B (renamed)"})
    header = [l for l in md.splitlines() if l.strip()][0]
    assert header == "| a | B (renamed) |"


def test_index_name_promotes_index_to_a_named_column():
    df = pd.DataFrame({"v": [10, 20]}, index=pd.Index(["x", "y"], name="chip"))
    md = df_to_md(df, index_name="chip")
    header = [l for l in md.splitlines() if l.strip()][0]
    assert header == "| chip | v |"


def test_none_and_nan_render_as_na_not_python_none():
    df = pd.DataFrame({"a": [None, float("nan"), 1.0]})
    md = df_to_md(df)
    assert "None" not in md
    assert md.count("n/a") == 2


def test_empty_dataframe_does_not_crash():
    assert "no data" in df_to_md(pd.DataFrame())
    assert "no data" in df_to_md(None)


def test_bins_yield_table_shape_matches_real_speed_bins_output():
    """Regression test mirroring the exact call in build_report for the bins table,
    against the real column set binner_analysis.speed_bins produces."""
    import binner_analysis as ba
    rng = np.random.default_rng(0)
    values = pd.Series(np.exp(np.log(2e8) + rng.normal(0, 0.03, 10)), index=[f"c{i}" for i in range(10)])
    func_pass = pd.Series(True, index=values.index)
    b = ba.speed_bins(values, 2e8, 0.001, func_pass, ba.DEFAULT_BINS, B=50, rng=rng)
    md = df_to_md(b["yield"], index_name="bin",
                  cols=["bin", "bin_raw_n", "bin_raw_yield", "bin_raw_ci",
                        "bin_gb_n", "bin_gb_yield", "bin_gb_ci",
                        "model_yield_gb", "model_yield_gb_ci"],
                  rename={"bin_raw_n": "n (raw)", "bin_raw_yield": "yield (raw)",
                          "bin_raw_ci": "CI90 (raw)", "bin_gb_n": "n (GB)",
                          "bin_gb_yield": "yield (GB)", "bin_gb_ci": "CI90 (GB)",
                          "model_yield_gb": "model yield (GB)",
                          "model_yield_gb_ci": "model CI90"})
    lines = [l for l in md.splitlines() if l.strip()]
    header_cells = _row_cell_count(lines[0])
    assert header_cells == 9
    for line in lines[2:]:
        assert _row_cell_count(line) == header_cells


def test_build_report_smoke(tiny_result):
    """The full report assembler must run without raising on a real (small) result,
    with and without a validation block, and every section heading must appear."""
    md = build_report(tiny_result, {}, "some/csv/dir", validation=None)
    assert isinstance(md, str) and len(md) > 500
    for heading in ("a. Ingestion", "b. Die-to-die", "g. PUF metrics", "i. Limitations"):
        assert heading in md
    assert "j. Validation" not in md


def test_build_report_with_validation_block(tiny_population, tiny_result):
    import binner_analysis as ba
    v = ba.validate_against_truth(tiny_result, tiny_population)
    md = build_report(tiny_result, {}, tiny_population, validation=v)
    assert "j. Validation against injected simulation truth" in md
    assert "Overall:" in md
