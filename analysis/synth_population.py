#!/usr/bin/env python3
"""Fast pure-Python synthetic BINNER population generator.

Draws chips from the generative model in docs/VARIATION_MODEL.md and emits, per
chip, a schema-v1 CSV (docs/CSV_SCHEMA.md) as the bring-up script would, plus a
``truth_<chip>.json`` with every injected parameter. It exists so the analysis
pipeline can be developed and validated before silicon and before the RTL-level
virtual demo board populations are available.

What is modelled (all from VARIATION_MODEL.md unless marked EXTENSION):

* die-to-die N/P drive shifts (s_n, s_p) ~ N(0, 0.04), optional correlation rho;
* per-die linear gradient (g_x, g_y) ~ N(g_mean, 0.005) over normalised tile
  coordinates (placement from tools/place_extract.py CSV, else a placeholder);
* operating temperature T_c ~ U(22, 35) C, +0.15 %/C of delay;
* within-die random mismatch eps ~ N(0, 0.008) per ring, N(0, 0.004) per chain stage;
* t_ov = 0.9 ns * (1 + 0.5 (s_n+s_p)/2), 0.6 ns fixed mux overhead;
* counter measurement: counts = floor(f * GATE / f_clk + U(0,1)) -> +/-1 LSB,
  16-bit wrap (OVF), 0.02 % white per-measurement frequency noise per ring;
* EXTENSION: a common-mode per-measurement-slot factor (supply/temperature
  wander, default 0.02 %) shared by the two rings of a simultaneous pair. It
  cancels in a paired ratio -- which is exactly why PUF bits use simultaneous
  pairs -- but not between sequential measurements;
* Fmax: clock f = sysclk / (2 k), sysclk integer MHz in [48, 250], so the tested
  frequency set is discrete; per-tap binary search over that set with n trials
  per point; per-trial fail probability Phi((T_path - 1/f) / sigma_j) (EXTENSION:
  sigma_j = 20 ps timing noise band); a point fails if any trial fails;
* RP2350 core-temperature proxy = T_c + per-chip offset N(0, 1 C) + reading
  noise N(0, 0.3 C) (EXTENSION, the board sensor is not the TT die);
* optional Stage 5 hot re-test (T_c + dT) of the INV rings and PUF bits;
* optional fault injection (dead ring, OVF, TIMEOUT, SUSPECT, partial file,
  functional fail) to exercise the ingestion/screening logic.

Usage:
    python analysis/synth_population.py --n 20 --seed 1 --out sim_pop20
    python analysis/synth_population.py --n 20 --seed 1 --out d --faults --stage5 \
        --predictions d/predictions_synthetic.json
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
from dataclasses import dataclass, field

import numpy as np
from scipy.stats import norm

# --------------------------------------------------------------------------------------
# Model constants (docs/VARIATION_MODEL.md)
# --------------------------------------------------------------------------------------
STRUCT = {
    "INV": dict(d0=0.100e-9, wn=0.5, wp=0.5, stages=25),
    "NAND": dict(d0=0.135e-9, wn=0.7, wp=0.3, stages=25),
    "NOR": dict(d0=0.160e-9, wn=0.25, wp=0.75, stages=25),
    "FO4": dict(d0=0.230e-9, wn=0.5, wp=0.5, stages=25),
    "DLY": dict(d0=3.40e-9, wn=0.5, wp=0.5, stages=1),
}
TAP_STAGES = [3, 4, 5, 6, 8, 10, 12, 14]
N_CHAIN = 14
T_MUX = 0.6e-9
T_OV0 = 0.9e-9
TEMP_COEF = 0.0015
INV_ITEMS = [f"R{i:02d}" for i in range(16)]
PUF_PAIRS = [(2 * n, 2 * n + 1) for n in range(8)] + [(i, i + 8) for i in range(8)]
SCHEMA_VERSION = 1
SCRIPT_VERSION = "synth-1.0"


def default_placement() -> dict[str, tuple[float, float]]:
    """Placeholder placement (normalised tile coordinates in [-1, 1]).

    INV rings on a 4x4 grid (row-major R00..R15), NAND/NOR/FO4 along the top edge,
    the delay chain centroid along the bottom edge. Replace with the CSV produced by
    tools/place_extract.py (columns item,x_norm,y_norm) once the DEF exists.
    """
    p = {}
    grid = [-0.75, -0.25, 0.25, 0.75]
    for i in range(16):
        p[f"R{i:02d}"] = (grid[i % 4], grid[i // 4])
    p["NAND"] = (-0.6, 0.95)
    p["NOR"] = (0.0, 0.95)
    p["FO4"] = (0.6, 0.95)
    p["DCH"] = (0.0, -0.95)
    return p


def load_placement(path: str | None) -> tuple[dict[str, tuple[float, float]], bool]:
    """Return (placement, is_placeholder). Accepts item,x_norm,y_norm CSV."""
    if not path:
        return default_placement(), True
    p = default_placement()
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            p[r["item"].strip()] = (float(r["x_norm"]), float(r["y_norm"]))
    for alias in ("DCHAIN", "CHAIN", "DCH0"):
        if "DCH" not in p and alias in p:
            p["DCH"] = p[alias]
    return p, False


def achievable_freqs(f_lo=4e6, f_hi=125e6, s_min=48, s_max=250) -> np.ndarray:
    """All PWM-achievable clocks f = sysclk / (2k), sysclk in integer MHz steps."""
    out = set()
    for s in range(s_min, s_max + 1):
        k = 1
        while True:
            f = s * 1e6 / (2 * k)
            if f < f_lo:
                break
            if f <= f_hi:
                out.add(round(f, 3))
            k += 1
    return np.array(sorted(out))


def lfsr_steps(n: int, seed: int = 0xACE1) -> int:
    q = seed
    for _ in range(n):
        fb = ((q >> 15) ^ (q >> 14) ^ (q >> 12) ^ (q >> 3)) & 1
        fb ^= int((q & 0x7FFF) == 0)
        q = ((q << 1) & 0xFFFF) | fb
    return q


@dataclass
class SynthConfig:
    n: int = 20
    seed: int = 1
    sigma_d2d: float = 0.04
    rho: float = 0.0
    sigma_g: float = 0.005
    g_mean: tuple[float, float] = (0.0, 0.0)
    temp_range: tuple[float, float] = (22.0, 35.0)
    sigma_wid: float = 0.008
    sigma_wid_chain: float = 0.004
    white: float = 2e-4
    common_mode: float = 2e-4
    fmax_jitter: float = 20e-12
    temp_proxy_offset: float = 1.0
    temp_proxy_noise: float = 0.3
    f_clk_ring: float = 10e6
    target_count: int = 50000
    ring_reps: int = 3
    fmax_reps: int = 2
    fmax_trials: int = 3
    puf_reps: int = 11
    stage5: bool = False
    stage5_dT: float = 15.0
    faults: bool = False
    placement: dict = field(default_factory=default_placement)
    placement_is_placeholder: bool = True
    freqs: np.ndarray = field(default_factory=achievable_freqs)


# --------------------------------------------------------------------------------------
# Chip draw
# --------------------------------------------------------------------------------------
def draw_chip(cfg: SynthConfig, rng: np.random.Generator, chip_id: str) -> dict:
    cov = cfg.sigma_d2d ** 2 * np.array([[1, cfg.rho], [cfg.rho, 1]])
    s_n, s_p = rng.multivariate_normal([0, 0], cov)
    g_x = rng.normal(cfg.g_mean[0], cfg.sigma_g)
    g_y = rng.normal(cfg.g_mean[1], cfg.sigma_g)
    T_c = rng.uniform(*cfg.temp_range)
    t_ov = T_OV0 * (1 + 0.5 * (s_n + s_p) / 2)
    pl = cfg.placement

    def dfac(kind, item, T):
        st = STRUCT[kind]
        x, y = pl[item]
        return (st["d0"] * math.exp(-(st["wn"] * s_n + st["wp"] * s_p))
                * (1 + g_x * x + g_y * y) * (1 + TEMP_COEF * (T - 25.0)))

    rings, eps = {}, {}
    kinds = {**{r: "INV" for r in INV_ITEMS}, "NAND": "NAND", "NOR": "NOR", "FO4": "FO4"}
    for item, kind in kinds.items():
        e = rng.normal(0, cfg.sigma_wid)
        eps[item] = e
        d = dfac(kind, item, T_c) * (1 + e)
        rings[item] = 1.0 / (2 * STRUCT[kind]["stages"] * d)
    eps_chain = rng.normal(0, cfg.sigma_wid_chain, N_CHAIN)
    d_stage = dfac("DLY", "DCH", T_c) * (1 + eps_chain)
    cum = np.cumsum(d_stage)
    D = np.array([T_MUX + cum[n - 1] for n in TAP_STAGES])
    fmax = 1.0 / (D + t_ov)
    for k in range(8):
        rings[f"DCH{k}"] = 1.0 / (2 * D[k])
    rings["CLK2"] = cfg.f_clk_ring / 2
    temp_offset = rng.normal(0, cfg.temp_proxy_offset)
    puf_bits = [int(rings[f"R{i:02d}"] > rings[f"R{j:02d}"]) for i, j in PUF_PAIRS]
    return dict(
        chip_id=chip_id, s_n=float(s_n), s_p=float(s_p), g_x=float(g_x), g_y=float(g_y),
        T_c=float(T_c), temp_proxy_offset=float(temp_offset), t_ov_s=float(t_ov),
        t_mux_s=T_MUX, eps=eps, eps_chain=eps_chain.tolist(), d_stage_s=d_stage.tolist(),
        t_stage_mean_s=float(d_stage.mean()), D_tap_s=D.tolist(), fmax_hz=fmax.tolist(),
        ring_hz=rings, puf_bits_true=puf_bits,
    )


# --------------------------------------------------------------------------------------
# Measurement simulation -> CSV rows
# --------------------------------------------------------------------------------------
class ChipWriter:
    def __init__(self, cfg: SynthConfig, rng: np.random.Generator, chip: dict):
        self.cfg, self.rng, self.chip = cfg, rng, chip
        self.rows: list[dict] = []
        self.t = 0.0
        self.run_id = f"{chip['chip_id']}-{1790000000 + int(rng.integers(0, 10**6))}"
        self.fingerprint = ""
        self.T_now = chip["T_c"]
        self.temp_scale = 1.0  # delay scale relative to T_c (Stage 5 heating)

    def proxy_temp(self) -> float:
        return round(self.T_now + self.chip["temp_proxy_offset"]
                     + self.rng.normal(0, self.cfg.temp_proxy_noise), 2)

    def add(self, stage, test, item, rep, x, y, unit, aux="", flags=None, dt=0.01):
        self.t += dt
        fl = ["SIM"] + (flags or [])
        self.rows.append(dict(
            chip_id=self.chip["chip_id"], fingerprint=self.fingerprint if stage >= 4 else "",
            run_id=self.run_id, t_s=round(self.t, 3), stage=stage, test=test, item=item,
            rep=rep, x="" if x is None else x, y=y, unit=unit, aux=aux,
            temp_c=self.proxy_temp(), flags=";".join(fl)))

    def count(self, f_true, gate, cm):
        f = f_true * (1 + self.rng.normal(0, self.cfg.white)) * (1 + cm)
        c = math.floor(f * gate / self.cfg.f_clk_ring + self.rng.random())
        return c

    def gate_for(self, f_nom):
        return int(max(16, min(65535, self.cfg.target_count * self.cfg.f_clk_ring / f_nom)))

    def f_ring(self, item):
        f = self.chip["ring_hz"][item]
        return f if item == "CLK2" else f / self.temp_scale

    # ---- Stage 1
    def stage1(self, functional_fail=False):
        self.add(1, "id", "ID", 0, None, 1, "bool", "id0=0x42;id1=0x4E;ver=0x01")
        for reg in ("SCRATCH", "CTRL", "SRCA", "SRCB", "PINDIV", "GATE_L", "GATE_H", "DTAP", "DBG"):
            self.add(1, "readback", reg, 0, None, 1, "bool", "wr=0xA5;rd=0xA5")
        for n in (1, 1000):
            exp = lfsr_steps(n)
            sig = exp ^ (0x0010 if functional_fail and n == 1000 else 0)
            self.add(1, "lfsr_kat", f"N={n}", 0, n, int(sig == exp), "bool",
                     f"sig=0x{sig:04X};exp=0x{exp:04X}")
        gate = 1024
        cnt = gate // 2 + int(self.rng.integers(-1, 2))
        self.add(1, "clk2_kat", "CLK2", 0, gate, cnt, "count", f"exp={gate // 2}")
        for item in ("R00", "R08"):
            f = self.f_ring(item) * (1 + self.rng.normal(0, 0.002))
            self.add(1, "pinmode", item, 0, self.cfg.f_clk_ring, round(f, 1), "Hz",
                     "pindiv=5;window_ms=10", ["PINMODE"])

    # ---- Stage 2 (paired ring measurements)
    def measure_pair(self, a, b, rep, stage=2, fault=None):
        cm = self.rng.normal(0, self.cfg.common_mode)
        fa, fb = self.f_ring(a), self.f_ring(b)
        gate = self.gate_for(max(fa, fb))
        for item, other, ch, f in ((a, b, "A", fa), (b, a, "B", fb)):
            cnt = self.count(f, gate, cm)
            flags = []
            if fault and fault[0] == item:
                kind = fault[1]
                if kind == "dead":
                    cnt, flags = 0, ["NOSEEN"]
                elif kind == "ovf":
                    cnt += 70000  # force a wrap
                elif kind == "timeout":
                    flags = ["TIMEOUT"]
                elif kind == "suspect":
                    cnt, flags = int(cnt * 1.3), ["SUSPECT"]
            if cnt >= 65536:
                cnt %= 65536
                flags.append("OVF")
            y = cnt * self.cfg.f_clk_ring / gate
            self.add(stage, "ring", item, rep, self.cfg.f_clk_ring, round(y, 3), "Hz",
                     f"cnt={cnt};gate={gate};ch={ch};pair={other}", flags, dt=gate / self.cfg.f_clk_ring + 0.004)

    def stage2(self, faults: dict):
        for rep in range(self.cfg.ring_reps):
            pairs = [(f"R{i:02d}", f"R{i + 8:02d}") for i in range(8)]
            if rep % 2 == 1:
                pairs = [(b, a) for a, b in pairs]
            pairs += [("NAND", "NOR"), ("FO4", "CLK2")] + [(f"DCH{k}", "CLK2") for k in range(8)]
            for a, b in pairs:
                fault = None
                for item in (a, b):
                    fk = faults.get(item)
                    if fk and (fk[1] == "dead" or fk[2] == rep):
                        fault = (item, fk[1])
                self.measure_pair(a, b, rep, fault=fault)

    # ---- Stage 3 (Fmax)
    def stage3(self):
        cfg, freqs = self.cfg, self.cfg.freqs
        for k in range(8):
            self.add(3, "fmax_inv", f"T{k}", 0, 10e6, 1, "bool", "ffail=0xFF", dt=0.02)
        for rep in range(cfg.fmax_reps):
            for k in range(8):
                T_path = (self.chip["D_tap_s"][k] * self.temp_scale + self.chip["t_ov_s"])

                def test(f):
                    p = norm.cdf((T_path - 1.0 / f) / cfg.fmax_jitter)
                    fails = int((self.rng.random(cfg.fmax_trials) < p).sum())
                    frac = fails / cfg.fmax_trials
                    self.add(3, "fmax_pt", f"T{k}", rep, float(f), round(frac, 4), "frac",
                             f"trials={cfg.fmax_trials}", dt=0.05 * cfg.fmax_trials)
                    return fails > 0

                lo, hi = 0, len(freqs) - 1
                lo_fail = test(freqs[lo])
                hi_fail = test(freqs[hi])
                if lo_fail:
                    self.add(3, "fmax", f"T{k}", rep, None, "", "Hz",
                             f"f_fail={freqs[lo]:.3f};f_pass=", dt=0.001)
                    continue
                if not hi_fail:
                    self.add(3, "fmax", f"T{k}", rep, None, float(freqs[hi]), "Hz",
                             f"f_fail=;f_pass={freqs[hi]:.3f}", dt=0.001)
                    continue
                while hi - lo > 1:
                    mid = (lo + hi) // 2
                    if test(freqs[mid]):
                        hi = mid
                    else:
                        lo = mid
                self.add(3, "fmax", f"T{k}", rep, None, float(freqs[lo]), "Hz",
                         f"f_fail={freqs[hi]:.3f};f_pass={freqs[lo]:.3f}", dt=0.001)

    # ---- Stage 4 (PUF)
    def puf_measure(self, i, j):
        cm = self.rng.normal(0, self.cfg.common_mode)
        a, b = f"R{i:02d}", f"R{j:02d}"
        gate = self.gate_for(max(self.f_ring(a), self.f_ring(b)))
        ca = self.count(self.f_ring(a), gate, cm)
        cb = self.count(self.f_ring(b), gate, cm)
        return ca, cb, gate

    def stage4(self, stage=4, pair_ratios=True):
        bits = np.zeros((self.cfg.puf_reps, 16), dtype=int)
        raw = []
        if pair_ratios:
            for i in range(16):
                for j in range(i + 1, 16):
                    ca, cb, gate = self.puf_measure(i, j)
                    raw.append(ca > cb)
                    self.add(stage, "puf_pair", f"R{i:02d}-R{j:02d}", 0, None,
                             round(ca / cb - 1, 7), "ratio", f"ca={ca};cb={cb};gate={gate}",
                             dt=gate / self.cfg.f_clk_ring + 0.004)
        for rep in range(self.cfg.puf_reps):
            for n, (i, j) in enumerate(PUF_PAIRS):
                ca, cb, gate = self.puf_measure(i, j)
                bits[rep, n] = int(ca > cb)
        if stage == 4:
            maj = (bits.sum(0) * 2 > self.cfg.puf_reps).astype(int)
            word = int(sum(int(b) << n for n, b in enumerate(maj)))
            rawv = 0
            for n, b in enumerate(raw[:48]):
                rawv |= int(b) << n
            self.fingerprint = f"{word:04X}{rawv:012X}"
        for rep in range(self.cfg.puf_reps):
            for n, (i, j) in enumerate(PUF_PAIRS):
                self.add(stage, "puf_bit", f"b{n:02d}", rep, None, int(bits[rep, n]), "bit",
                         f"pair=R{i:02d}-R{j:02d}", dt=0.002)
        return bits

    # ---- Stage 5 (temperature)
    def stage5(self, hot: bool):
        self.add(5, "temp", "CORE", 0, None, self.proxy_temp(), "C")
        if not hot:
            return
        T_hot = self.chip["T_c"] + self.cfg.stage5_dT
        self.temp_scale = (1 + TEMP_COEF * (T_hot - 25)) / (1 + TEMP_COEF * (self.chip["T_c"] - 25))
        self.T_now = T_hot
        self.add(5, "temp", "CORE", 1, None, self.proxy_temp(), "C", dt=60.0)
        for i in range(8):
            self.measure_pair(f"R{i:02d}", f"R{i + 8:02d}", 0, stage=5)
        self.stage4(stage=5, pair_ratios=False)


def write_chip_csv(path: str, cfg: SynthConfig, w: ChipWriter):
    cols = ["chip_id", "fingerprint", "run_id", "t_s", "stage", "test", "item", "rep", "x", "y",
            "unit", "aux", "temp_c", "flags"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        fh.write(f"# schema_version={SCHEMA_VERSION}\n")
        fh.write(f"# script_version={SCRIPT_VERSION}\n")
        fh.write("# firmware_version=synthetic\n")
        fh.write("# board=synthetic-population (analysis/synth_population.py)\n")
        fh.write(f"# f_clk_ring_hz={cfg.f_clk_ring:.0f}\n")
        fh.write("# fmax_clock=sysclk/(2k), sysclk 48..250 MHz in 1 MHz steps\n")
        fh.write("# start_time=2026-09-29T00:00:00Z\n")
        # fingerprint is only known after Stage 4; the script back-fills nothing.
        wr = csv.DictWriter(fh, fieldnames=cols)
        wr.writeheader()
        for r in w.rows:
            wr.writerow(r)


def model_predictions(cfg: SynthConfig) -> dict:
    """Synthetic 'SDF-style' prediction bands from the nominal model at 25 C.

    tt: s_n=s_p=0; ss/ff: s_n=s_p=-/+3 sigma_d2d; lo/hi = ss/ff. Format:
    {item: {"tt": Hz, "ss": Hz, "ff": Hz, "lo": Hz, "hi": Hz}}.
    """
    out = {}
    for label, s in (("tt", 0.0), ("ss", -3 * cfg.sigma_d2d), ("ff", 3 * cfg.sigma_d2d)):
        for kind in ("INV", "NAND", "NOR", "FO4"):
            st = STRUCT[kind]
            d = st["d0"] * math.exp(-(st["wn"] + st["wp"]) * s)
            items = INV_ITEMS + ["INV"] if kind == "INV" else [kind]
            for it in items:
                out.setdefault(it, {})[label] = 1 / (2 * st["stages"] * d)
        dstage = STRUCT["DLY"]["d0"] * math.exp(-s)
        tov = T_OV0 * (1 + 0.5 * s)
        for k, n in enumerate(TAP_STAGES):
            D = T_MUX + n * dstage
            out.setdefault(f"DCH{k}", {})[label] = 1 / (2 * D)
            out.setdefault(f"T{k}", {})[label] = 1 / (D + tov)
    for v in out.values():
        v["lo"], v["hi"] = v["ss"], v["ff"]
    return out


def generate(cfg: SynthConfig, out_dir: str, write_truth: bool = True) -> list[dict]:
    os.makedirs(out_dir, exist_ok=True)
    rng = np.random.default_rng(cfg.seed)
    chips = []
    for c in range(cfg.n):
        chip_id = f"sim{c:02d}"
        chip = draw_chip(cfg, rng, chip_id)
        w = ChipWriter(cfg, rng, chip)
        faults, partial, ffail = {}, False, False
        if cfg.faults:
            # deterministic fault plan on specific chips (only if the population is big enough)
            plan = {3: {"R05": (None, "dead", None)}, 5: {"R02": (None, "ovf", 1)},
                    7: {"NOR": (None, "timeout", 0)}, 9: {"R10": (None, "suspect", 2)}}
            faults = {k: v for k, v in plan.get(c, {}).items()}
            partial = c == 11
            ffail = c == 13
        chip["injected_faults"] = {k: v[1] for k, v in faults.items()}
        chip["partial"] = partial
        chip["functional_fail"] = ffail
        w.stage1(functional_fail=ffail)
        w.stage2(faults)
        if not partial:
            w.stage3()
            w.stage4()
            w.stage5(hot=cfg.stage5)
        write_chip_csv(os.path.join(out_dir, f"binner_{chip_id}.csv"), cfg, w)
        chips.append(chip)
        if write_truth:
            t = {k: v for k, v in chip.items()}
            t["model"] = population_truth(cfg)
            with open(os.path.join(out_dir, f"truth_{chip_id}.json"), "w", encoding="utf-8") as fh:
                json.dump(t, fh, indent=1)
    if write_truth:
        pt = population_truth(cfg)
        arr = lambda k: np.array([ch[k] for ch in chips])
        eps = np.array([[ch["eps"][r] for r in INV_ITEMS] for ch in chips])
        pt["sample"] = {
            "sd_s_n": float(arr("s_n").std(ddof=1)), "sd_s_p": float(arr("s_p").std(ddof=1)),
            "sigma_d2d_pooled": float(np.sqrt((arr("s_n").var(ddof=1) + arr("s_p").var(ddof=1)) / 2)),
            "sigma_wid_inv_rings": float(np.sqrt(np.mean(np.log1p(eps) ** 2))),
        }
        with open(os.path.join(out_dir, "population_truth.json"), "w", encoding="utf-8") as fh:
            json.dump(pt, fh, indent=1)
    return chips


def population_truth(cfg: SynthConfig) -> dict:
    return dict(
        n=cfg.n, seed=cfg.seed, sigma_d2d=cfg.sigma_d2d, rho=cfg.rho, sigma_g=cfg.sigma_g,
        g_mean=list(cfg.g_mean), temp_range=list(cfg.temp_range), sigma_wid=cfg.sigma_wid,
        sigma_wid_chain=cfg.sigma_wid_chain, white=cfg.white, common_mode=cfg.common_mode,
        fmax_jitter_s=cfg.fmax_jitter, temp_coef=TEMP_COEF, t_mux_s=T_MUX, t_ov0_s=T_OV0,
        tap_stages=TAP_STAGES, placement={k: list(v) for k, v in cfg.placement.items()},
        placement_is_placeholder=cfg.placement_is_placeholder, stage5=cfg.stage5,
        stage5_dT=cfg.stage5_dT, faults=cfg.faults,
    )


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", required=True)
    ap.add_argument("--rho", type=float, default=0.0)
    ap.add_argument("--sigma-d2d", type=float, default=0.04)
    ap.add_argument("--sigma-wid", type=float, default=0.008)
    ap.add_argument("--g-mean", type=float, nargs=2, default=(0.0, 0.0),
                    help="common (layout-driven) gradient mean, per unit normalised coordinate")
    ap.add_argument("--placement", help="placement CSV (item,x_norm,y_norm); default placeholder")
    ap.add_argument("--stage5", action="store_true", help="add a hot Stage 5 re-test (T_c + 15 C)")
    ap.add_argument("--faults", action="store_true", help="inject screening test cases")
    ap.add_argument("--no-truth", action="store_true")
    ap.add_argument("--predictions", help="also write model-derived prediction bands JSON here")
    a = ap.parse_args(argv)
    pl, ph = load_placement(a.placement)
    cfg = SynthConfig(n=a.n, seed=a.seed, rho=a.rho, sigma_d2d=a.sigma_d2d, sigma_wid=a.sigma_wid,
                      g_mean=tuple(a.g_mean), stage5=a.stage5, faults=a.faults,
                      placement=pl, placement_is_placeholder=ph)
    generate(cfg, a.out, write_truth=not a.no_truth)
    if a.predictions:
        with open(a.predictions, "w", encoding="utf-8") as fh:
            json.dump(model_predictions(cfg), fh, indent=1)
    print(f"wrote {a.n} chips to {a.out}")


if __name__ == "__main__":
    main()
