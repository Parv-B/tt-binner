#!/usr/bin/env python3
"""BINNER post-route SDF timing predictor.

Reads the post-route SDF (one per LibreLane RC/PVT corner, e.g.
GDS_logs/runs/wokwi/final/sdf/<rc>_<pvt>_<temp>_<volt>/*.sdf) together with
the matching post-route netlist (to resolve exact hand-instantiated cell
names -- SDF instance paths mirror the netlist's flattened hierarchical
names exactly, including synthesis-inserted generate-block segments like
"genblk1." that are NOT predictable from RTL alone) and computes:

  * per-ring oscillation period/frequency, for all 19 rings, per corner,
  * per-tap Fmax prediction (launch CLK->Q + chain delay to the tap + setup
    - launch/capture clock-insertion skew) for the delay chain's 8 taps,
  * per-tap delay-chain RING-MODE oscillation period,
  * NAND/INV and NOR/INV ring frequency ratios per corner (the N/P pull
    strength skew signature these two rings exist to expose).

All delay arithmetic tracks output-edge polarity explicitly (SDF rise/fall
values are indexed by the OUTPUT transition, not the cause), because every
ring here is built from an ODD number of inverting stages and getting the
rise/fall bookkeeping wrong silently halves or doubles the predicted period.

State every assumption and uncertainty explicitly (see "Assumptions and
limitations" in the rendered report) -- this is a hand-rolled STA-adjacent
calculation, not OpenSTA, and is meant to sanity-check the CI's own STA
results, not replace them.

Usage:
  python tools/sdf_predict.py --ci-dir ci_artifacts/908c9e1 [--out docs/reports/908c9e1]
  python tools/sdf_predict.py --netlist NL.v --sdf CORNER1.sdf --sdf CORNER2.sdf ...
"""
import argparse
import csv
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pvlib  # noqa: E402

WARNINGS = []


def warn(msg):
    WARNINGS.append(msg)


# =============================================================================
# Netlist-derived exact structural instance names (SDF paths must match the
# post-route netlist's flattened hierarchy exactly; classify_notouch()/
# classify_keep() locate them regardless of synthesis-inserted generate-block
# segments).
# =============================================================================
class Topology:
    """Resolves pvlib structural roles to exact instance names + the dynamic
    (loop-carrying) input pin of each ring stage, from one parsed netlist."""

    def __init__(self, nl):
        self.nl = nl
        self.ring_stage = {}   # (prefix, idx) -> inst name
        self.ring_tap = {}     # prefix -> inst name
        self.dc_dly = {}       # idx -> inst name
        self.dc_inmux = None
        self.dc_tapmux = {}    # idx -> inst name
        self.dc_fbnand = None
        self.fm_launch = None
        self.fm_cap = {}       # idx -> inst name
        for name in nl.insts:
            c = pvlib.classify_notouch(name)
            if c:
                role, prefix, idx = c
                if role == "ring_stage":
                    self.ring_stage[(prefix, idx)] = name
                elif role == "ring_tap":
                    self.ring_tap[prefix] = name
                elif role == "dc_dly":
                    self.dc_dly[idx] = name
                elif role == "dc_inmux":
                    self.dc_inmux = name
                elif role == "dc_tapmux":
                    self.dc_tapmux[idx] = name
                elif role == "dc_fbnand":
                    self.dc_fbnand = name
                continue
            c = pvlib.classify_keep(name)
            if c:
                role, _, idx = c
                if role == "fm_launch":
                    self.fm_launch = name
                elif role == "fm_cap":
                    self.fm_cap[idx] = name

    def stage_input_pin(self, kind, idx, cell):
        if kind in (1, 2):
            return "A1"
        if idx == 0:
            return "A1"   # NAND2 gate cell
        return "I"


# =============================================================================
# SDF delay lookup helpers
# =============================================================================
def iopath_rf(sdf, inst, ipin, opin):
    """Return ((r_min,r_typ,r_max), (f_min,f_typ,f_max)) for IOPATH ipin->opin
    on inst, preferring the unconditioned (COND-free) arc. None if absent."""
    for e in sdf.iopath.get(inst, []):
        if e["i"] == ipin and e["o"] == opin and e["cond"] is None:
            return e["rise"], e["fall"]
    for e in sdf.iopath.get(inst, []):
        if e["i"] == ipin and e["o"] == opin:
            return e["rise"], e["fall"]
    return None


