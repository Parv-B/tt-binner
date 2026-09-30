# SPDX-FileCopyrightText: (c) 2026 Parv Bhadra
# SPDX-License-Identifier: Apache-2.0
"""Draws one simulated chip from docs/VARIATION_MODEL.md and turns it into
the RTL plusargs BINNER's behavioural models read (docs/SPEC.md section 8).

Uses only the standard library (random, math) -- this runs under the
cocotb/Icarus venv (CPython, WSL), not MicroPython, so it is a separate
module from bringup/binner_bringup.py.
"""

import math
import os
import random

# ---------------------------------------------------------------------------
# Ring/source structure table (docs/VARIATION_MODEL.md section "Structure
# delay factor"). NOTE (hard-part flag, see bringup/README.md): the
# variation-model table lists FO4 at 25 stages, but src/binner_ring.v uses
# localparam N_FO4 = 13 for KIND==3 -- the RTL is authoritative (SPEC.md
# says so explicitly), so FO4's stage count here is 13, not the doc table's
# 25. Using 25 would make the injected +RING18_HP_FS wrong by ~2x relative
# to what the ring actually loops through.
# ---------------------------------------------------------------------------
STRUCTS = {
    # name: (d0_ns_per_stage, w_n, w_p, n_stages)
    "INV": (0.100, 0.5, 0.5, 25),
    "NAND": (0.135, 0.7, 0.3, 25),
    "NOR": (0.160, 0.25, 0.75, 25),
    "FO4": (0.230, 0.5, 0.5, 13),  # RTL N_FO4, not the doc table's 25
}
DLY_D0_NS = 3.40
DLY_W_N = 0.5
DLY_W_P = 0.5
DLY_N_STAGES = 14
DCHAIN_OVH_NS = 0.6
SIGMA_D2D = 0.04
SIGMA_WID_RING = 0.008
SIGMA_WID_STAGE = 0.004
RHO_NP = 0.5
SIGMA_GRAD = 0.005
TEMP_LO, TEMP_HI = 22.0, 35.0


def ns_to_fs(ns):
    return int(round(ns * 1.0e6))


# ---------------------------------------------------------------------------
# placement: ring (x, y) in normalised [-1, 1] tile coordinates.
# docs/reports/<sha>/placement.csv (tools/place_extract.py) doesn't exist yet
# in this repo snapshot -- path is configurable via BINNER_PLACEMENT_CSV,
# checked at runtime, and we fall back to a deterministic placeholder grid
# so the variation model still has *something* physically coherent to draw
# g_x/g_y through. This is exactly the "use a placeholder ... if not
# available" instruction; swap in the real placement.csv once it exists,
# nothing else in this file needs to change.
# ---------------------------------------------------------------------------
def default_placement_csv_path():
    return os.environ.get(
        "BINNER_PLACEMENT_CSV",
        os.path.join(os.path.dirname(__file__), "..", "..", "docs", "reports",
                     "PLACEHOLDER_SHA", "placement.csv"),
    )


def load_placement(path=None):
    path = path or default_placement_csv_path()
    placement = {}
    if os.path.isfile(path):
        with open(path) as f:
            header = None
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(",")
                if header is None:
                    header = parts
                    continue
                row = dict(zip(header, parts))
                placement[row["name"]] = (float(row["x"]), float(row["y"]))
        return placement, True

    # Placeholder deterministic layout: 16 INV rings on a 4x4 grid spanning
    # the tile, NAND/NOR/FO4 along one edge, the delay chain centred.
    for i in range(16):
        col = i % 4
        row = i // 4
        x = -0.75 + col * 0.5
        y = -0.75 + row * 0.5
        placement["R%02d" % i] = (x, y)
    placement["NAND"] = (-0.5, 0.95)
    placement["NOR"] = (0.0, 0.95)
    placement["FO4"] = (0.5, 0.95)
    placement["DCHAIN"] = (0.0, -0.95)
    return placement, False


