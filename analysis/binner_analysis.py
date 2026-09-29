"""BINNER population analysis library.

Turns a directory of per-chip bring-up CSVs (docs/CSV_SCHEMA.md, schema v1) into
population estimates a product/yield engineer needs: die-to-die distributions,
speed bins with gauge-derived guard bands, systematic-vs-random variance
decomposition, N/P skew per die, Fmax-vs-tap regression, PUF quality metrics,
predicted-vs-measured, small-N limitations and (optionally) a validation against
injected simulation truth.

Conventions
-----------
* Frequencies in Hz, delays in seconds internally; reports use MHz / ns / ps.
* Most statistics are done on ln(f): process variation is multiplicative, so
  sd(ln f) is directly the relative (1-sigma) spread.
* "Delay factor" gradients (g_x, g_y) follow VARIATION_MODEL.md: delay scales by
  (1 + g_x x + g_y y), hence ln f ~ c - g_x x - g_y y.
* Every population statistic carries a 90 % bootstrap CI over chips (the chip is
  the independent unit; rings within a chip are not independent replicates of the
  die-to-die process).

Model file (sensitivities)
--------------------------
``load_model(path)`` deep-merges a JSON over ``DEFAULT_MODEL`` so the nominal
delays, N/P sensitivities (w_n, w_p), temperature coefficient, mux overhead etc.
can later be replaced by SDF/SPICE-derived values without code changes.

Predictions file
----------------
``{item: {"tt": Hz, "ss": Hz, "ff": Hz, "lo": Hz, "hi": Hz}}``. Items: R00..R15,
``INV`` (mean of R00..R15), NAND, NOR, FO4, DCH0..DCH7 (ring frequency) and
T0..T7 (Fmax). Missing keys are allowed; ``lo``/``hi`` default to ss/ff.
Predictions are taken to be at 25 C, so they are compared with temperature-
corrected measurements.
"""
from __future__ import annotations

import copy
import glob
import json
import math
import os
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import optimize, stats

# ======================================================================================
# Model / constants
# ======================================================================================
DEFAULT_MODEL = {
    "structures": {
        "INV": {"d0_ns": 0.100, "w_n": 0.5, "w_p": 0.5, "stages": 25},
        "NAND": {"d0_ns": 0.135, "w_n": 0.7, "w_p": 0.3, "stages": 25},
        "NOR": {"d0_ns": 0.160, "w_n": 0.25, "w_p": 0.75, "stages": 25},
        "FO4": {"d0_ns": 0.230, "w_n": 0.5, "w_p": 0.5, "stages": 25},
        "DLY": {"d0_ns": 3.40, "w_n": 0.5, "w_p": 0.5, "stages": 1},
    },
    "temp_coeff_per_C": 0.0015,   # fractional delay increase per C
    "t_ref_C": 25.0,
    "t_mux_ns": 0.6,              # fixed chain-entry mux overhead
    "t_ov0_ns": 0.9,              # nominal Fmax flop overhead
    "tap_stages": [3, 4, 5, 6, 8, 10, 12, 14],
    "temp_proxy_sigma_C": 1.0,    # 1-sigma uncertainty of RP2350 core temp as die-temp proxy
    "temp_prior_C": [22.0, 35.0], # used when temp_c is missing (uniform prior)
    "fmax_noise_ns": 0.02,        # timing noise band of a pass/fail decision (jitter)
    "chain_stage_mismatch": 0.004,
    "np_use_chain": True,         # include the delay-chain stage delay in the N/P GLS
}

INV_ITEMS = [f"R{i:02d}" for i in range(16)]
DCH_ITEMS = [f"DCH{k}" for k in range(8)]
TAP_ITEMS = [f"T{k}" for k in range(8)]
RING_ITEMS = INV_ITEMS + ["NAND", "NOR", "FO4"] + DCH_ITEMS + ["CLK2"]
PUF_PAIRS = [(2 * n, 2 * n + 1) for n in range(8)] + [(i, i + 8) for i in range(8)]
SCHEMA_COLUMNS = ["chip_id", "fingerprint", "run_id", "t_s", "stage", "test", "item", "rep",
                  "x", "y", "unit", "aux", "temp_c", "flags"]
KNOWN_FLAGS = {"OVF", "NOSEEN", "TIMEOUT", "SIM", "PINMODE", "SUSPECT"}
TEST_SPEC = {  # test -> (allowed stages, unit, item regex)
    "id": ({1}, "bool", r"^ID$"),
    "readback": ({1}, "bool", r"^[A-Z_0-9]+$"),
    "lfsr_kat": ({1}, "bool", r"^N=\d+$"),
    "clk2_kat": ({1}, "count", r"^CLK2$"),
    "pinmode": ({1}, "Hz", r"^(R\d\d|NAND|NOR|FO4|DCH[0-7])$"),
    "ring": ({2, 5}, "Hz", r"^(R(0\d|1[0-5])|NAND|NOR|FO4|DCH[0-7]|CLK2)$"),
    "fmax_pt": ({3}, "frac", r"^T[0-7]$"),
    "fmax": ({3}, "Hz", r"^T[0-7]$"),
    "fmax_inv": ({3}, "bool", r"^T[0-7]$"),
    "puf_pair": ({4, 5}, "ratio", r"^R(0\d|1[0-5])-R(0\d|1[0-5])$"),
    "puf_bit": ({4, 5}, "bit", r"^b(0\d|1[0-5])$"),
    "temp": ({5}, "C", r"^CORE$"),
}
Z90 = stats.norm.ppf(0.95)  # two-sided 90 %


def load_model(path: str | None = None) -> dict:
    m = copy.deepcopy(DEFAULT_MODEL)
    if path:
        with open(path, encoding="utf-8") as fh:
            upd = json.load(fh)

        def merge(a, b):
            for k, v in b.items():
                if isinstance(v, dict) and isinstance(a.get(k), dict):
                    merge(a[k], v)
                else:
                    a[k] = v
        merge(m, upd)
    return m


def nominal_freq(model: dict, kind: str) -> float:
    st = model["structures"][kind]
    return 1.0 / (2 * st["stages"] * st["d0_ns"] * 1e-9)


def item_kind(item: str) -> str:
    if item.startswith("R") and item[1:].isdigit():
        return "INV"
    return item


def parse_aux(s) -> dict:
    out = {}
    if not isinstance(s, str):
        return out
    for tok in s.split(";"):
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def fnum(v, default=np.nan) -> float:
    try:
        f = float(v)
        return f
    except (TypeError, ValueError):
        return default