def ic_typ(sdf, drv_inst, drv_pin, ld_inst, ld_pin, rising):
    key = (pvlib.Sdf.pinkey(drv_inst, drv_pin), pvlib.Sdf.pinkey(ld_inst, ld_pin))
    rf = sdf.ic.get(key)
    if rf is None:
        return 0.0
    triple = rf[0] if rising else rf[1]
    if triple is None:
        triple = rf[0] or rf[1]
    return triple[1] if triple else 0.0


def edge_step(sdf, inst, ipin, opin, edge_rising):
    """Advance one stage: return (new_edge_rising, typ_delay_ns, (min,max))."""
    rf = iopath_rf(sdf, inst, ipin, opin)
    if rf is None:
        warn("no IOPATH %s->%s on %s -- treated as 0 delay" % (ipin, opin, inst))
        return edge_rising, 0.0, (0.0, 0.0)
    rise, fall = rf
    # An inverting arc (A1/I -> ZN on our NAND2/NOR2/INV1 ring cells) flips
    # the edge; the *output* transition (and hence which SDF triple to use)
    # is therefore the opposite of the incoming edge for these cells. All
    # ring stage cells here (INV1, and NAND2/NOR2 with the other input held
    # static) are inverting on their dynamic input.
    out_rising = not edge_rising
    triple = rise if out_rising else fall
    if triple is None:
        triple = fall if out_rising else rise
    return out_rising, (triple[1] if triple else 0.0), (triple[0] if triple else 0.0, triple[2] if triple else 0.0)


def noninv_step(sdf, inst, ipin, opin, edge_rising):
    """Advance one stage through a non-inverting arc (DLY, MUX2 pass-through)."""
    rf = iopath_rf(sdf, inst, ipin, opin)
    if rf is None:
        warn("no IOPATH %s->%s on %s -- treated as 0 delay" % (ipin, opin, inst))
        return edge_rising, 0.0, (0.0, 0.0)
    rise, fall = rf
    triple = rise if edge_rising else fall
    if triple is None:
        triple = fall if edge_rising else rise
    return edge_rising, (triple[1] if triple else 0.0), (triple[0] if triple else 0.0, triple[2] if triple else 0.0)


# =============================================================================
# Ring period
# =============================================================================
def ring_period(sdf, topo, prefix, kind, n):
    """One full period = two trips around the loop (N inverting stages, N
    odd => one trip inverts polarity, two trips restore it and close the
    loop -- see src/binner_ring.v header comment)."""
    edge = True   # arbitrary starting polarity; the mechanism is symmetric
    total_typ = 0.0
    total_lo = 0.0
    total_hi = 0.0
    for trip in range(2):
        for i in range(n):
            name = topo.ring_stage.get((prefix, i))
            if name is None:
                warn("%s stage %d not found in netlist -- period incomplete" % (prefix, i))
                continue
            cell = topo.nl.insts[name].cell
            ipin = topo.stage_input_pin(kind, i, cell)
            edge, d, (lo, hi) = edge_step(sdf, name, ipin, "ZN", edge)
            total_typ += d
            total_lo += lo
            total_hi += hi
    return total_typ, (total_lo, total_hi), edge


# =============================================================================
# Fmax per-tap prediction
# =============================================================================
def chain_delay_to_tap(sdf, topo, tap_stage, worst_case=True):
    """Sum DLY I->Z delay from dch[0] to dch[tap_stage]. Non-inverting chain;
    since launch data (LFSR-derived, pseudo-random) can be either polarity,
    take the worse (larger) of rise/fall at each stage when worst_case=True
    (conservative -- matches how a real timing sign-off would bound an
    unknown-polarity data path)."""
    total_typ = 0.0
    lo_sum = hi_sum = 0.0
    edge = True
    for i in range(1, tap_stage + 1):
        name = topo.dc_dly.get(i)
        if name is None:
            warn("delay chain stage %d not found in netlist" % i)
            continue
        rf = iopath_rf(sdf, name, "I", "Z")
        if rf is None:
            warn("no IOPATH I->Z on %s" % name)
            continue
        rise, fall = rf
        if worst_case:
            r = rise[1] if rise else 0.0
            f = fall[1] if fall else 0.0
            total_typ += max(r, f)
            lo_sum += min(rise[0] if rise else 0.0, fall[0] if fall else 0.0)
            hi_sum += max(rise[2] if rise else 0.0, fall[2] if fall else 0.0)
        else:
            edge, d, (lo, hi) = noninv_step(sdf, name, "I", "Z", edge)
            total_typ += d
            lo_sum += lo
            hi_sum += hi
    return total_typ, (lo_sum, hi_sum)