# ---------------------------------------------------------------------------
# per-chip draw
# ---------------------------------------------------------------------------
def draw_chip(seed, placement=None):
    rng = random.Random(seed)
    placement = placement or load_placement()[0]

    z1 = rng.gauss(0.0, 1.0)
    z2 = rng.gauss(0.0, 1.0)
    s_n = SIGMA_D2D * z1
    s_p = SIGMA_D2D * (RHO_NP * z1 + math.sqrt(max(0.0, 1.0 - RHO_NP * RHO_NP)) * z2)
    g_x = rng.gauss(0.0, SIGMA_GRAD)
    g_y = rng.gauss(0.0, SIGMA_GRAD)
    t_c = rng.uniform(TEMP_LO, TEMP_HI)
    t_ov_ns = 0.9 * (1.0 + 0.5 * (s_n + s_p) / 2.0)

    def scale(x, y, w_n, w_p):
        return (math.exp(-(w_n * s_n + w_p * s_p))
                * (1.0 + g_x * x + g_y * y)
                * (1.0 + 0.0015 * (t_c - 25.0)))

    truth = {
        "seed": seed, "s_n": s_n, "s_p": s_p, "g_x": g_x, "g_y": g_y,
        "T_c": t_c, "t_ov_ns": t_ov_ns, "rings": {}, "dchain": {},
    }
    plusargs = []

    # 16 identical INV rings
    d0, w_n, w_p, n = STRUCTS["INV"]
    for i in range(16):
        x, y = placement.get("R%02d" % i, (0.0, 0.0))
        eps = rng.gauss(0.0, SIGMA_WID_RING)
        d_ns = d0 * scale(x, y, w_n, w_p) * (1.0 + eps)
        hp_fs = ns_to_fs(n * d_ns)
        plusargs.append("+RING%d_HP_FS=%d" % (i, hp_fs))
        truth["rings"]["R%02d" % i] = {"x": x, "y": y, "eps": eps, "d_ns": d_ns, "hp_fs": hp_fs}

    # NAND=16, NOR=17, FO4=18
    for idx, name in ((16, "NAND"), (17, "NOR"), (18, "FO4")):
        d0, w_n, w_p, n = STRUCTS[name]
        x, y = placement.get(name, (0.0, 0.0))
        eps = rng.gauss(0.0, SIGMA_WID_RING)
        d_ns = d0 * scale(x, y, w_n, w_p) * (1.0 + eps)
        hp_fs = ns_to_fs(n * d_ns)
        plusargs.append("+RING%d_HP_FS=%d" % (idx, hp_fs))
        truth["rings"][name] = {"x": x, "y": y, "eps": eps, "d_ns": d_ns, "hp_fs": hp_fs}

    # delay chain: 14 stages + mux/NAND overhead
    x, y = placement.get("DCHAIN", (0.0, 0.0))
    stage_ns = []
    for i in range(1, DLY_N_STAGES + 1):
        eps = rng.gauss(0.0, SIGMA_WID_STAGE)
        d_ns = DLY_D0_NS * scale(x, y, DLY_W_N, DLY_W_P) * (1.0 + eps)
        stage_ns.append(d_ns)
        plusargs.append("+DSTG%d_FS=%d" % (i, ns_to_fs(d_ns)))
    ovh_eps = rng.gauss(0.0, SIGMA_WID_STAGE)
    ovh_ns = DCHAIN_OVH_NS * scale(x, y, DLY_W_N, DLY_W_P) * (1.0 + ovh_eps)
    plusargs.append("+DCHAIN_OVH_FS=%d" % ns_to_fs(ovh_ns))
    truth["dchain"] = {"x": x, "y": y, "stage_ns": stage_ns, "ovh_ns": ovh_ns}

    return truth, plusargs


def variation_for_sim_bridge(truth):
    """The subset of `truth` that ttboard._sim_bridge.core_temp() (and any
    future sim-side reporting) needs -- just T_c today."""
    return {"T_c": truth["T_c"]}
