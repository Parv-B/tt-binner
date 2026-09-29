#!/usr/bin/env python3
"""BINNER placement extractor: per-structure centroid/bbox from the final DEF,
normalized over the tile, plus a floorplan PNG.

Reads GDS_logs/runs/wokwi/final/def/<top>.def (LibreLane/OpenROAD DEF,
COMPONENTS with escaped hierarchical instance names, e.g.
"u_ring_nand.g_stg\\[0\\].g_nand.stg_notouch_"). Every component is grouped
into its structural "item" (one of the 16 PUF/INV rings, the NAND ring, the
NOR ring, the FO4 ring, the delay chain, or the Fmax flops) using the same
classify_notouch()/classify_keep() instance-name classifier as
tools/netlist_audit.py, so grouping is exact -- not a name-substring guess.

For each item: cell count, centroid (area-weighted by LEF/footprint size when
available, else unweighted over placed origins), axis-aligned bounding box,
in um and normalized to [-1, 1] over the die (346.64 x 160.72 um for this
TTGF26d 1x1 tile; the actual DIEAREA read from the DEF is used, and compared
against that nominal size in the report).

Usage:
  python tools/place_extract.py --ci-dir ci_artifacts/908c9e1 [--out docs/reports/908c9e1]
  python tools/place_extract.py --def PATH.def [--lef PATH.lef] [--out DIR]
"""
import argparse
import csv
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pvlib  # noqa: E402

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as patches
    HAVE_MPL = True
except ImportError:
    HAVE_MPL = False


def classify_component(name):
    c = pvlib.classify_notouch(name)
    if c:
        role, prefix, idx = c
        return ("ring", prefix) if role.startswith("ring_") else ("dchain", pvlib.DCHAIN)
    c = pvlib.classify_keep(name)
    if c:
        return ("fmax", pvlib.FMAX)
    return None


def item_label(kind, prefix):
    if kind == "ring":
        return pvlib.ring_label(prefix)
    return {"dchain": "delay_chain", "fmax": "fmax_flops"}[kind]


def extract(d, sizes):
    """d: pvlib.Def. sizes: {cell: (w_um, h_um)}. Returns list of item dicts."""
    groups = {}   # label -> list of (name, cell, x, y, w, h)  (x,y = LEF origin, um)
    for name, comp in d.comps.items():
        c = classify_component(name)
        if c is None:
            continue
        kind, prefix = c
        label = item_label(kind, prefix)
        if comp["x"] is None:
            continue   # UNPLACED -- shouldn't happen post-route, but be safe
        w, h = sizes.get(comp["cell"], (0.0, 0.0))
        groups.setdefault(label, []).append((name, comp["cell"], comp["x"], comp["y"], w, h))

    die = d.die or (0.0, 0.0, 346.64, 160.72)
    dx0, dy0, dx1, dy1 = die
    dw, dh = dx1 - dx0, dy1 - dy0

    def norm(x, span0, span):
        # map [span0, span0+span] -> [-1, 1]
        return 2.0 * (x - span0) / span - 1.0

    items = []
    for label in sorted(groups):
        cells = groups[label]
        n = len(cells)
        # area-weighted centroid over each cell's footprint center (x+w/2, y+h/2);
        # cells with unknown size (w=h=0, not in the LEF/BUILTIN_SIZES table)
        # fall back to their placement origin with zero weight contribution to
        # area but still count toward an unweighted centroid via max(area,1e-6).
        tot_area = 0.0
        cx = cy = 0.0
        x0 = y0 = float("inf")
        x1 = y1 = float("-inf")
        for name, cell, x, y, w, h in cells:
            ccx, ccy = x + w / 2.0, y + h / 2.0
            area = w * h if (w and h) else 1e-6
            cx += ccx * area
            cy += ccy * area
            tot_area += area
            x0, y0 = min(x0, x), min(y0, y)
            x1, y1 = max(x1, x + w), max(y1, y + h)
        cx /= tot_area
        cy /= tot_area
        cell_area_sum = sum((w * h) for _, _, _, _, w, h in cells if w and h)
        items.append({
            "item": label, "n_cells": n,
            "centroid_x_um": cx, "centroid_y_um": cy,
            "bbox_x0_um": x0, "bbox_y0_um": y0, "bbox_x1_um": x1, "bbox_y1_um": y1,
            "cell_area_um2": cell_area_sum,
            "x_norm": norm(cx, dx0, dw), "y_norm": norm(cy, dy0, dh),
            "bbox_x0_norm": norm(x0, dx0, dw), "bbox_y0_norm": norm(y0, dy0, dh),
            "bbox_x1_norm": norm(x1, dx0, dw), "bbox_y1_norm": norm(y1, dy0, dh),
        })
    return items, die


