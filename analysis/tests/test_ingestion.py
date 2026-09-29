"""Tests for CSV ingestion, schema validation and the R1-R7 screening rules
(docs/CSV_SCHEMA.md, binner_analysis.SCREEN_RULES)."""
import numpy as np
import pandas as pd

import binner_analysis as ba
from conftest import make_csv_text, ring_row, write_chip_csv


def _load(tmp_path):
    pop = ba.load_population(str(tmp_path))
    ba.screen_rows(pop, ba.load_model())
    return pop


def test_missing_required_columns_is_fatal(tmp_path):
    p = tmp_path / "binner_bad.csv"
    p.write_text("# schema_version=1\nchip_id,test\nbad,ring\n", encoding="utf-8")
    issues = []
    meta, df = ba.read_chip_csv(str(p), issues)
    assert df is None
    assert any(i["level"] == "ERROR" for i in issues)


def test_unknown_schema_version_warns_but_loads(tmp_path):
    rows = [ring_row("R00", 1.0e8)]
    write_chip_csv(tmp_path, "chipA", rows, schema_version=99)
    issues = []
    meta, df = ba.read_chip_csv(str(tmp_path / "binner_chipA.csv"), issues)
    assert df is not None and len(df) == 1
    assert any(i["check"] == "metadata" for i in issues)


def test_r1_hard_flags_invalidate_row(tmp_path):
    rows = [ring_row("R00", 1.0e8, flags="OVF"), ring_row("R00", 1.02e8)]
    write_chip_csv(tmp_path, "chipA", rows)
    pop = _load(tmp_path)
    d = pop.rows
    ovf = d[d.flagset.map(lambda s: "OVF" in s)]
    assert len(ovf) == 1 and not ovf["valid"].iloc[0] and ovf["reason"].iloc[0] == "R1"
    clean = d[~d.flagset.map(lambda s: "OVF" in s)]
    assert clean["valid"].iloc[0]


def test_r2_implausible_ring_frequency_invalidated(tmp_path):
    # nominal INV freq ~ 200 MHz; 10x nominal should be screened out.
    rows = [ring_row("R00", 2.0e9), ring_row("R00", 2.0e8)]
    write_chip_csv(tmp_path, "chipA", rows)
    pop = _load(tmp_path)
    d = pop.rows.sort_values("y")
    assert not d.iloc[-1]["valid"] and d.iloc[-1]["reason"] == "R2"
    assert d.iloc[0]["valid"]


def test_r3_suspect_used_only_without_clean_repeat(tmp_path):
    # Case A: a clean repeat exists -> SUSPECT dropped.
    rows = [ring_row("R00", 2.0e8, rep=0), ring_row("R00", 2.5e8, rep=1, flags="SUSPECT")]
    write_chip_csv(tmp_path, "chipA", rows)
    pop = _load(tmp_path)
    susp = pop.rows[pop.rows.flagset.map(lambda s: "SUSPECT" in s)]
    assert not susp["valid"].iloc[0] and susp["reason"].iloc[0] == "R3"


def test_r3_suspect_kept_when_no_clean_alternative(tmp_path):
    rows = [ring_row("R00", 2.0e8, rep=0, flags="SUSPECT")]
    write_chip_csv(tmp_path, "chipA", rows)
    pop = _load(tmp_path)
    assert pop.rows["valid"].iloc[0]


def test_r4_repeat_outlier_screen(tmp_path):
    # 5 repeats tightly clustered, 1 wild outlier -> outlier rejected, cluster kept.
    vals = [2.00e8, 2.001e8, 1.999e8, 2.002e8, 2.5e8]
    rows = [ring_row("R00", v, rep=i) for i, v in enumerate(vals)]
    write_chip_csv(tmp_path, "chipA", rows)
    pop = _load(tmp_path)
    d = pop.rows.sort_values("y")
    assert not d.iloc[-1]["valid"] and d.iloc[-1]["reason"] == "R4"
    assert d.iloc[:-1]["valid"].all()


def test_unknown_flags_warn(tmp_path):
    rows = [ring_row("R00", 2.0e8, flags="BOGUS")]
    write_chip_csv(tmp_path, "chipA", rows)
    pop = ba.load_population(str(tmp_path))
    assert any(i["check"] == "flags" for i in pop.issues)


def test_chip_id_mismatch_between_rows_and_filename(tmp_path):
    p = tmp_path / "binner_chipA.csv"
    body = ba.SCHEMA_COLUMNS
    line = ",".join(["chipB" if c == "chip_id" else "" for c in body])
    text = ("# schema_version=1\n" + ",".join(body) + "\n" + line + "\n")
    p.write_text(text, encoding="utf-8")
    issues = []
    meta, df = ba.read_chip_csv(str(p), issues)
    assert any(i["check"] == "chip_id" for i in issues)


def test_empty_directory_raises(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        ba.load_population(str(tmp_path))


def test_partial_chip_missing_stage_degrades_gracefully(tmp_path):
    """A chip with only Stage 1+2 data (no Fmax/PUF) must not crash the pipeline."""
    rows = [dict(stage=1, test="id", item="ID", rep=0, x="", y=1, unit="bool", aux="", flags="")]
    rows += [ring_row(f"R{i:02d}", 2.0e8 + i * 1e5) for i in range(16)]
    write_chip_csv(tmp_path, "chipA", rows)
    R = ba.analyze(str(tmp_path), B=20, seed=0)
    assert "chipA" in R["completeness"].index
    assert R["completeness"].loc["chipA", "Fmax taps"] == "0/8"
    # PUF / chain sections should degrade to "not ok" rather than raising.
    assert R["puf"].get("ok") in (False, None) or R["puf"] == {"ok": False}


def test_multiple_files_same_chip_id_merged_with_warning(tmp_path):
    rows_a = [ring_row("R00", 2.0e8, rep=0)]
    rows_b = [ring_row("R00", 2.0e8, rep=1)]
    (tmp_path / "binner_chipA.csv").write_text(
        make_csv_text(rows_a, chip_id="chipA"), encoding="utf-8")
    (tmp_path / "binner_chipA_2.csv").write_text(
        make_csv_text(rows_b, chip_id="chipA"), encoding="utf-8")
    pop = ba.load_population(str(tmp_path))
    assert (pop.rows.chip_id == "chipA").sum() == 2
    assert any(i["check"] == "duplicate" for i in pop.issues)