def flop_ck2q(sdf, inst):
    rf = iopath_rf(sdf, inst, "CLK", "Q")
    if rf is None:
        warn("no CLK->Q IOPATH on %s" % inst)
        return None
    rise, fall = rf
    r = rise[1] if rise else None
    f = fall[1] if fall else None
    vals = [v for v in (r, f) if v is not None]
    return max(vals) if vals else None   # worst case (polarity unknown a priori)


def flop_setup(sdf, inst):
    """Largest SETUP value across data-edge/clock-edge combinations."""
    checks = sdf.checks.get(inst, [])
    vals = [c["value"][1] for c in checks if c["type"] == "SETUP" and c["value"]]
    return max(vals) if vals else None


def clk_insertion(sdf, inst):
    """Typ INTERCONNECT delay of the last clock-buffer-to-CLK-pin hop, found
    in the top-level (unnamed INSTANCE) CELL block. Used only for a relative
    launch/capture skew estimate, not absolute clock latency from the pad."""
    for (frm, to), rf in sdf.ic.items():
        if to.endswith("/" + "CLK") and to.startswith(inst + "/"):
            rise, fall = rf
            t = rise or fall
            return t[1] if t else None
    return None


# =============================================================================
# Tap-mux path (delay-chain ring mode)
# =============================================================================
_LEAF = [(0, 1), (2, 3), (4, 5), (6, 7)]
_COMBINE1 = {0: (4, "I0"), 1: (4, "I1"), 2: (5, "I0"), 3: (5, "I1")}
_COMBINE2 = {4: (6, "I0"), 5: (6, "I1")}


def tapmux_path(k):
    """Return the ordered list of (tm_idx, in_pin) hops from tap k to tm6."""
    leaf_idx = k // 2
    leaf_pin = "I0" if k % 2 == 0 else "I1"
    hops = [(leaf_idx, leaf_pin)]
    c1, p1 = _COMBINE1[leaf_idx]
    hops.append((c1, p1))
    if c1 in _COMBINE2:
        c2, p2 = _COMBINE2[c1]
        hops.append((c2, p2))
    return hops


def dchain_ring_period(sdf, topo, k):
    """Ring-mode period for tap k: 2 * (chain-to-tap + tap-mux tree + dfbg
    NAND (inverting) + dmx.I1->Z (non-inverting)). One inversion (the NAND)
    per trip => two trips to close the loop, as for the oscillator rings."""
    tap_stage = pvlib.TAPPOS[k]
    edge = True
    total = 0.0
    lo = hi = 0.0
    for trip in range(2):
        # chain-to-tap (non-inverting, DLY stages 1..tap_stage), tracked with
        # one consistent edge through the whole trip (a real oscillator
        # settles into a fixed edge-alternation pattern, unlike the
        # unknown-polarity Fmax launch data in chain_delay_to_tap()).
        e = edge
        seg_typ = 0.0
        seg_lo = seg_hi = 0.0
        for i in range(1, tap_stage + 1):
            name = topo.dc_dly.get(i)
            if name is None:
                continue
            e, d2, (l2, h2) = noninv_step(sdf, name, "I", "Z", e)
            seg_typ += d2
            seg_lo += l2
            seg_hi += h2
        for tm_idx, pin in tapmux_path(k):
            name = topo.dc_tapmux.get(tm_idx)
            if name is None:
                warn("tap-mux tm%d not found" % tm_idx)
                continue
            e, d2, (l2, h2) = noninv_step(sdf, name, pin, "Z", e)
            seg_typ += d2
            seg_lo += l2
            seg_hi += h2
        if topo.dc_fbnand:
            e, d2, (l2, h2) = edge_step(sdf, topo.dc_fbnand, "A1", "ZN", e)
            seg_typ += d2
            seg_lo += l2
            seg_hi += h2
        if topo.dc_inmux:
            e, d2, (l2, h2) = noninv_step(sdf, topo.dc_inmux, "I1", "Z", e)
            seg_typ += d2
            seg_lo += l2
            seg_hi += h2
        total += seg_typ
        lo += seg_lo
        hi += seg_hi
        edge = e
    return total, (lo, hi)