def write_csv(path, items):
    cols = ["item", "n_cells", "x_norm", "y_norm", "centroid_x_um", "centroid_y_um",
            "bbox_x0_um", "bbox_y0_um", "bbox_x1_um", "bbox_y1_um",
            "bbox_x0_norm", "bbox_y0_norm", "bbox_x1_norm", "bbox_y1_norm", "cell_area_um2"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for it in items:
            w.writerow(it)


def render_png(path, items, die):
    dx0, dy0, dx1, dy1 = die
    fig, ax = plt.subplots(figsize=(9, 4.5), dpi=150)
    ax.add_patch(patches.Rectangle((dx0, dy0), dx1 - dx0, dy1 - dy0, fill=False,
                                    edgecolor="black", linewidth=1.2, zorder=1))
    cmap = plt.get_cmap("tab20")
    puf_items = sorted([it for it in items if it["item"].startswith("puf")],
                        key=lambda it: int(it["item"][3:].strip("[]")) if it["item"][3:].strip("[]").isdigit() else it["item"])
    other_items = [it for it in items if not it["item"].startswith("puf")]
    ordered = puf_items + other_items
    for i, it in enumerate(ordered):
        color = cmap(i % 20)
        w = it["bbox_x1_um"] - it["bbox_x0_um"]
        h = it["bbox_y1_um"] - it["bbox_y0_um"]
        ax.add_patch(patches.Rectangle((it["bbox_x0_um"], it["bbox_y0_um"]), w, h,
                                        facecolor=color, edgecolor=color, alpha=0.35, zorder=2))
        ax.plot(it["centroid_x_um"], it["centroid_y_um"], marker="o", color=color,
                markersize=4, zorder=3)
        ax.annotate(it["item"], (it["centroid_x_um"], it["centroid_y_um"]),
                    fontsize=5, ha="center", va="bottom", zorder=4)
    ax.set_xlim(dx0 - 5, dx1 + 5)
    ax.set_ylim(dy0 - 5, dy1 + 5)
    ax.set_aspect("equal")
    ax.set_xlabel("x (um)")
    ax.set_ylabel("y (um)")
    ax.set_title("BINNER floorplan: ring / delay-chain / Fmax cell footprints (%.2f x %.2f um tile)" %
                 (dx1 - dx0, dy1 - dy0))
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def render_markdown(items, die, def_path, lef_path):
    dx0, dy0, dx1, dy1 = die
    lines = ["# BINNER placement extraction", ""]
    lines.append("- DEF: `%s`" % def_path)
    lines.append("- LEF (cell sizes): `%s`" % (lef_path or "none -- used tools/pvlib.py BUILTIN_SIZES"))
    lines.append("- DIEAREA: (%.4f, %.4f) - (%.4f, %.4f) um -> %.4f x %.4f um "
                 "(nominal TTGF26d 1x1 tile: 346.64 x 160.72 um)" %
                 (dx0, dy0, dx1, dy1, dx1 - dx0, dy1 - dy0))
    lines.append("")
    lines.append(pvlib.md_table(
        ["item", "n cells", "x_norm", "y_norm", "centroid (um)", "bbox (um)", "cell area (um^2)"],
        [[it["item"], it["n_cells"], pvlib.fmt(it["x_norm"]), pvlib.fmt(it["y_norm"]),
          "(%.2f, %.2f)" % (it["centroid_x_um"], it["centroid_y_um"]),
          "(%.1f,%.1f)-(%.1f,%.1f)" % (it["bbox_x0_um"], it["bbox_y0_um"], it["bbox_x1_um"], it["bbox_y1_um"]),
          pvlib.fmt(it["cell_area_um2"], 2)]
         for it in items]))
    lines.append("")
    lines.append("`x_norm`/`y_norm` are the area-weighted centroid mapped linearly from the DIEAREA "
                 "onto [-1, 1] on each axis (die corner (%.2f,%.2f) -> (-1,-1), (%.2f,%.2f) -> (1,1))." %
                 (dx0, dy0, dx1, dy1))
    lines.append("")
    return "\n".join(lines)


def discover(ci_dir):
    defp = None
    cand = glob.glob(os.path.join(ci_dir, "GDS_logs", "runs", "*", "final", "def", "*.def"))
    if cand:
        defp = cand[0]
    lefp = None
    cand = glob.glob(os.path.join(ci_dir, "tt_submission", "tt_submission", "*.lef"))
    if cand:
        lefp = cand[0]
    else:
        cand = glob.glob(os.path.join(ci_dir, "GDS_logs", "runs", "*", "final", "lef", "*.lef"))
        if cand:
            lefp = cand[0]
    return defp, lefp


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ci-dir")
    ap.add_argument("--def", dest="def_path")
    ap.add_argument("--lef")
    ap.add_argument("--out")
    a = ap.parse_args()

    defp, lefp = (None, None)
    if a.ci_dir:
        defp, lefp = discover(a.ci_dir)
    if a.def_path:
        defp = a.def_path
    if a.lef:
        lefp = a.lef
    if not defp:
        ap.error("need a DEF: pass --ci-dir or --def")

    d = pvlib.parse_def(defp)
    sizes = dict(pvlib.BUILTIN_SIZES)
    if lefp and os.path.exists(lefp):
        try:
            sizes.update(pvlib.parse_lef_sizes(lefp))
        except Exception as e:
            print("warning: failed to parse LEF %s (%s); using BUILTIN_SIZES only" % (lefp, e), file=sys.stderr)

    items, die = extract(d, sizes)
    md = render_markdown(items, die, defp, lefp)
    print(md)

    if a.out:
        os.makedirs(a.out, exist_ok=True)
        write_csv(os.path.join(a.out, "place_extract.csv"), items)
        with open(os.path.join(a.out, "place_extract.md"), "w", encoding="utf-8") as f:
            f.write(md)
        with open(os.path.join(a.out, "place_extract.json"), "w", encoding="utf-8") as f:
            json.dump({"def": os.path.relpath(defp), "die_um": die, "items": items}, f, indent=2)
        if HAVE_MPL:
            render_png(os.path.join(a.out, "floorplan.png"), items, die)
        else:
            print("warning: matplotlib not available, skipping floorplan.png", file=sys.stderr)


if __name__ == "__main__":
    main()
