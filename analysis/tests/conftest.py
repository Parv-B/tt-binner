import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

import binner_analysis as ba

SCHEMA_HEADER = ",".join(ba.SCHEMA_COLUMNS)


def make_csv_text(rows: list[dict], chip_id="chipA", schema_version=1) -> str:
    """Build a minimal schema-v1 CSV body from a list of row-dicts (missing keys default)."""
    lines = [f"# schema_version={schema_version}", "# script_version=test",
             "# board=unit-test", "# start_time=2026-09-29T00:00:00Z", SCHEMA_HEADER]
    for r in rows:
        row = {c: "" for c in ba.SCHEMA_COLUMNS}
        row["chip_id"] = chip_id
        row["run_id"] = f"{chip_id}-1"
        row.update(r)
        lines.append(",".join(str(row[c]) for c in ba.SCHEMA_COLUMNS))
    return "\n".join(lines) + "\n"


def write_chip_csv(tmp_path, chip_id, rows, **kw) -> str:
    p = tmp_path / f"binner_{chip_id}.csv"
    p.write_text(make_csv_text(rows, chip_id=chip_id, **kw), encoding="utf-8")
    return str(p)


def ring_row(item, y, stage=2, rep=0, x=10e6, flags="", ch="A", pair="", temp_c=25.0):
    return dict(stage=stage, test="ring", item=item, rep=rep, x=x, y=y, unit="Hz",
               aux=f"cnt=1000;gate=100;ch={ch};pair={pair}", temp_c=temp_c, flags=flags)


@pytest.fixture
def rng():
    return np.random.default_rng(0)


@pytest.fixture(scope="session")
def tiny_population(tmp_path_factory):
    """A small (N=6) synthetic population, generated once per test session."""
    import synth_population as sp
    d = tmp_path_factory.mktemp("tiny_pop")
    pl, ph = sp.load_placement(None)
    cfg = sp.SynthConfig(n=6, seed=42, placement=pl, placement_is_placeholder=ph, stage5=True)
    sp.generate(cfg, str(d), write_truth=True)
    return str(d)


@pytest.fixture(scope="session")
def tiny_result(tiny_population):
    """The full analyze() result for the tiny synthetic population, computed once."""
    return ba.analyze(tiny_population, B=60, seed=0)