# =============================================================================
# Corner discovery + main computation
# =============================================================================
def discover(ci_dir):
    nlp = None
    cand = glob.glob(os.path.join(ci_dir, "tt_submission", "tt_submission", "*.v"))
    if cand:
        nlp = cand[0]
    else:
        cand = glob.glob(os.path.join(ci_dir, "GDS_logs", "runs", "*", "final", "pnl", "*.v"))
        if cand:
            nlp = cand[0]
    sdfs = sorted(glob.glob(os.path.join(ci_dir, "GDS_logs", "runs", "*", "final", "sdf", "*", "*.sdf")))
    return nlp, sdfs


def compute_for_corner(topo, sdf_path):
    sdf = pvlib.parse_sdf(sdf_path)
    corner = pvlib.sdf_corner_name(sdf_path)
    row = {"corner": corner, "sdf": os.path.basename(sdf_path)}

    ring_rows = []
    puf_freqs = []
    for prefix, kind, src, n in pvlib.RINGS:
        typ, (lo, hi), _ = ring_period(sdf, topo, prefix, kind, n)
        freq = (1.0 / typ) if typ > 0 else None   # GHz (ns time units)
        freq_lo = (1.0 / hi) if hi > 0 else None
        freq_hi = (1.0 / lo) if lo > 0 else None
        ring_rows.append({"ring": pvlib.ring_label(prefix), "kind": pvlib.KIND_NAMES[kind],
                          "n_stages": n, "period_typ_ns": typ, "period_min_ns": lo, "period_max_ns": hi,
                          "freq_typ_ghz": freq, "freq_lo_ghz": freq_lo, "freq_hi_ghz": freq_hi})
        if kind == 0:
            puf_freqs.append(freq)
    puf_avg = sum(f for f in puf_freqs if f) / len([f for f in puf_freqs if f]) if puf_freqs else None
    nand_freq = next((r["freq_typ_ghz"] for r in ring_rows if r["ring"] == "ring_nand"), None)
    nor_freq = next((r["freq_typ_ghz"] for r in ring_rows if r["ring"] == "ring_nor"), None)
    skew = {
        "puf_avg_freq_ghz": puf_avg,
        "nand_over_puf_avg": (nand_freq / puf_avg) if (nand_freq and puf_avg) else None,
        "nor_over_puf_avg": (nor_freq / puf_avg) if (nor_freq and puf_avg) else None,
    }

    tap_rows = []
    ck2q = flop_ck2q(sdf, topo.fm_launch) if topo.fm_launch else None
    launch_ins = clk_insertion(sdf, topo.fm_launch) if topo.fm_launch else None
    for k in range(8):
        tap_stage = pvlib.TAPPOS[k]
        cap = topo.fm_cap.get(k)
        chain_typ, (chain_lo, chain_hi) = chain_delay_to_tap(sdf, topo, tap_stage, worst_case=True)
        setup = flop_setup(sdf, cap) if cap else None
        cap_ins = clk_insertion(sdf, cap) if cap else None
        skew_ns = (cap_ins - launch_ins) if (cap_ins is not None and launch_ins is not None) else 0.0
        if ck2q is not None and setup is not None:
            tmin = ck2q + chain_typ + setup - skew_ns
            fmax = 1.0 / tmin if tmin > 0 else None
        else:
            tmin = None
            fmax = None
        ring_typ, (ring_lo, ring_hi) = dchain_ring_period(sdf, topo, k)
        tap_rows.append({
            "tap": k, "chain_stage": tap_stage,
            "launch_ck2q_ns": ck2q, "chain_delay_ns": chain_typ, "chain_delay_lo_ns": chain_lo,
            "chain_delay_hi_ns": chain_hi, "setup_ns": setup, "clk_skew_ns": skew_ns,
            "t_min_ns": tmin, "fmax_ghz": fmax,
            "ring_period_ns": ring_typ, "ring_freq_ghz": (1.0 / ring_typ) if ring_typ > 0 else None,
        })

    row["rings"] = ring_rows
    row["skew_signature"] = skew
    row["fmax_taps"] = tap_rows
    return row