# ======================================================================================
# Placement
# ======================================================================================
def placeholder_placement() -> dict:
    """Same placeholder as synth_population.default_placement()."""
    p = {}
    grid = [-0.75, -0.25, 0.25, 0.75]
    for i in range(16):
        p[f"R{i:02d}"] = (grid[i % 4], grid[i // 4])
    p.update({"NAND": (-0.6, 0.95), "NOR": (0.0, 0.95), "FO4": (0.6, 0.95), "DCH": (0.0, -0.95)})
    return p


def load_placement(path: str | None) -> tuple[dict, bool, list[str]]:
    """Return (placement, is_placeholder, notes)."""
    notes = []
    if not path or not os.path.exists(path):
        if path:
            notes.append(f"placement file {path} not found")
        notes.append("PLACEHOLDER placement used (4x4 INV grid); gradient estimates are "
                     "only meaningful once tools/place_extract.py output is supplied")
        return placeholder_placement(), True, notes
    df = pd.read_csv(path)
    p = {str(r.item).strip(): (float(r.x_norm), float(r.y_norm)) for r in df.itertuples()}
    if "DCH" not in p:
        for alias in ("DCHAIN", "CHAIN", "DCH0", "T0"):
            if alias in p:
                p["DCH"] = p[alias]
                break
    missing = [i for i in INV_ITEMS + ["NAND", "NOR", "FO4", "DCH"] if i not in p]
    if missing:
        ph = placeholder_placement()
        for m in missing:
            p[m] = ph[m]
        notes.append(f"placement missing {missing}; placeholder coordinates substituted")
    return p, False, notes


# ======================================================================================
# Ingestion + schema validation
# ======================================================================================
@dataclass
class Population:
    rows: pd.DataFrame
    meta: dict
    issues: list = field(default_factory=list)
    files: dict = field(default_factory=dict)

    @property
    def chips(self) -> list[str]:
        return sorted(self.rows["chip_id"].unique()) if len(self.rows) else []


def _issue(issues, chip, level, check, msg):
    issues.append({"chip": chip, "level": level, "check": check, "message": msg})


def read_chip_csv(path: str, issues: list) -> tuple[dict, pd.DataFrame | None]:
    meta, body = {}, []
    fname = os.path.basename(path)
    m = re.match(r"binner_(.+)\.csv$", fname)
    file_chip = m.group(1) if m else fname
    with open(path, encoding="utf-8-sig") as fh:
        for line in fh:
            if line.startswith("#"):
                t = line[1:].strip()
                if "=" in t:
                    k, v = t.split("=", 1)
                    meta[k.strip()] = v.strip()
            elif line.strip():
                body.append(line)
    if not body:
        _issue(issues, file_chip, "ERROR", "empty", f"{fname}: no data rows")
        return meta, None
    from io import StringIO
    df = pd.read_csv(StringIO("".join(body)), dtype=str, keep_default_na=False)
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in SCHEMA_COLUMNS if c not in df.columns]
    extra = [c for c in df.columns if c not in SCHEMA_COLUMNS]
    if extra:
        _issue(issues, file_chip, "WARN", "columns", f"{fname}: extra columns ignored {extra}")
    if missing:
        crit = {"chip_id", "test", "item", "y"} & set(missing)
        _issue(issues, file_chip, "ERROR" if crit else "WARN", "columns",
               f"{fname}: missing columns {missing}")
        if crit:
            return meta, None
        for c in missing:
            df[c] = ""
    df = df[SCHEMA_COLUMNS].copy()
    sv = meta.get("schema_version", meta.get("schema"))
    if sv is None:
        _issue(issues, file_chip, "WARN", "metadata", f"{fname}: no schema_version metadata")
    elif str(sv) != "1":
        _issue(issues, file_chip, "WARN", "metadata", f"{fname}: schema_version={sv} (expected 1)")
    ids = df["chip_id"].unique()
    if len(ids) != 1:
        _issue(issues, file_chip, "ERROR", "chip_id", f"{fname}: multiple chip_ids {list(ids)}; using file name")
        df["chip_id"] = file_chip
    elif ids[0] != file_chip:
        _issue(issues, file_chip, "WARN", "chip_id", f"{fname}: chip_id {ids[0]} != file name; using chip_id")
    for c in ("t_s", "x", "y", "temp_c"):
        df[c] = pd.to_numeric(df[c], errors="coerce")  # "" -> NaN via coerce; no downcast warning
    for c in ("stage", "rep"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    bad = df["stage"].isna() | ~df["stage"].isin([1, 2, 3, 4, 5]) | df["rep"].isna()
    if bad.any():
        _issue(issues, file_chip, "ERROR", "types", f"{fname}: {int(bad.sum())} rows with bad stage/rep dropped")
        df = df[~bad]
    df["stage"] = df["stage"].astype(int)
    df["rep"] = df["rep"].astype(int)
    # test / unit / item / stage consistency
    unk = ~df["test"].isin(TEST_SPEC)
    if unk.any():
        _issue(issues, file_chip, "WARN", "test", f"{fname}: unknown tests ignored {sorted(df.loc[unk, 'test'].unique())}")
        df = df[~unk]
    for t, (stg, unit, rx) in TEST_SPEC.items():
        sel = df["test"] == t
        if not sel.any():
            continue
        s_bad = sel & ~df["stage"].isin(stg)
        u_bad = sel & (df["unit"] != unit)
        i_bad = sel & ~df["item"].str.match(rx)
        if s_bad.any():
            _issue(issues, file_chip, "WARN", "stage", f"{fname}: {t} at unexpected stage(s) {sorted(df.loc[s_bad, 'stage'].unique())}")
        if u_bad.any():
            _issue(issues, file_chip, "WARN", "unit", f"{fname}: {t} unit {sorted(df.loc[u_bad, 'unit'].unique())} != {unit}")
        if i_bad.any():
            _issue(issues, file_chip, "ERROR", "item", f"{fname}: {t} invalid items {sorted(df.loc[i_bad, 'item'].unique())[:5]} dropped")
            df = df[~i_bad]
    flag_tokens = set(t for f in df["flags"] for t in str(f).split(";") if t)
    if flag_tokens - KNOWN_FLAGS:
        _issue(issues, file_chip, "WARN", "flags", f"{fname}: unknown flags {sorted(flag_tokens - KNOWN_FLAGS)}")
    fp = [f for f in df["fingerprint"].unique() if f]
    if len(fp) > 1:
        _issue(issues, file_chip, "WARN", "fingerprint", f"{fname}: multiple fingerprints {fp}")
    for f in fp:
        if not re.fullmatch(r"[0-9A-Fa-f]{16}", f):
            _issue(issues, file_chip, "WARN", "fingerprint", f"{fname}: malformed fingerprint {f}")
    meta["file"] = fname
    return meta, df


def load_population(csv_dir: str) -> Population:
    issues: list = []
    files = sorted(glob.glob(os.path.join(csv_dir, "binner_*.csv")))
    if not files:
        raise FileNotFoundError(f"no binner_*.csv files in {csv_dir}")
    frames, meta, fmap = [], {}, {}
    for f in files:
        m, df = read_chip_csv(f, issues)
        if df is None or not len(df):
            continue
        cid = df["chip_id"].iloc[0]
        if cid in meta:
            _issue(issues, cid, "WARN", "duplicate", f"chip {cid} appears in several files; rows merged")
        meta[cid] = m
        fmap[cid] = os.path.basename(f)
        frames.append(df)
    rows = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=SCHEMA_COLUMNS)
    rows["flagset"] = rows["flags"].map(lambda s: frozenset(t for t in str(s).split(";") if t))
    return Population(rows=rows, meta=meta, issues=issues, files=fmap)


# ======================================================================================
# Screening (documented outlier rules)
# ======================================================================================
SCREEN_RULES = [
    ("R1", "Rows flagged OVF, NOSEEN or TIMEOUT are invalid (counter wrapped / source dead / "
           "handshake failed) and never used."),
    ("R2", "Ring rows with y <= 0, non-finite y, or y outside [1/3, 3] x the nominal model "
           "frequency are invalid (implausible)."),
    ("R3", "SUSPECT rows are used only if no unflagged repeat of the same (chip, stage, test, item) "
           "exists."),
    ("R4", "Repeat screen: within a (chip, stage, item) ring group with >= 3 valid repeats, a value "
           "deviating from the group median by more than max(6 x 1.4826 x MAD, 0.5 %) is rejected."),
    ("R5", "Within-die screen: an INV ring whose residual from the per-chip plane fit exceeds "
           "5 x the pooled within-die sigma is excluded from the gradient / sigma_wid fits "
           "(reported as a ring outlier - in production this is a defect signature)."),
    ("R6", "Chip screen: a chip whose mean INV ln f has a robust z-score (median/MAD over chips) "
           "> 4 is flagged a population outlier; it stays in yield counts but population sigma "
           "is reported with and without it."),
    ("R7", "A chip failing any Stage 1 functional check (ID, register read-back, LFSR "
           "known-answer, CLK2 count +/-1) is binned FUNCTIONAL-FAIL; its parametric data are "
           "still analysed (a digital defect does not invalidate a ring frequency)."),
]


def screen_rows(pop: Population, model: dict) -> pd.DataFrame:
    """Add ``valid``/``reason`` columns implementing rules R1-R4. Returns the frame."""
    df = pop.rows
    df["valid"] = True
    df["reason"] = ""
    hard = df["flagset"].map(lambda s: bool(s & {"OVF", "NOSEEN", "TIMEOUT"}))
    df.loc[hard, ["valid", "reason"]] = [False, "R1"]
    ring = df["test"] == "ring"
    nom = df["item"].map(lambda it: np.nan if it == "CLK2" else _nominal_item(model, it))
    rel = df["y"] / nom
    bad = ring & df["valid"] & (~np.isfinite(df["y"]) | (df["y"] <= 0) |
                                ((df["item"] != "CLK2") & ((rel < 1 / 3) | (rel > 3))))
    df.loc[bad, ["valid", "reason"]] = [False, "R2"]
    susp = df["flagset"].map(lambda s: "SUSPECT" in s)
    if susp.any():
        key = ["chip_id", "stage", "test", "item"]
        clean = df[df["valid"] & ~susp].groupby(key).size()
        for idx in df.index[susp & df["valid"]]:
            k = tuple(df.loc[idx, key])
            if clean.get(k, 0) > 0:
                df.loc[idx, ["valid", "reason"]] = [False, "R3"]
    grp = df[ring & df["valid"]].groupby(["chip_id", "stage", "item"])["y"]
    med = grp.transform("median")
    mad = grp.transform(lambda v: np.median(np.abs(v - np.median(v))))
    cnt = grp.transform("size")
    dev = (df.loc[med.index, "y"] - med).abs()
    thr = np.maximum(6 * 1.4826 * mad, 0.005 * med)
    rej = (cnt >= 3) & (dev > thr)
    df.loc[rej[rej].index, ["valid", "reason"]] = [False, "R4"]
    pop.rows = df
    return df


def _nominal_item(model, item):
    if item.startswith("DCH"):
        k = int(item[3:])
        st = model["structures"]["DLY"]
        D = model["t_mux_ns"] + model["tap_stages"][k] * st["d0_ns"]
        return 1.0 / (2 * D * 1e-9)
    kind = item_kind(item)
    if kind in model["structures"]:
        return nominal_freq(model, kind)
    return np.nan


# ======================================================================================
# Per-chip summaries
# ======================================================================================
def functional_status(pop: Population) -> pd.DataFrame:
    rows = []
    df = pop.rows
    for c in pop.chips:
        d = df[(df.chip_id == c) & (df.stage == 1)]
        r = {"chip": c, "stage1_rows": len(d)}
        idp = d[d.test == "id"]["y"]
        r["id_ok"] = bool(len(idp) and (idp == 1).all())
        rb = d[d.test == "readback"]["y"]
        r["readback_ok"] = bool(len(rb) and (rb == 1).all())
        lk = d[d.test == "lfsr_kat"]
        lk_ok = len(lk) > 0 and (lk["y"] == 1).all()
        for a in lk["aux"]:
            ax = parse_aux(a)
            if "sig" in ax and "exp" in ax and ax["sig"].lower() != ax["exp"].lower():
                lk_ok = False
        r["lfsr_ok"] = bool(lk_ok)
        ck = d[d.test == "clk2_kat"]
        ck_ok = len(ck) > 0
        for _, rr in ck.iterrows():
            exp = fnum(parse_aux(rr["aux"]).get("exp"), rr["x"] / 2 if np.isfinite(rr["x"]) else np.nan)
            ck_ok &= bool(np.isfinite(exp) and abs(rr["y"] - exp) <= 1)
        r["clk2_ok"] = bool(ck_ok)
        r["functional_pass"] = bool(r["id_ok"] and r["readback_ok"] and r["lfsr_ok"] and r["clk2_ok"])
        r["stage1_present"] = len(d) > 0
        rows.append(r)
    return pd.DataFrame(rows).set_index("chip") if rows else pd.DataFrame()


def ring_summary(pop: Population, stage: int = 2) -> pd.DataFrame:
    """Per (chip, item): median valid frequency, n, repeat sd of ln f, per-channel means."""
    df = pop.rows
    d = df[(df.test == "ring") & (df.stage == stage) & df.valid].copy()
    if not len(d):
        return pd.DataFrame(columns=["chip", "item", "f", "n", "sd_ln"])
    d["lnf"] = np.log(d["y"])
    d["ch"] = d["aux"].map(lambda a: parse_aux(a).get("ch", ""))
    g = d.groupby(["chip_id", "item"])
    out = g.agg(f=("y", "median"), n=("y", "size"), lnf_mean=("lnf", "mean"),
                sd_ln=("lnf", lambda v: v.std(ddof=1) if len(v) > 1 else np.nan),
                temp=("temp_c", "median")).reset_index().rename(columns={"chip_id": "chip"})
    return out


def chip_temperature(pop: Population, model: dict) -> pd.Series:
    """Median RP2350 core-temperature proxy per chip over Stage 2 rows (or any rows)."""
    df = pop.rows
    out = {}
    for c in pop.chips:
        d = df[(df.chip_id == c)]
        t = d[d.stage == 2]["temp_c"].dropna()
        if not len(t):
            t = d["temp_c"].dropna()
        out[c] = float(t.median()) if len(t) else np.nan
    return pd.Series(out)


def temp_factor(model, T):
    """Delay factor (1 + beta (T - Tref)); frequency at Tref = f_meas * factor."""
    return 1 + model["temp_coeff_per_C"] * (np.asarray(T, float) - model["t_ref_C"])


def temp_or_prior(model, T):
    """Return (T_used, sigma_T) using the uniform prior when the proxy is missing."""
    lo, hi = model["temp_prior_C"]
    if T is None or not np.isfinite(T):
        return (lo + hi) / 2, (hi - lo) / math.sqrt(12)
    return T, model["temp_proxy_sigma_C"]


def completeness_table(pop: Population, fstat: pd.DataFrame, rs: pd.DataFrame) -> pd.DataFrame:
    df = pop.rows
    rows = []
    for c in pop.chips:
        d = df[df.chip_id == c]
        r = rs[rs.chip == c]
        items = set(r["item"])
        fm = d[(d.test == "fmax") & d.valid]
        fm_taps = set(fm.loc[fm["aux"].map(lambda a: bool(parse_aux(a).get("f_pass"))), "item"])
        pb = d[(d.test == "puf_bit") & (d.stage == 4) & d.valid]
        rows.append({
            "chip": c,
            "stages": "".join(str(s) for s in sorted(d.stage.unique())),
            "functional": "PASS" if fstat.loc[c, "functional_pass"] else
                          ("NO-S1" if not fstat.loc[c, "stage1_present"] else "FAIL"),
            "INV rings": f"{sum(i in items for i in INV_ITEMS)}/16",
            "NAND/NOR/FO4": "".join("Y" if i in items else "-" for i in ("NAND", "NOR", "FO4")),
            "DCH taps": f"{sum(i in items for i in DCH_ITEMS)}/8",
            "Fmax taps": f"{len(fm_taps)}/8",
            "PUF bits": f"{pb['item'].nunique()}/16",
            "PUF reps": int(pb.groupby("item").size().min()) if len(pb) else 0,
            "Stage5": "Y" if (d.stage == 5).any() else "-",
            "temp": "Y" if d["temp_c"].notna().any() else "-",
            "rows": len(d),
            "invalid rows": int((~d.valid).sum()),
            "flags": ",".join(sorted(set().union(*d["flagset"]) - {"SIM"})) or "-",
        })
    t = pd.DataFrame(rows).set_index("chip") if rows else pd.DataFrame()
    return t


# ======================================================================================
# Statistics helpers
# ======================================================================================
def bootstrap(stat_fn, n: int, B: int = 1000, rng=None, alpha: float = 0.10):
    """Nonparametric chip bootstrap. ``stat_fn(idx)`` -> float (or array). Returns (lo, hi, samples)."""
    rng = rng if rng is not None else np.random.default_rng(0)
    if n < 2:
        return np.nan, np.nan, np.array([])
    samples = []
    for _ in range(B):
        idx = rng.integers(0, n, n)
        try:
            samples.append(stat_fn(idx))
        except Exception:  # degenerate resample
            continue
    s = np.array(samples, dtype=float)
    s = s[np.isfinite(s)] if s.ndim == 1 else s
    if not len(s):
        return np.nan, np.nan, s
    return float(np.quantile(s, alpha / 2)), float(np.quantile(s, 1 - alpha / 2)), s


def sd_chi2_ci(sd: float, dof: int, alpha: float = 0.10):
    """Exact (normal-theory) CI for a standard deviation."""
    if dof < 1 or not np.isfinite(sd):
        return np.nan, np.nan
    lo = sd * math.sqrt(dof / stats.chi2.ppf(1 - alpha / 2, dof))
    hi = sd * math.sqrt(dof / stats.chi2.ppf(alpha / 2, dof))
    return lo, hi


def clopper_pearson(k: int, n: int, alpha: float = 0.10):
    if n == 0:
        return np.nan, np.nan
    lo = 0.0 if k == 0 else stats.beta.ppf(alpha / 2, k, n - k + 1)
    hi = 1.0 if k == n else stats.beta.ppf(1 - alpha / 2, k + 1, n - k)
    return float(lo), float(hi)


def pop_summary(values: np.ndarray, B: int, rng, log: bool = True) -> dict:
    """Mean / sd (and relative sd if log) with bootstrap CIs."""
    v = np.asarray(values, float)
    v = v[np.isfinite(v)]
    n = len(v)
    out = {"n": n}
    if n == 0:
        return out
    out["mean"] = float(v.mean())
    out["median"] = float(np.median(v))
    out["sd"] = float(v.std(ddof=1)) if n > 1 else np.nan
    lo, hi, _ = bootstrap(lambda i: v[i].mean(), n, B, rng)
    out["mean_ci"] = [lo, hi]
    lo, hi, _ = bootstrap(lambda i: v[i].std(ddof=1), n, B, rng)
    out["sd_ci"] = [lo, hi]
    if log and (v > 0).all():
        lv = np.log(v)
        out["rel_sd"] = float(lv.std(ddof=1)) if n > 1 else np.nan
        lo, hi, _ = bootstrap(lambda i: lv[i].std(ddof=1), n, B, rng)
        out["rel_sd_ci"] = [lo, hi]
        out["rel_sd_ci_chi2"] = list(sd_chi2_ci(out["rel_sd"], n - 1))
    if n >= 3:
        out["shapiro_p"] = float(stats.shapiro(v).pvalue)
    return out


# ======================================================================================
# (b) die-to-die distributions
# ======================================================================================
def per_chip_metrics(rs: pd.DataFrame, temps: pd.Series, model: dict) -> pd.DataFrame:
    """Per-chip structure frequencies (Hz): mean INV, NAND, NOR, FO4 and derived delays."""
    rows = []
    for c, g in rs.groupby("chip"):
        f = dict(zip(g["item"], g["f"]))
        inv = [f[i] for i in INV_ITEMS if i in f]
        r = {"chip": c, "n_inv": len(inv),
             "f_inv_mean": float(np.mean(inv)) if inv else np.nan,
             "f_nand": f.get("NAND", np.nan), "f_nor": f.get("NOR", np.nan), "f_fo4": f.get("FO4", np.nan)}
        for kind, key in (("INV", "f_inv_mean"), ("NAND", "f_nand"), ("NOR", "f_nor"), ("FO4", "f_fo4")):
            st = model["structures"][kind]
            r["tpd_" + kind.lower() + "_ps"] = 1e12 / (2 * st["stages"] * r[key]) if np.isfinite(r[key]) else np.nan
        T = temps.get(c, np.nan)
        Tu, _ = temp_or_prior(model, T)
        r["temp_c"] = T
        r["f_inv_mean_25C"] = r["f_inv_mean"] * temp_factor(model, Tu)
        rows.append(r)
    return pd.DataFrame(rows).set_index("chip") if rows else pd.DataFrame()


# ======================================================================================
# (d) within-die: plane fit, sigma_wid, REML, gradient consistency
# ======================================================================================
def plane_fit(lnf: np.ndarray, xy: np.ndarray):
    """OLS lnf = c + bx x + by y. Returns (beta, cov_unscaled, resid, dof)."""
    X = np.column_stack([np.ones(len(lnf)), xy])
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ X.T @ lnf
    resid = lnf - X @ beta
    return beta, XtX_inv, resid, len(lnf) - 3


def reml_oneway(groups: list[np.ndarray]):
    """REML for y_ij = mu + a_i + e_ij (unbalanced). Returns (sigma_a, sigma_e, mu)."""
    groups = [np.asarray(g, float) for g in groups if len(g) > 0]
    if len(groups) < 2:
        return np.nan, np.nan, np.nan
    y = np.concatenate(groups)
    ni = np.array([len(g) for g in groups])
    N = len(y)

    def nll(theta):
        sa2, se2 = np.exp(theta)
        # V_i = se2 I + sa2 J ; closed-form det/inverse per group
        w = 1.0 / (se2 + ni * sa2) * ni  # 1' V_i^-1 1
        ybar = np.array([g.mean() for g in groups])
        mu = np.sum(w * ybar) / np.sum(w)
        q = 0.0
        logdet = 0.0
        for g, n_i in zip(groups, ni):
            r = g - mu
            q += (r @ r - sa2 / (se2 + n_i * sa2) * r.sum() ** 2) / se2
            logdet += (n_i - 1) * math.log(se2) + math.log(se2 + n_i * sa2)
        return 0.5 * (logdet + q + math.log(np.sum(w))), mu

    v0 = np.var([g.mean() for g in groups]) + 1e-12
    e0 = np.mean([g.var(ddof=1) for g in groups if len(g) > 1]) + 1e-12
    res = optimize.minimize(lambda t: nll(t)[0], np.log([v0, e0]), method="Nelder-Mead",
                            options={"xatol": 1e-6, "fatol": 1e-9, "maxiter": 4000})
    sa2, se2 = np.exp(res.x)
    return math.sqrt(sa2), math.sqrt(se2), nll(res.x)[1]


def within_die(rs: pd.DataFrame, placement: dict, B: int, rng) -> dict:
    """Per-chip plane fits on the 16 identical INV rings + population decomposition."""
    per, resid_all, meas_var = [], {}, []
    xy_all = np.array([placement[i] for i in INV_ITEMS])
    for c, g in rs[rs["item"].isin(INV_ITEMS)].groupby("chip"):
        g = g.set_index("item").reindex(INV_ITEMS).dropna(subset=["f"])
        if len(g) < 6:
            continue
        per.append({"chip": c, "items": list(g.index), "lnf": np.log(g["f"].values),
                    "xy": np.array([placement[i] for i in g.index]),
                    "meas_var": np.nanmean((g["sd_ln"] ** 2 / g["n"]).values) if g["sd_ln"].notna().any() else 0.0})
    if not per:
        return {"ok": False}
    # pass 1: fits, robust pooled sigma, R5 outlier exclusion, refit
    def fit_all(per):
        for p in per:
            m = p.get("mask", np.ones(len(p["lnf"]), bool))
            beta, cu, res, dof = plane_fit(p["lnf"][m], p["xy"][m])
            full_res = p["lnf"] - np.column_stack([np.ones(len(p["lnf"])), p["xy"]]) @ beta
            p.update(beta=beta, cu=cu, res=full_res, dof=dof, m=m)
    fit_all(per)
    allres = np.concatenate([p["res"] for p in per])
    sig_rob = 1.4826 * np.median(np.abs(allres - np.median(allres))) * math.sqrt(16 / 13)
    outliers = []
    for p in per:
        m = np.abs(p["res"]) <= 5 * sig_rob
        if (~m).any():
            outliers += [(p["chip"], p["items"][k], float(p["res"][k])) for k in np.where(~m)[0]]
        p["mask"] = m
    fit_all(per)
    rss = np.array([np.sum(p["res"][p["m"]] ** 2) for p in per])
    dof = np.array([p["dof"] for p in per])
    mv = np.array([p["meas_var"] for p in per])

    def swid(idx):
        s2 = rss[idx].sum() / dof[idx].sum() - np.nanmean(mv[idx])
        return math.sqrt(max(s2, 0.0))

    s_res = math.sqrt(rss.sum() / dof.sum())
    s_wid = swid(np.arange(len(per)))
    lo, hi, _ = bootstrap(swid, len(per), B, rng)
    chips = []
    for p in per:
        s2 = s_res ** 2  # pooled residual variance (more stable than per-chip at 13 dof)
        se = np.sqrt(np.diag(p["cu"]) * s2)
        tq = stats.t.ppf(0.95, dof.sum())
        chips.append({"chip": p["chip"], "c_lnf": p["beta"][0], "se_c": se[0],
                      "g_x": -p["beta"][1], "g_y": -p["beta"][2], "se_gx": se[1], "se_gy": se[2],
                      "g_x_ci": [-p["beta"][1] - tq * se[1], -p["beta"][1] + tq * se[1]],
                      "g_y_ci": [-p["beta"][2] - tq * se[2], -p["beta"][2] + tq * se[2]],
                      "n_rings": int(p["m"].sum()), "rms_resid": float(np.sqrt(np.mean(p["res"][p["m"]] ** 2)))})
    ct = pd.DataFrame(chips).set_index("chip")
    # REML one-way on raw ln f (die-to-die vs total within-die incl. gradient)
    groups = [p["lnf"][p["m"]] for p in per]
    sa, se_tot, _ = reml_oneway(groups)
    # REML on plane-corrected values: intercept variance vs random within
    groups_c = [p["res"][p["m"]] + p["beta"][0] for p in per]
    sa_c, se_c, _ = reml_oneway(groups_c)
    # gradient variance explained within die: mean over rings of (g . r)^2
    grad_var = np.mean([np.mean((p["xy"][p["m"]] @ p["beta"][1:]) ** 2) for p in per])
    grad_var_true = max(grad_var - np.mean([np.mean(np.einsum("ij,jk,ik->i", p["xy"][p["m"]], p["cu"][1:, 1:] * s_res ** 2, p["xy"][p["m"]])) for p in per]), 0)
    # mean residual map over chips (common layout systematic beyond linear)
    resmap = pd.DataFrame({p["chip"]: pd.Series(p["res"], index=p["items"]) for p in per}).T
    gt = gradient_consistency(ct)
    return {
        "ok": True, "per_chip": ct, "sigma_resid": s_res, "sigma_wid": s_wid, "sigma_wid_ci": [lo, hi],
        "sigma_meas": float(math.sqrt(np.nanmean(mv))), "dof": int(dof.sum()),
        "reml_raw": {"sigma_d2d_lnf": sa, "sigma_within_total": se_tot},
        "reml_plane": {"sigma_d2d_lnf": sa_c, "sigma_within_random": se_c},
        "var_components": {"die_to_die": sa ** 2, "within_systematic_gradient": grad_var_true,
                           "within_random": s_wid ** 2, "measurement": float(np.nanmean(mv))},
        "ring_outliers": outliers, "resid_map_mean": resmap.mean(0).to_dict(),
        "resid_map_se": (resmap.std(0, ddof=1) / np.sqrt(len(resmap))).to_dict() if len(resmap) > 1 else {},
        "gradient_test": gt, "n_chips": len(per),
    }


def gradient_consistency(ct: pd.DataFrame) -> dict:
    """Is the gradient common (layout-driven) or random per die?

    * Common mean: Hotelling T^2 on (g_x, g_y) across chips, H0: E[g] = 0.
    * Die-to-die variability: chi^2 = sum((g_i - gbar)^2 / se_i^2) ~ chi2(N-1) per axis
      under H0 "every die has the same gradient"; tau^2 = var(g) - mean(se^2).
    * Power: minimum common gradient detectable at alpha=0.05 (two-sided), 80 % power.
    """
    N = len(ct)
    out = {"n": N}
    if N < 3:
        return out
    G = ct[["g_x", "g_y"]].values
    gbar = G.mean(0)
    S = np.cov(G.T, ddof=1)
    try:
        T2 = N * gbar @ np.linalg.solve(S, gbar)
        F = (N - 2) / (2 * (N - 1)) * T2
        p = float(stats.f.sf(F, 2, N - 2)) if N > 2 else np.nan
    except np.linalg.LinAlgError:
        T2, p = np.nan, np.nan
    out.update(mean_gx=float(gbar[0]), mean_gy=float(gbar[1]),
               mean_se=[float(math.sqrt(S[0, 0] / N)), float(math.sqrt(S[1, 1] / N))],
               hotelling_T2=float(T2), p_common=p)
    for ax, se_col in (("g_x", "se_gx"), ("g_y", "se_gy")):
        g, se = ct[ax].values, ct[se_col].values
        chi2 = float(np.sum((g - g.mean()) ** 2 / se ** 2))
        tau2 = g.var(ddof=1) - np.mean(se ** 2)
        out[f"chi2_{ax}"] = chi2
        out[f"p_random_{ax}"] = float(stats.chi2.sf(chi2, N - 1))
        out[f"tau_{ax}"] = float(math.sqrt(max(tau2, 0)))
    sd_tot = float(np.sqrt(np.mean(np.diag(S))))
    out["mde_common"] = float((stats.norm.ppf(0.975) + stats.norm.ppf(0.8)) * sd_tot / math.sqrt(N))
    out["se_single_die"] = float(ct["se_gx"].mean())
    pc = out["p_common"] < 0.05
    pr = min(out["p_random_g_x"], out["p_random_g_y"]) < 0.05 / 2
    out["verdict"] = ("common (layout-driven) gradient" if pc and not pr else
                      "common gradient plus die-to-die random gradient" if pc and pr else
                      "random per-die gradient (no common component detected)" if pr else
                      "no gradient detectable above per-die fit noise")
    return out


# ======================================================================================
# (e) N/P skew inference
# ======================================================================================
def np_skew(rs: pd.DataFrame, wd: dict, chain: pd.DataFrame | None, temps: pd.Series,
            placement: dict, model: dict, B: int, rng) -> dict:
    """Per-chip (s_n, s_p) by GLS on log-frequency deviations from the nominal model.

    Observation for structure k (gradient- and temperature-corrected):
        z_k = ln f_k + ln(2 N_k d0_k) + ln(1 + beta (T - 25)) + ln(1 + g . r_k)
            = w_nk s_n + w_pk s_p + noise_k
    INV uses the plane-fit intercept (16 rings -> variance sigma_wid^2 * c_unscaled);
    NAND/NOR/FO4 are single rings (variance sigma_wid^2); the delay-chain stage delay
    (DCH slope, optional) adds an observation with its regression variance. The
    temperature-proxy error is common to all observations (full covariance).
    Because every structure's (w_n + w_p) = 1 in the default model, the ratios fix only
    s_n - s_p; the sum s_n + s_p rests on the absolute frequency (i.e. on d0 and T).
    """
    if not wd.get("ok"):
        return {"ok": False}
    sw = wd["sigma_wid"]
    beta_T = model["temp_coeff_per_C"]
    S = model["structures"]
    rows = []
    for c in wd["per_chip"].index:
        pc = wd["per_chip"].loc[c]
        g = rs[rs.chip == c].set_index("item")
        T, sT = temp_or_prior(model, temps.get(c, np.nan))
        tf = math.log(temp_factor(model, T))
        X, z, var = [], [], []
        used = []
        z.append(pc["c_lnf"] + math.log(2 * S["INV"]["stages"] * S["INV"]["d0_ns"] * 1e-9) + tf)
        X.append([S["INV"]["w_n"], S["INV"]["w_p"]]); var.append(pc["se_c"] ** 2); used.append("INV")
        for kind in ("NAND", "NOR", "FO4"):
            if kind in g.index and np.isfinite(g.loc[kind, "f"]):
                x, y = placement[kind]
                gcorr = math.log(max(1 + pc["g_x"] * x + pc["g_y"] * y, 1e-3))
                z.append(math.log(g.loc[kind, "f"]) + math.log(2 * S[kind]["stages"] * S[kind]["d0_ns"] * 1e-9) + tf + gcorr)
                X.append([S[kind]["w_n"], S[kind]["w_p"]])
                se_grad2 = (x ** 2 * pc["se_gx"] ** 2 + y ** 2 * pc["se_gy"] ** 2)
                var.append(sw ** 2 + se_grad2); used.append(kind)
        if model.get("np_use_chain", True) and chain is not None and "t_stage_dch" in chain.columns \
                and c in chain.index and np.isfinite(chain.loc[c, "t_stage_dch"]):
            x, y = placement["DCH"]
            gcorr = math.log(max(1 + pc["g_x"] * x + pc["g_y"] * y, 1e-3))
            ts = chain.loc[c, "t_stage_dch"]
            z.append(math.log(S["DLY"]["d0_ns"] * 1e-9 / ts) + tf + gcorr)
            X.append([S["DLY"]["w_n"], S["DLY"]["w_p"]])
            rel = chain.loc[c, "se_t_stage_dch"] / ts
            var.append(rel ** 2 + (model["chain_stage_mismatch"] ** 2) / 14 +
                       x ** 2 * pc["se_gx"] ** 2 + y ** 2 * pc["se_gy"] ** 2)
            used.append("DLY")
        X, z = np.array(X), np.array(z)
        V = np.diag(var) + (beta_T * sT) ** 2 * np.ones((len(z), len(z)))
        Vi = np.linalg.inv(V)
        try:
            cov = np.linalg.inv(X.T @ Vi @ X)
        except np.linalg.LinAlgError:
            continue
        s = cov @ X.T @ Vi @ z
        dvec = np.array([1, -1])
        rows.append({"chip": c, "s_n": s[0], "s_p": s[1], "se_s_n": math.sqrt(cov[0, 0]),
                     "se_s_p": math.sqrt(cov[1, 1]), "cov_np": cov[0, 1],
                     "delta": s[0] - s[1], "se_delta": math.sqrt(dvec @ cov @ dvec),
                     "sigma_sum": s[0] + s[1], "se_sum": math.sqrt(np.ones(2) @ cov @ np.ones(2)),
                     "structures": "+".join(used), "temp_used": T})
    if not rows:
        return {"ok": False}
    t = pd.DataFrame(rows).set_index("chip")
    for k in ("s_n", "s_p", "delta"):
        se = t["se_" + k]
        t[k + "_ci"] = [[v - Z90 * e, v + Z90 * e] for v, e in zip(t[k], se)]
    sn, sp = t["s_n"].values, t["s_p"].values
    en, ep, ec = t["se_s_n"].values ** 2, t["se_s_p"].values ** 2, t["cov_np"].values

    def mom(idx):
        v = (np.var(sn[idx], ddof=1) + np.var(sp[idx], ddof=1) - en[idx].mean() - ep[idx].mean()) / 2
        return math.sqrt(max(v, 0.0))

    def rho_fn(idx):
        s2 = mom(idx) ** 2
        c = np.cov(sn[idx], sp[idx], ddof=1)[0, 1] - ec[idx].mean()
        return float(np.clip(c / s2, -1, 1)) if s2 > 0 else np.nan

    n = len(t)
    idx = np.arange(n)
    sig = mom(idx)
    lo, hi, _ = bootstrap(mom, n, B, rng)
    rlo, rhi, _ = bootstrap(rho_fn, n, B, rng)
    return {"ok": True, "per_chip": t, "sigma_d2d": sig, "sigma_d2d_ci": [lo, hi],
            "sigma_d2d_ci_chi2": list(sd_chi2_ci(sig, 2 * (n - 1))),
            "rho": rho_fn(idx), "rho_ci": [rlo, rhi],
            "median_se_delta": float(np.median(t["se_delta"])),
            "median_se_sum": float(np.median(t["se_sum"]))}


def sigma_d2d_from_inv(pcm: pd.DataFrame, rho: float, B: int, rng) -> dict:
    """sigma of ln(mean INV f) at 25 C and implied sigma_d2d = sigma_INV * sqrt(2/(1+rho))."""
    v = np.log(pcm["f_inv_mean_25C"].dropna().values)
    n = len(v)
    if n < 2:
        return {}
    s = float(v.std(ddof=1))
    lo, hi, _ = bootstrap(lambda i: v[i].std(ddof=1), n, B, rng)
    r = rho if np.isfinite(rho) else 0.0
    k = math.sqrt(2 / (1 + max(min(r, 0.99), -0.5)))
    return {"sigma_inv_lnf": s, "sigma_inv_ci": [lo, hi], "rho_used": r,
            "sigma_d2d_implied": s * k, "sigma_d2d_implied_ci": [lo * k, hi * k]}


# ======================================================================================
# (f) Fmax-vs-tap regression and DCH ring regression
# ======================================================================================
def fmax_intervals(pop: Population, chip: str) -> pd.DataFrame:
    """Per tap: pass/fail frequency interval combined over repeats (intersection if
    consistent, union otherwise). Falls back to fmax_pt points if no ``fmax`` row."""
    df = pop.rows
    d = df[(df.chip_id == chip) & (df.stage == 3) & df.valid]
    out = []
    for k, tap in enumerate(TAP_ITEMS):
        fm = d[(d.test == "fmax") & (d.item == tap)]
        passes, fails = [], []
        for _, r in fm.iterrows():
            a = parse_aux(r["aux"])
            fp, ff = fnum(a.get("f_pass")), fnum(a.get("f_fail"))
            if not np.isfinite(fp) and np.isfinite(r["y"]):
                fp = r["y"]
            passes.append(fp if np.isfinite(fp) else 0.0)
            fails.append(ff if np.isfinite(ff) else np.inf)
        if not passes:
            pt = d[(d.test == "fmax_pt") & (d.item == tap)]
            if not len(pt):
                continue
            ok = pt[pt.y == 0]["x"]
            bad = pt[pt.y > 0]["x"]
            passes = [ok.max() if len(ok) else 0.0]
            fails = [bad[bad > passes[0]].min() if (bad > passes[0]).any() else np.inf]
        lo, hi = max(passes), min(fails)
        consistent = lo < hi
        if not consistent:
            lo, hi = min(passes), max(fails)
        out.append({"tap": tap, "k": k, "f_pass": lo, "f_fail": hi, "n_rep": len(passes),
                    "consistent": consistent})
    return pd.DataFrame(out)


def _censored_fit(n, L, U, sig, a0, b0):
    """Interval-censored Gaussian ML for period = a + b n; L/U in seconds (U may be inf)."""
    scale = 1e9  # work in ns

    def nll(p):
        mu = (p[0] + p[1] * n)
        hi = stats.norm.cdf((U * scale - mu) / sig)
        lo = stats.norm.cdf((L * scale - mu) / sig)
        return -np.sum(np.log(np.clip(hi - lo, 1e-300, None)))

    res = optimize.minimize(nll, [a0 * scale, b0 * scale], method="Nelder-Mead",
                            options={"xatol": 1e-7, "fatol": 1e-10, "maxiter": 5000})
    p = res.x
    # numerical Hessian
    h = np.array([1e-3, 1e-4])
    H = np.zeros((2, 2))
    f0 = nll(p)
    for i in range(2):
        for j in range(2):
            ei, ej = np.eye(2)[i] * h[i], np.eye(2)[j] * h[j]
            H[i, j] = (nll(p + ei + ej) - nll(p + ei - ej) - nll(p - ei + ej) + nll(p - ei - ej)) / (4 * h[i] * h[j])
    try:
        cov = np.linalg.inv(H)
        if not np.all(np.isfinite(cov)) or np.any(np.diag(cov) <= 0):
            raise np.linalg.LinAlgError
    except np.linalg.LinAlgError:
        cov = np.full((2, 2), np.nan)
    return p / scale, cov / scale ** 2, bool(res.success), f0


def chain_analysis(pop: Population, rs: pd.DataFrame, model: dict, B: int, rng) -> dict:
    taps = np.array(model["tap_stages"], float)
    t_mux = model["t_mux_ns"] * 1e-9
    rows, fits = [], {}
    for c in pop.chips:
        r = {"chip": c}
        # DCH ring: half period vs stage count
        g = rs[(rs.chip == c) & rs["item"].isin(DCH_ITEMS)].set_index("item")
        if len(g) >= 3:
            ks = [int(i[3:]) for i in g.index]
            n_ = taps[ks]
            hp = 1 / (2 * g["f"].values)
            X = np.column_stack([np.ones(len(n_)), n_])
            beta, *_ = np.linalg.lstsq(X, hp, rcond=None)
            res = hp - X @ beta
            dof = len(n_) - 2
            s2 = res @ res / dof if dof > 0 else np.nan
            cov = np.linalg.inv(X.T @ X) * s2
            r.update(t_stage_dch=beta[1], se_t_stage_dch=math.sqrt(cov[1, 1]) if dof > 0 else np.nan,
                     t_mux_dch=beta[0], se_t_mux_dch=math.sqrt(cov[0, 0]) if dof > 0 else np.nan,
                     n_dch=len(n_))
            fits.setdefault(c, {})["dch"] = (n_, hp)
        iv = fmax_intervals(pop, c)
        if len(iv) >= 3 and (iv["f_pass"] > 0).sum() >= 2:
            n_ = taps[iv["k"].values]
            L = 1 / iv["f_fail"].values                            # shortest period that failed -> lower bound of true min period
            U = np.where(iv["f_pass"].values > 0, 1 / iv["f_pass"].values, np.inf)
            # midpoint WLS
            fin = np.isfinite(U) & (L > 0)
            mid = (L + U) / 2
            w2 = (U - L) ** 2 / 12
            sig_ns = np.sqrt(model["fmax_noise_ns"] ** 2 + n_ * (model["chain_stage_mismatch"] * model["structures"]["DLY"]["d0_ns"]) ** 2)
            vv = w2 + (sig_ns * 1e-9) ** 2
            X = np.column_stack([np.ones(fin.sum()), n_[fin]])
            W = np.diag(1 / vv[fin])
            covw = np.linalg.inv(X.T @ W @ X)
            bw = covw @ X.T @ W @ mid[fin]
            # censored ML (primary)
            bc, covc, ok, _ = _censored_fit(n_, L, U, sig_ns, bw[0], bw[1])
            r.update(t_stage_wls=bw[1], se_t_stage_wls=math.sqrt(covw[1, 1]),
                     a_wls=bw[0], t_stage=bc[1], se_t_stage=math.sqrt(covc[1, 1]),
                     a_fmax=bc[0], se_a_fmax=math.sqrt(covc[0, 0]), cens_ok=ok,
                     t_ov=bc[0] - t_mux, se_t_ov=math.sqrt(covc[0, 0]),
                     n_taps=int(len(iv)), fmax_rel_step=float(np.nanmedian((U - L)[fin] / mid[fin])),
                     monotone=bool(np.all(np.diff(iv.sort_values("k")["f_pass"].values) <= 0)))
            if "t_mux_dch" in r:
                r["t_ov_via_dch"] = bc[0] - r["t_mux_dch"]
            for k, tap in zip(iv["k"], iv["tap"]):
                r["fmax_" + tap] = float(iv.loc[iv.k == k, "f_pass"].iloc[0])
                r["fmax_fail_" + tap] = float(iv.loc[iv.k == k, "f_fail"].iloc[0])
            fits.setdefault(c, {})["fmax"] = (n_, L, U, bc)
        rows.append(r)
    t = pd.DataFrame(rows).set_index("chip")
    out = {"per_chip": t, "fits": fits}
    for col in ("t_stage", "t_ov", "t_stage_dch", "t_mux_dch"):
        if col in t and t[col].notna().sum() >= 2:
            out["pop_" + col] = pop_summary(t[col].dropna().values, B, rng)
    if "t_stage" in t and "t_stage_dch" in t:
        both = t[["t_stage", "t_stage_dch"]].dropna()
        if len(both) >= 2:
            ratio = both["t_stage"] / both["t_stage_dch"]
            out["cross_check"] = {"ratio_mean": float(ratio.mean()), "ratio_sd": float(ratio.std(ddof=1)),
                                  "corr": float(np.corrcoef(both.values.T)[0, 1]) if len(both) > 2 else np.nan}
    return out


# ======================================================================================
# (c) gauge R&R + speed bins
# ======================================================================================
def grr_ring(pop: Population, model: dict, temps: pd.Series) -> dict:
    """Gauge R&R for the bin metric 'mean INV ring frequency'.

    Each Stage 2 repeat is one complete pass over the 16 rings (with the A/B channel
    assignment swapped on alternate passes), i.e. one full re-test of the part. The
    metric per pass m_cr = mean_ring ln f. Repeatability = pooled within-chip sd of
    m_cr; part-to-part = between-chip sd of chip means (corrected for repeatability).
    Test-condition term: temperature-proxy uncertainty beta * sigma_T after correction to
    25 C (a Type-B component: it is invisible in same-session repeats).
    """
    df = pop.rows
    d = df[(df.test == "ring") & (df.stage == 2) & df.valid & df["item"].isin(INV_ITEMS)].copy()
    if not len(d):
        return {}
    d["lnf"] = np.log(d["y"])
    # use rings measured in all passes of that chip so pass means are comparable
    m = d.groupby(["chip_id", "rep"])["lnf"].mean().unstack()
    reps = m.notna().sum(1)
    m = m[reps >= 2]
    if len(m) < 2:
        return {}
    within = m.sub(m.mean(1), axis=0)
    dof = int((m.notna().sum(1) - 1).sum())
    s_rep = math.sqrt(np.nansum(within.values ** 2) / dof)
    nbar = float(m.notna().sum(1).mean())
    chip_means = m.mean(1)
    s_part = math.sqrt(max(chip_means.var(ddof=1) - s_rep ** 2 / nbar, 0))
    s_T = model["temp_coeff_per_C"] * model["temp_proxy_sigma_C"]
    res = {"metric": "mean INV ring ln f", "sigma_repeat": s_rep, "sigma_part": s_part,
           "sigma_temp": s_T, "n_chips": len(m), "reps": nbar}
    for tag, sms in (("gauge", s_rep), ("gauge+temp", math.sqrt(s_rep ** 2 + s_T ** 2))):
        tv = math.sqrt(sms ** 2 + s_part ** 2)
        res[tag] = {"sigma_ms": sms, "pct_grr": 100 * sms / tv if tv > 0 else np.nan,
                    "ndc": int(1.41 * s_part / sms) if sms > 0 else np.inf}
    return res


def grr_fmax(chain: dict, pop: Population, tap: str) -> dict:
    """GRR for Fmax at one tap: repeatability from repeated binary searches, floored by
    the PWM quantisation (step^2/12) because identical repeats cannot reveal sub-step noise."""
    t = chain["per_chip"]
    col = "fmax_" + tap
    if col not in t or t[col].notna().sum() < 2:
        return {}
    df = pop.rows
    fm = df[(df.test == "fmax") & (df.item == tap) & df.valid]
    per = fm.groupby("chip_id")["y"].agg(lambda v: np.log(v.astype(float)).var(ddof=1) if len(v) > 1 else np.nan)
    s_rep_obs = math.sqrt(np.nanmean(per.values)) if per.notna().any() else 0.0
    step = np.log(t["fmax_fail_" + tap] / t[col]).replace([np.inf, -np.inf], np.nan)
    s_q = float(np.sqrt(np.nanmean(step ** 2) / 12))
    sms = math.sqrt(max(s_rep_obs, s_q) ** 2)
    lf = np.log(t[col].dropna())
    s_part = math.sqrt(max(lf.var(ddof=1) - sms ** 2, 0))
    tv = math.sqrt(sms ** 2 + s_part ** 2)
    return {"metric": f"Fmax {tap} ln f", "sigma_repeat_obs": s_rep_obs, "sigma_quant": s_q,
            "sigma_ms": sms, "sigma_part": s_part, "pct_grr": 100 * sms / tv if tv else np.nan,
            "ndc": int(1.41 * s_part / sms) if sms > 0 else np.inf, "n_chips": int(len(lf))}


DEFAULT_BINS = {
    # limits are relative to the nominal (TT, 25 C) value of the metric; highest bin first
    "limits": [["BIN1-FAST", 1.03], ["BIN2-TYP", 0.97], ["BIN3-SLOW", 0.90]],
    "reject": "REJECT-SLOW",
    "guard_z": 1.645,   # guard band = z * sigma_measurement (5 % one-sided misbin risk at a limit)
}


def speed_bins(values: pd.Series, f_nom: float, sigma_ms_rel: float, func_pass: pd.Series,
               bins: dict, B: int, rng) -> dict:
    """Assign bins with and without guard band; yields with Clopper-Pearson 90 % CIs, and a
    model-based (normal fit) yield with bootstrap CIs, which is more stable at small N."""
    gb = bins["guard_z"] * sigma_ms_rel
    names = [b[0] for b in bins["limits"]] + [bins["reject"]]
    rows = []
    for c in func_pass.index.union(values.index):
        v = values.get(c, np.nan)
        fp = bool(func_pass.get(c, False))
        r = {"chip": c, "value": v, "rel": v / f_nom if np.isfinite(v) else np.nan}
        for tag, g in (("bin_raw", 0.0), ("bin_gb", gb)):
            if not fp:
                r[tag] = "FUNCTIONAL-FAIL"
            elif not np.isfinite(v):
                r[tag] = "NO-DATA"
            else:
                r[tag] = bins["reject"]
                for name, lim in bins["limits"]:
                    if r["rel"] >= lim * (1 + g):
                        r[tag] = name
                        break
        # risk that the true value is below the lower limit of the assigned (raw) bin
        lim = dict(bins["limits"]).get(r["bin_raw"])
        r["misbin_risk"] = float(stats.norm.cdf((math.log(lim) - math.log(r["rel"])) / sigma_ms_rel)) \
            if lim and np.isfinite(r["rel"]) and sigma_ms_rel > 0 else 0.0
        rows.append(r)
    t = pd.DataFrame(rows).set_index("chip")
    N = len(t)
    yields = []
    lv = np.log(t["rel"].dropna().values)
    edges = [math.inf] + [math.log(l) for _, l in bins["limits"]] + [-math.inf]
    for i, name in enumerate(names + ["FUNCTIONAL-FAIL", "NO-DATA"]):
        row = {"bin": name}
        for tag in ("bin_raw", "bin_gb"):
            k = int((t[tag] == name).sum())
            lo, hi = clopper_pearson(k, N)
            row[tag + "_n"], row[tag + "_yield"], row[tag + "_ci"] = k, k / N if N else np.nan, [lo, hi]
        if i < len(names) and len(lv) >= 3:
            up, dn = edges[i], edges[i + 1]
            if i < len(names) - 1 or True:
                up_g = up + gb if np.isfinite(up) else up
                dn_g = dn + gb if np.isfinite(dn) else dn

            def mfy(idx, up=up_g, dn=dn_g):
                mu, sd = lv[idx].mean(), lv[idx].std(ddof=1)
                return stats.norm.cdf((up - mu) / sd) - stats.norm.cdf((dn - mu) / sd)
            row["model_yield_gb"] = float(mfy(np.arange(len(lv))))
            lo, hi, _ = bootstrap(mfy, len(lv), B, rng)
            row["model_yield_gb_ci"] = [lo, hi]
        yields.append(row)
    return {"per_chip": t, "yield": pd.DataFrame(yields).set_index("bin"), "guard_band_rel": gb,
            "f_nom": f_nom, "limits": bins["limits"]}


# ======================================================================================
# (g) PUF metrics
# ======================================================================================
def puf_analysis(pop: Population, sigma_wid: float, sigma_rep: float, B: int, rng) -> dict:
    df = pop.rows
    d = df[(df.test == "puf_bit") & df.valid].copy()
    if not len(d):
        return {"ok": False}
    d["bit"] = d["item"].str[1:].astype(int)
    ref, reps, hot = {}, {}, {}
    fp_check = {}
    for c, g in d.groupby("chip_id"):
        g4 = g[g.stage == 4]
        if not len(g4):
            continue
        M = g4.pivot_table(index="rep", columns="bit", values="y", aggfunc="first").reindex(columns=range(16))
        maj = (M.mean(0) > 0.5).astype(float).where(M.notna().any(axis=0))
        ref[c] = maj.values
        reps[c] = M.values
        g5 = g[g.stage == 5]
        if len(g5):
            hot[c] = g5.pivot_table(index="rep", columns="bit", values="y", aggfunc="first").reindex(columns=range(16)).values
        fps = [f for f in df.loc[df.chip_id == c, "fingerprint"].unique() if f]
        if fps and np.isfinite(maj.values).all():
            word = int(fps[0][:4], 16)
            bits_fp = np.array([(word >> n) & 1 for n in range(16)])
            fp_check[c] = int(np.sum(bits_fp != maj.values))
    chips = sorted(ref)
    N = len(chips)
    if N == 0:
        return {"ok": False}
    R = np.array([ref[c] for c in chips])  # N x 16
    nb = 16
    unif = np.nanmean(R, 1)
    # inter-chip HD
    pairs, hds = [], []
    for i in range(N):
        for j in range(i + 1, N):
            ok = np.isfinite(R[i]) & np.isfinite(R[j])
            hds.append(np.mean(R[i, ok] != R[j, ok]))
            pairs.append((chips[i], chips[j]))
    hds = np.array(hds)
    out = {"ok": True, "n_chips": N, "chips": chips, "bits": R.tolist(),
           "uniformity": dict(zip(chips, unif.tolist())),
           "uniformity_mean": float(np.nanmean(unif)),
           "fingerprint_mismatch_bits": fp_check}
    lo, hi, _ = bootstrap(lambda i: np.nanmean(R[i]), N, B, rng)
    out["uniformity_ci"] = [lo, hi]
    if len(hds):
        out["inter_hd_mean"] = float(hds.mean())
        out["inter_hd_sd"] = float(hds.std(ddof=1)) if len(hds) > 1 else np.nan
        out["inter_hd_min"] = float(hds.min())
        out["inter_hd_pairs"] = len(hds)
        k = int(round(hds.mean() * nb * len(hds)))
        out["inter_hd_naive_ci"] = list(clopper_pearson(k, nb * len(hds)))

        def hd_boot(idx):
            Rb = R[idx]
            v = []
            for a in range(len(idx)):
                for b in range(a + 1, len(idx)):
                    if idx[a] != idx[b]:
                        v.append(np.nanmean(Rb[a] != Rb[b]))
            return np.mean(v) if v else np.nan
        lo, hi, _ = bootstrap(hd_boot, N, min(B, 500), rng)
        out["inter_hd_chip_boot_ci"] = [lo, hi]
        out["inter_hd_hist"] = hds.tolist()
    # intra-chip reliability (BER of each repeat vs the majority reference)
    ber = {c: float(np.nanmean(reps[c] != ref[c][None, :])) for c in chips}
    out["intra_ber"] = ber
    out["intra_ber_mean"] = float(np.mean(list(ber.values())))
    out["reliability"] = 1 - out["intra_ber_mean"]
    unstable = {c: int(np.sum(np.nanmin(reps[c], 0) != np.nanmax(reps[c], 0))) for c in chips}
    out["unstable_bits"] = unstable
    out["intra_hd_hist"] = [float(np.nanmean(reps[c][r] != ref[c])) for c in chips for r in range(len(reps[c]))]
    if hot:
        hb = {c: float(np.nanmean(hot[c] != ref[c][None, :])) for c in hot if c in ref}
        out["hot_ber"] = hb
        out["hot_ber_mean"] = float(np.mean(list(hb.values())))
    # bit aliasing
    alias = np.nanmean(R, 0)
    out["bit_aliasing"] = alias.tolist()
    out["bit_aliasing_ci"] = [clopper_pearson(int(round(a * N)), N) for a in alias]
    h = -np.log2(np.maximum(alias, 1 - alias))
    out["min_entropy_bits"] = float(np.nansum(h))
    out["min_entropy_per_bit"] = float(np.nanmean(h))
    # expected min-entropy per bit for an IDEAL p=0.5 source at this N (small-N bias)
    ks = np.arange(N + 1)
    pk = stats.binom.pmf(ks, N, 0.5)
    out["min_entropy_ideal_at_N"] = float(np.sum(pk * -np.log2(np.maximum(ks, N - ks) / N)))
    # expectations under the model
    sd_delta = math.sqrt(2) * sigma_wid
    sr = math.sqrt(2) * sigma_rep
    out["expected"] = {"uniformity": 0.5, "inter_hd": 0.5, "bit_aliasing": 0.5,
                       "intra_ber_upper": float(math.atan(sr / sd_delta) / math.pi) if sd_delta > 0 else np.nan,
                       "note": "BER expectation = (1/pi) atan(sigma_noise/sigma_mismatch) for "
                               "Gaussian pair mismatch; uses the ring repeatability as an upper "
                               "bound on pair noise (common-mode noise cancels in simultaneous pairs)."}
    # pair ratio spread -> sigma_wid cross-check
    pp = df[(df.test == "puf_pair") & df.valid & (df.stage == 4)]
    if len(pp):
        adj = pp[pp["item"].isin([f"R{i:02d}-R{j:02d}" for i, j in PUF_PAIRS])]
        v = np.log1p(adj["y"].astype(float))
        out["pair_ratio_sd"] = float(v.std(ddof=1)) if len(v) > 1 else np.nan
        out["sigma_wid_from_pairs"] = out["pair_ratio_sd"] / math.sqrt(2)
    return out


# ======================================================================================
# (h) predicted vs measured
# ======================================================================================
def compare_predictions(pred: dict, pcm: pd.DataFrame, rs: pd.DataFrame, chain: dict,
                        temps: pd.Series, model: dict, B: int, rng) -> pd.DataFrame:
    rows = []
    tf = {c: temp_factor(model, temp_or_prior(model, temps.get(c, np.nan))[0]) for c in pcm.index}
    ch = chain["per_chip"] if chain else pd.DataFrame()
    for item, p in pred.items():
        if "tt" not in p:
            continue
        if item == "INV":
            meas = pcm["f_inv_mean"] * pd.Series(tf)
        elif item in TAP_ITEMS:
            col = "fmax_" + item
            if col not in ch:
                continue
            mid = (ch[col] + ch["fmax_fail_" + item].replace(np.inf, np.nan)) / 2
            meas = mid * pd.Series(tf)
        else:
            s = rs[rs["item"] == item].set_index("chip")["f"]
            meas = s * pd.Series(tf).reindex(s.index)
        meas = meas.dropna()
        if not len(meas):
            continue
        r = (meas / p["tt"]).values
        lo_b, hi_b = p.get("lo", p.get("ss")), p.get("hi", p.get("ff"))
        lo, hi, _ = bootstrap(lambda i: np.median(r[i]), len(r), B, rng)
        rows.append({"item": item, "n": len(r), "pred_tt": p["tt"], "meas_median": float(np.median(meas)),
                     "ratio_median": float(np.median(r)), "ratio_ci": [lo, hi],
                     "ratio_sd": float(np.std(r, ddof=1)) if len(r) > 1 else np.nan,
                     "band_lo_rel": lo_b / p["tt"] if lo_b else np.nan,
                     "band_hi_rel": hi_b / p["tt"] if hi_b else np.nan,
                     "frac_in_band": float(np.mean((meas >= lo_b) & (meas <= hi_b))) if lo_b and hi_b else np.nan,
                     "values_rel": r.tolist()})
    return pd.DataFrame(rows).set_index("item") if rows else pd.DataFrame()


# ======================================================================================
# Orchestration
# ======================================================================================
def analyze(csv_dir: str, placement_path: str | None = None, model_path: str | None = None,
            predictions_path: str | None = None, bins: dict | None = None,
            B: int = 1000, seed: int = 0, fmax_bin_tap: str = "T7") -> dict:
    """Run the full pipeline. Returns a dict of results (DataFrames + scalars)."""
    rng = np.random.default_rng(seed)
    model = load_model(model_path)
    placement, placeholder, pnotes = load_placement(placement_path)
    pop = load_population(csv_dir)
    screen_rows(pop, model)
    R = {"model": model, "placement": placement, "placement_placeholder": placeholder,
         "placement_notes": pnotes, "pop": pop, "csv_dir": csv_dir}
    fstat = functional_status(pop)
    rs = ring_summary(pop, 2)
    temps = chip_temperature(pop, model)
    R.update(functional=fstat, ring_summary=rs, temps=temps)
    R["completeness"] = completeness_table(pop, fstat, rs)
    pcm = per_chip_metrics(rs, temps, model)
    wd = within_die(rs, placement, B, rng)
    R["within_die"] = wd
    # R6 chip-level screen
    lnm = np.log(pcm["f_inv_mean_25C"].dropna())
    if len(lnm) >= 4:
        mad = 1.4826 * np.median(np.abs(lnm - lnm.median()))
        z = (lnm - lnm.median()) / mad if mad > 0 else lnm * 0
        R["chip_outliers"] = z[np.abs(z) > 4].to_dict()
        R["chip_robust_z"] = z.to_dict()
    else:
        R["chip_outliers"], R["chip_robust_z"] = {}, {}
    chain = chain_analysis(pop, rs, model, B, rng)
    R["chain"] = chain
    npk = np_skew(rs, wd, chain["per_chip"], temps, placement, model, B, rng)
    R["np"] = npk
    pcm = pcm.join(chain["per_chip"][[c for c in chain["per_chip"].columns if c.startswith(("t_stage", "t_ov", "fmax_T"))]], how="left")
    R["per_chip"] = pcm
    R["inv_spread"] = sigma_d2d_from_inv(pcm, npk.get("rho", np.nan) if npk.get("ok") else np.nan, B, rng)
    if R["chip_outliers"]:
        keep = pcm.drop(index=list(R["chip_outliers"]))
        R["inv_spread_no_outliers"] = sigma_d2d_from_inv(keep, npk.get("rho", 0.0), B, rng)
    d2d = {}
    for col, lab in (("f_inv_mean", "INV ring (mean of 16)"), ("f_inv_mean_25C", "INV ring @25C"),
                     ("f_nand", "NAND ring"), ("f_nor", "NOR ring"), ("f_fo4", "FO4 ring"),
                     ("t_stage", "chain stage delay (Fmax fit)"), ("t_stage_dch", "chain stage delay (DCH ring)"),
                     ("t_ov", "Fmax overhead t_ov"), ("fmax_" + fmax_bin_tap, f"Fmax {fmax_bin_tap}")):
        if col in pcm and pcm[col].notna().sum() >= 2:
            d2d[col] = {"label": lab, **pop_summary(pcm[col].values, B, rng)}
    R["d2d"] = d2d
    # gauge + bins
    grr = grr_ring(pop, model, temps)
    R["grr_ring"] = grr
    R["grr_fmax"] = grr_fmax(chain, pop, fmax_bin_tap)
    bins = bins or DEFAULT_BINS
    pred = None
    if predictions_path:
        with open(predictions_path, encoding="utf-8") as fh:
            pred = json.load(fh)
    R["predictions"] = pred
    f_nom_inv = (pred or {}).get("INV", {}).get("tt", nominal_freq(model, "INV"))
    if grr:
        R["bins_ring"] = speed_bins(pcm["f_inv_mean_25C"], f_nom_inv, grr["gauge+temp"]["sigma_ms"],
                                    fstat["functional_pass"], bins, B, rng)
    if R["grr_fmax"]:
        S = model["structures"]["DLY"]
        k = int(fmax_bin_tap[1:])
        f_nom_t = (pred or {}).get(fmax_bin_tap, {}).get(
            "tt", 1 / ((model["t_mux_ns"] + model["tap_stages"][k] * S["d0_ns"] + model["t_ov0_ns"]) * 1e-9))
        tf = pd.Series({c: temp_factor(model, temp_or_prior(model, temps.get(c, np.nan))[0]) for c in pcm.index})
        # Fmax path: chain stages scale with T, flop overhead assumed not to (model); approximate
        # the correction with the chain share of the path delay.
        share = 1 - (model["t_ov0_ns"] + model["t_mux_ns"]) / (model["t_mux_ns"] + model["tap_stages"][k] * S["d0_ns"] + model["t_ov0_ns"])
        fcorr = pcm["fmax_" + fmax_bin_tap] * (1 + (tf - 1) * share)
        sms = math.sqrt(R["grr_fmax"]["sigma_ms"] ** 2 + (share * model["temp_coeff_per_C"] * model["temp_proxy_sigma_C"]) ** 2)
        R["bins_fmax"] = speed_bins(fcorr, f_nom_t, sms, fstat["functional_pass"], bins, B, rng)
        R["bins_fmax"]["tap"] = fmax_bin_tap
    sig_rep = grr.get("sigma_repeat", 2e-4) * math.sqrt(16) if grr else 3e-4
    R["puf"] = puf_analysis(pop, wd.get("sigma_wid", 0.008) if wd.get("ok") else 0.008,
                            _ring_repeat_sigma(rs), B, rng)
    if pred:
        R["pred_cmp"] = compare_predictions(pred, pcm, rs, chain, temps, model, B, rng)
    R["stage5"] = stage5_temperature(pop, model)
    R["limitations"] = limitations(R)
    return R


def _ring_repeat_sigma(rs: pd.DataFrame) -> float:
    v = rs.loc[rs["item"].isin(INV_ITEMS), "sd_ln"].dropna()
    return float(np.sqrt(np.mean(v ** 2))) if len(v) else 3e-4


def stage5_temperature(pop: Population, model: dict) -> dict:
    """If Stage 5 re-measured INV rings at a different temperature, estimate the
    temperature coefficient of delay from d ln f / d T (per chip, then pooled)."""
    df = pop.rows
    d5 = df[(df.test == "ring") & (df.stage == 5) & df.valid & df["item"].isin(INV_ITEMS)]
    if not len(d5):
        return {}
    d2 = df[(df.test == "ring") & (df.stage == 2) & df.valid & df["item"].isin(INV_ITEMS)]
    rows = []
    for c, g5 in d5.groupby("chip_id"):
        g2 = d2[d2.chip_id == c]
        common = sorted(set(g5["item"]) & set(g2["item"]))
        if not common:
            continue
        l5 = np.log(g5[g5["item"].isin(common)].groupby("item")["y"].median()).mean()
        l2 = np.log(g2[g2["item"].isin(common)].groupby("item")["y"].median()).mean()
        T5 = g5["temp_c"].median()
        T2 = g2["temp_c"].median()
        if np.isfinite(T5) and np.isfinite(T2) and abs(T5 - T2) > 2:
            rows.append({"chip": c, "dT": T5 - T2, "dlnf": l5 - l2, "coef": -(l5 - l2) / (T5 - T2)})
    if not rows:
        return {}
    t = pd.DataFrame(rows).set_index("chip")
    return {"per_chip": t, "temp_coeff": float(t["coef"].mean()),
            "temp_coeff_se": float(t["coef"].std(ddof=1) / math.sqrt(len(t))) if len(t) > 1 else np.nan,
            "model_coeff": model["temp_coeff_per_C"]}


# ======================================================================================
# (i) limitations at small N
# ======================================================================================
def limitations(R: dict) -> list[str]:
    L = []
    N = len(R["per_chip"])
    npk, wd = R.get("np", {}), R.get("within_die", {})
    if npk.get("ok"):
        s, (lo, hi) = npk["sigma_d2d"], npk["sigma_d2d_ci"]
        L.append(f"sigma_d2d = {s:.4f} with 90 % CI [{lo:.4f}, {hi:.4f}] -> relative CI width "
                 f"{(hi - lo) / s * 100:.0f} % at N = {N}. Normal-theory CI for a sd with N-1 dof "
                 f"spans -{(1 - sd_chi2_ci(1, max(N - 1, 1))[0]) * 100:.0f} % / +{(sd_chi2_ci(1, max(N - 1, 1))[1] - 1) * 100:.0f} %; "
                 "no estimator can do better than that with this many dies.")
        L.append(f"Per-die N/P skew: median 1-sigma uncertainty of s_n - s_p is {npk['median_se_delta']:.3f} "
                 f"versus a population spread of s_n - s_p of about sqrt(2(1-rho)) x sigma_d2d "
                 f"= {math.sqrt(2) * s:.3f} (rho=0). With one NAND and one NOR ring per die, "
                 "each ratio carries a full sigma_wid of mismatch, so individual dies can only be "
                 "placed coarsely on the N/P plot; the population cloud is informative, single points are not.")
    if wd.get("ok"):
        gt = wd["gradient_test"]
        L.append(f"Gradient detection: single-die gradient 1-sigma = {gt.get('se_single_die', np.nan):.4f} per unit "
                 f"coordinate (vs model sigma_g = 0.005). A COMMON gradient must exceed "
                 f"{gt.get('mde_common', np.nan):.4f} to be detected with 80 % power at alpha = 0.05 over {gt.get('n')} dies.")
        s, (lo, hi) = wd["sigma_wid"], wd["sigma_wid_ci"]
        L.append(f"sigma_wid = {s:.4f} [{lo:.4f}, {hi:.4f}] rests on {wd['dof']} residual dof, so it is the best-"
                 "determined variance component; it is still a single-process-lot number.")
        if R.get("placement_placeholder"):
            L.append("Placement is a PLACEHOLDER: gradient directions and magnitudes are in placeholder "
                     "coordinates. Re-run with --placement from tools/place_extract.py before any layout conclusion.")
    b = R.get("bins_ring")
    if b:
        y = b["yield"]
        worst = max((v[1] - v[0]) for v in y["bin_gb_ci"] if np.isfinite(v[0]))
        L.append(f"Bin yields are counts out of {N} dies: the widest Clopper-Pearson 90 % interval is "
                 f"{worst * 100:.0f} percentage points wide. The normal-model yields are tighter but assume normality "
                 "(check the probability plots).")
    p = R.get("puf", {})
    if p.get("ok"):
        n = p["n_chips"]
        L.append(f"PUF: {n * (n - 1) // 2} chip pairs but only {n} independent dies. The naive binomial CI on "
                 f"inter-chip HD {fmt_ci(p.get('inter_hd_naive_ci'))} treats pairs as independent; the chip-bootstrap "
                 f"CI {fmt_ci(p.get('inter_hd_chip_boot_ci'))} is the honest one.")
        L.append(f"Min-entropy per bit from bit-aliasing is biased low at small N: even an ideal p=0.5 source gives "
                 f"{p['min_entropy_ideal_at_N']:.2f} bit/bit at N = {n} (measured {p['min_entropy_per_bit']:.2f}). "
                 "Report the ratio to the ideal, not the raw value. 16 bits cannot demonstrate uniqueness at scale.")
    ch = R.get("chain", {})
    if "pop_t_stage" in ch:
        t = ch["per_chip"]
        L.append(f"Fmax resolution: median PWM step is {np.nanmedian(t['fmax_rel_step']) * 100:.2f} % of Fmax; "
                 "the censored fit recovers stage delay far below the step because 8 taps are fitted jointly, "
                 "but any single-tap Fmax is only known to within one step.")
    if R.get("temps") is not None:
        L.append("Temperature correction uses the RP2350 core-temperature proxy with an assumed 1-sigma "
                 "error of 1 C; if the board sensor offset is larger, absolute speed (s_n + s_p) and bin "
                 "edges inherit 0.15 %/C of error. Differences (s_n - s_p, within-die) are immune.")
    return L


def fmt_ci(ci, f="{:.3f}"):
    if ci is None or len(ci) != 2 or not all(np.isfinite(ci)):
        return "[n/a]"
    return "[" + f.format(ci[0]) + ", " + f.format(ci[1]) + "]"


# ======================================================================================
# (j) validation against truth
# ======================================================================================
TARGETS = {
    "sigma_d2d": ("rel", 0.35),
    "sigma_wid": ("rel", 0.25),
    "delta": ("abs", 0.01),
    "t_stage": ("rel", 0.02),
}


def load_truth(truth_dir: str) -> tuple[dict, dict]:
    chips = {}
    for f in glob.glob(os.path.join(truth_dir, "truth_*.json")):
        with open(f, encoding="utf-8") as fh:
            t = json.load(fh)
        chips[t["chip_id"]] = t
    pop = {}
    pf = os.path.join(truth_dir, "population_truth.json")
    if os.path.exists(pf):
        with open(pf, encoding="utf-8") as fh:
            pop = json.load(fh)
    elif chips:
        pop = next(iter(chips.values())).get("model", {})
    return chips, pop


def validate_against_truth(R: dict, truth_dir: str) -> dict:
    """Compare every recovered parameter with injected truth. Returns tables + PASS/FAIL."""
    chips, popt = load_truth(truth_dir)
    rows_pop, rows_chip = [], []

    def add_pop(name, est, ci, truth, unit, target=None, truth_sample=None):
        err = est - truth
        rel = err / truth if truth else np.nan
        cov = bool(ci[0] <= truth <= ci[1]) if ci and all(np.isfinite(ci)) else None
        passed = None
        if target:
            kind, b = target
            passed = bool(abs(rel if kind == "rel" else err) <= b)
        rows_pop.append({"parameter": name, "estimate": est, "ci_lo": ci[0] if ci else np.nan,
                         "ci_hi": ci[1] if ci else np.nan, "truth": truth, "truth_sample": truth_sample,
                         "error": err, "rel_error": rel, "ci_covers": cov,
                         "target": (f"+/-{target[1] * 100:.0f} %" if target and target[0] == "rel" else
                                    f"+/-{target[1]}" if target else ""),
                         "pass": passed, "unit": unit})

    npk, wd, ch = R.get("np", {}), R.get("within_die", {}), R.get("chain", {})
    samp = popt.get("sample", {})
    if npk.get("ok"):
        add_pop("sigma_d2d (N/P GLS, MoM)", npk["sigma_d2d"], npk["sigma_d2d_ci"], popt["sigma_d2d"], "1",
                TARGETS["sigma_d2d"], samp.get("sigma_d2d_pooled"))
        add_pop("rho(s_n, s_p)", npk["rho"], npk["rho_ci"], popt.get("rho", 0.0), "1")
    inv = R.get("inv_spread", {})
    if inv:
        exp_inv = popt["sigma_d2d"] * math.sqrt((1 + popt.get("rho", 0)) / 2)
        add_pop("sigma(ln f_INV) @25C", inv["sigma_inv_lnf"], inv["sigma_inv_ci"], exp_inv, "1")
        add_pop("sigma_d2d implied by INV spread", inv["sigma_d2d_implied"], inv["sigma_d2d_implied_ci"],
                popt["sigma_d2d"], "1", TARGETS["sigma_d2d"], samp.get("sigma_d2d_pooled"))
    if wd.get("ok"):
        add_pop("sigma_wid", wd["sigma_wid"], wd["sigma_wid_ci"], popt["sigma_wid"], "1",
                TARGETS["sigma_wid"], samp.get("sigma_wid_inv_rings"))
    per_np = npk.get("per_chip") if npk.get("ok") else None
    per_wd = wd.get("per_chip") if wd.get("ok") else None
    per_ch = ch.get("per_chip")
    for c, t in chips.items():
        def add(name, est, se, truth, unit, target=None):
            if est is None or not np.isfinite(est):
                return
            err = est - truth
            ci = [est - Z90 * se, est + Z90 * se] if se is not None and np.isfinite(se) else [np.nan, np.nan]
            passed = None
            if target:
                kind, b = target
                passed = bool(abs(err / truth if kind == "rel" else err) <= b)
            rows_chip.append({"chip": c, "parameter": name, "estimate": est, "se": se, "truth": truth,
                              "error": err, "ci_covers": bool(ci[0] <= truth <= ci[1]) if np.isfinite(ci[0]) else None,
                              "pass": passed, "unit": unit})
        if per_np is not None and c in per_np.index:
            p = per_np.loc[c]
            add("s_n", p["s_n"], p["se_s_n"], t["s_n"], "1")
            add("s_p", p["s_p"], p["se_s_p"], t["s_p"], "1")
            add("s_n-s_p", p["delta"], p["se_delta"], t["s_n"] - t["s_p"], "1", TARGETS["delta"])
            add("s_n+s_p", p["sigma_sum"], p["se_sum"], t["s_n"] + t["s_p"], "1")
        if per_wd is not None and c in per_wd.index:
            p = per_wd.loc[c]
            add("g_x", p["g_x"], p["se_gx"], t["g_x"], "1/unit")
            add("g_y", p["g_y"], p["se_gy"], t["g_y"], "1/unit")
        if per_ch is not None and c in per_ch.index:
            p = per_ch.loc[c]
            if "t_stage" in p:
                add("t_stage (Fmax cens.)", p.get("t_stage"), p.get("se_t_stage"), t["t_stage_mean_s"], "s", TARGETS["t_stage"])
                add("t_stage (Fmax WLS mid)", p.get("t_stage_wls"), p.get("se_t_stage_wls"), t["t_stage_mean_s"], "s", TARGETS["t_stage"])
                add("t_ov", p.get("t_ov"), p.get("se_t_ov"), t["t_ov_s"], "s")
            if "t_stage_dch" in p:
                add("t_stage (DCH ring)", p.get("t_stage_dch"), p.get("se_t_stage_dch"), t["t_stage_mean_s"], "s", TARGETS["t_stage"])
    pc = pd.DataFrame(rows_chip)
    pp = pd.DataFrame(rows_pop)
    summ = []
    if len(pc):
        for name, g in pc.groupby("parameter", sort=False):
            e = g["error"].values
            summ.append({"parameter": name, "n": len(g), "bias": float(e.mean()), "rmse": float(np.sqrt(np.mean(e ** 2))),
                         "max_abs": float(np.max(np.abs(e))),
                         "rel_rmse": float(np.sqrt(np.mean((e / g["truth"].values) ** 2))) if name.startswith(("t_", "t_ov")) else np.nan,
                         "ci90_coverage": float(g["ci_covers"].dropna().mean()) if g["ci_covers"].notna().any() else np.nan,
                         "pass_frac": float(g["pass"].dropna().mean()) if g["pass"].notna().any() else np.nan})
    # PUF: majority bits vs noise-free truth
    puf = R.get("puf", {})
    if puf.get("ok"):
        wrong = [int(np.sum(np.array(puf["bits"][i]) != np.array(chips[c]["puf_bits_true"])))
                 for i, c in enumerate(puf["chips"]) if c in chips]
        tb = np.array([chips[c]["puf_bits_true"] for c in puf["chips"] if c in chips])
        if len(tb):
            thd = [np.mean(tb[i] != tb[j]) for i in range(len(tb)) for j in range(i + 1, len(tb))]
            rows_pop.append({"parameter": "PUF majority bits wrong vs noise-free (total)", "estimate": sum(wrong),
                             "truth": 0, "error": sum(wrong), "unit": "bits", "pass": None})
            add_pop("PUF uniformity (mean)", puf["uniformity_mean"], puf.get("uniformity_ci", [np.nan, np.nan]),
                    float(tb.mean()), "1")
            if thd:
                add_pop("PUF inter-chip HD", puf["inter_hd_mean"], puf.get("inter_hd_chip_boot_ci", [np.nan] * 2),
                        float(np.mean(thd)), "1")
    pp = pd.DataFrame(rows_pop)
    sm = pd.DataFrame(summ)
    verdict = {}
    if len(pp):
        for _, r in pp.iterrows():
            if r.get("pass") is not None and r["target"]:
                verdict[r["parameter"]] = bool(r["pass"])
    if len(sm):
        for _, r in sm.iterrows():
            if np.isfinite(r["pass_frac"]):
                verdict[f"{r['parameter']} (>=90 % of dies within target)"] = bool(r["pass_frac"] >= 0.9)
    return {"population": pp, "per_chip": pc, "summary": sm, "verdict": verdict, "truth_pop": popt}


# ======================================================================================
# JSON export
# ======================================================================================
def to_jsonable(o):
    if isinstance(o, pd.DataFrame):
        return json.loads(o.reset_index().to_json(orient="records"))
    if isinstance(o, pd.Series):
        return json.loads(o.to_json())
    if isinstance(o, dict):
        return {str(k): to_jsonable(v) for k, v in o.items() if k not in ("pop", "fits")}
    if isinstance(o, (list, tuple)):
        return [to_jsonable(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.ndarray):
        return to_jsonable(o.tolist())
    return o