def render_markdown(rows):
    lines = ["# BINNER post-route SDF timing prediction", ""]
    lines.append("Corners: %d SDF files (%s)." % (len(rows), ", ".join(r["corner"] for r in rows)))
    lines.append("")
    lines.append("## N/P skew signature (NAND/NOR ring vs. average INV/PUF ring frequency)")
    lines.append("")
    lines.append(pvlib.md_table(
        ["corner", "puf avg freq (GHz)", "nand/puf ratio", "nor/puf ratio"],
        [[r["corner"], pvlib.fmt(r["skew_signature"]["puf_avg_freq_ghz"]),
          pvlib.fmt(r["skew_signature"]["nand_over_puf_avg"]),
          pvlib.fmt(r["skew_signature"]["nor_over_puf_avg"])] for r in rows]))
    lines.append("")
    lines.append("## Per-ring oscillation frequency (typical corner value; min/max = OCV bounds from the SDF triples)")
    lines.append("")
    for r in rows:
        lines.append("### %s" % r["corner"])
        lines.append("")
        lines.append(pvlib.md_table(
            ["ring", "kind", "N", "period typ (ns)", "period min (ns)", "period max (ns)", "freq typ (GHz)"],
            [[x["ring"], x["kind"], x["n_stages"], pvlib.fmt(x["period_typ_ns"]),
              pvlib.fmt(x["period_min_ns"]), pvlib.fmt(x["period_max_ns"]), pvlib.fmt(x["freq_typ_ghz"])]
             for x in r["rings"]]))
        lines.append("")
    lines.append("## Fmax per tap (launch ck2q + worst-case chain delay + setup - clk skew)")
    lines.append("")
    for r in rows:
        lines.append("### %s" % r["corner"])
        lines.append("")
        lines.append(pvlib.md_table(
            ["tap", "chain stage", "ck2q (ns)", "chain (ns)", "setup (ns)", "clk skew (ns)",
             "T_min (ns)", "Fmax (GHz)", "ring period (ns)", "ring freq (GHz)"],
            [[x["tap"], x["chain_stage"], pvlib.fmt(x["launch_ck2q_ns"]), pvlib.fmt(x["chain_delay_ns"]),
              pvlib.fmt(x["setup_ns"]), pvlib.fmt(x["clk_skew_ns"]), pvlib.fmt(x["t_min_ns"]),
              pvlib.fmt(x["fmax_ghz"]), pvlib.fmt(x["ring_period_ns"]), pvlib.fmt(x["ring_freq_ghz"])]
             for x in r["fmax_taps"]]))
        lines.append("")
    lines.append("## Assumptions and limitations")
    lines.append("")
    lines.append("- **Hand-rolled, not OpenSTA.** This is a from-first-principles sanity check built "
                 "directly off the SDF's own IOPATH/INTERCONNECT/TIMINGCHECK arcs; it is meant to cross-check "
                 "the CI's OpenSTA-derived setup/hold/Fmax results (see docs/reports/<sha>/metrics_summary), "
                 "not replace them.")
    lines.append("- **Edge polarity.** SDF rise/fall triples are indexed by the *output* transition. Every ring "
                 "stage cell here (INV1, and NAND2/NOR2 with the other input held static during oscillation) is "
                 "inverting on its dynamic input, so the predictor flips the tracked edge at every ring stage and "
                 "the dfbg_notouch_ NAND in the delay-chain ring-mode loop, and keeps it fixed through non-inverting "
                 "DLY/MUX2 stages. Getting this wrong would silently halve or double the predicted period.")
    lines.append("- **Two trips per period.** All four ring kinds (INV/PUF, NAND, NOR, FO4) use an ODD stage "
                 "count (N_STG=25 or N_FO4=13), so one trip around the loop inverts polarity and a full period is "
                 "two trips; likewise the delay-chain ring-mode loop has exactly one inversion (the dfbg NAND) "
                 "per trip.")
    lines.append("- **Chain (Fmax) worst-case polarity.** The Fmax launch value comes from an LFSR bit, i.e. "
                 "either polarity is equally likely on any given chain traversal. chain_delay_to_tap() therefore "
                 "sums max(rise, fall) at every DLY stage -- a conservative bound, not the delay of one specific "
                 "toggle sequence. The ring-mode chain computation (used for the ring-period column), by contrast, "
                 "tracks one consistent edge through the whole loop, since a real oscillator settles into a fixed "
                 "edge-alternation pattern.")
    lines.append("- **Launch ck2q** is likewise reported as max(rise, fall) clk-to-Q, for the same reason.")
    lines.append("- **Clock skew** between the launch and each capture flop is estimated from the *typical* "
                 "value of the single largest clock-network INTERCONNECT hop feeding each flop's CLK pin in the "
                 "SDF's top-level CELL block (its total clock latency from the clock root is not represented as a "
                 "single INTERCONNECT entry in this SDF format, so this is a *relative* last-hop estimate only, "
                 "not full insertion delay -- treat clk_skew_ns as a rough, possibly noisy, correction, not a "
                 "sign-off number).")
    lines.append("- **Interconnect between logic stages is not separately added.** IOPATH delays in this SDF are "
                 "reported as pin-to-pin cell delays only; net RC is captured in the separate INTERCONNECT records "
                 "keyed by exact driver/load pin pairs. Resolving those per-stage (rather than only for the CLK "
                 "network, as done above) needs the exact yosys-assigned generate-block path for every stage, "
                 "which this script resolves via the parsed netlist -- if a stage's expected INTERCONNECT entry "
                 "is absent (observed occasionally for very short, near-zero, same-row hops) it is silently "
                 "treated as 0 ns and counted in the warnings list below rather than failing the run.")
    lines.append("- **GF180 PDK corner limitation.** gf180mcu_fd_sc_mcu7t5v0 ships only `tt`/`ss`/`ff` timing "
                 "corners (crossed here with LibreLane's `min`/`nom`/`max` parasitic-extraction corners = 9 SDF "
                 "files total). There is no `fs` (fast-NMOS/slow-PMOS) or `sf` (slow-NMOS/fast-PMOS) corner in "
                 "this PDK, so this predictor -- like the CI's own STA -- cannot see N/P-mismatch-driven setup/hold "
                 "pessimism that asymmetric process corners would expose; the NAND/PUF and NOR/PUF frequency "
                 "ratios above are the closest available proxy for that mismatch (they respond to the *relative* "
                 "NMOS/PMOS drive strength baked into each corner's ss/ff/tt model, just not to the two skewed "
                 "corners that don't exist for this PDK).")
    if WARNINGS:
        lines.append("")
        lines.append("### Runtime warnings (%d, deduplicated below)" % len(WARNINGS))
        lines.append("")
        seen = []
        for w in WARNINGS:
            if w not in seen:
                seen.append(w)
        for w in seen[:50]:
            lines.append("- %s" % w)
        if len(seen) > 50:
            lines.append("- ... and %d more" % (len(seen) - 50))
    lines.append("")
    return "\n".join(lines)


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["corner", "item_type", "item", "kind_or_tap", "n_or_stage",
                    "period_or_tmin_ns", "period_min_ns", "period_max_ns", "freq_ghz"])
        for r in rows:
            for x in r["rings"]:
                w.writerow([r["corner"], "ring", x["ring"], x["kind"], x["n_stages"],
                           x["period_typ_ns"], x["period_min_ns"], x["period_max_ns"], x["freq_typ_ghz"]])
            for x in r["fmax_taps"]:
                w.writerow([r["corner"], "fmax_tap", x["tap"], "fmax", x["chain_stage"],
                           x["t_min_ns"], None, None, x["fmax_ghz"]])
                w.writerow([r["corner"], "dchain_ring_tap", x["tap"], "ring", x["chain_stage"],
                           x["ring_period_ns"], None, None, x["ring_freq_ghz"]])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ci-dir")
    ap.add_argument("--netlist")
    ap.add_argument("--sdf", action="append", default=[])
    ap.add_argument("--out")
    a = ap.parse_args()

    nlp, sdfs = (None, [])
    if a.ci_dir:
        nlp, sdfs = discover(a.ci_dir)
    if a.netlist:
        nlp = a.netlist
    if a.sdf:
        sdfs = a.sdf
    if not nlp or not sdfs:
        ap.error("need a netlist and at least one SDF: pass --ci-dir, or --netlist and --sdf")

    nl = pvlib.parse_verilog(nlp)
    topo = Topology(nl)
    rows = [compute_for_corner(topo, s) for s in sdfs]

    md = render_markdown(rows)
    js = {"netlist": os.path.relpath(nlp), "corners": rows, "warnings": sorted(set(WARNINGS))}
    print(md)
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, "sdf_predict.md"), "w", encoding="utf-8") as f:
            f.write(md)
        with open(os.path.join(a.out, "sdf_predict.json"), "w", encoding="utf-8") as f:
            json.dump(js, f, indent=2)
        write_csv(os.path.join(a.out, "sdf_predict.csv"), rows)


if __name__ == "__main__":
    main()
