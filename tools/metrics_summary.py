#!/usr/bin/env python3
"""BINNER LibreLane metrics.csv summary: utilization, cell counts/area, timing
WNS/TNS per corner, slew/fanout violations, antenna/DRC counts.

metrics.csv (tt_submission/tt_submission/stats/metrics.csv) is a flat
"Metric,Value" table (one row per scalar metric, ~300 rows for this design),
not a wide table -- this is the CI's own OpenROAD/LibreLane metrics dump, the
authoritative source for the utilization number the project plan estimated
at ~32.8k um^2 (via a local yosys area estimate, pre-place-and-route). This
tool reports the real, post-route number and flags it (along with any
non-zero violation counts) rather than silently passing them through.

Usage:
  python tools/metrics_summary.py --ci-dir ci_artifacts/908c9e1 [--out docs/reports/908c9e1]
  python tools/metrics_summary.py --csv PATH/metrics.csv [--out DIR]
"""
import argparse
import csv
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pvlib  # noqa: E402

UTIL_TARGET = 0.60   # project plan's target: <= 60% utilization


def load_metrics(path):
    m = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        r = csv.reader(f)
        header = next(r, None)
        for row in r:
            if len(row) < 2:
                continue
            k, v = row[0], row[1]
            if v == "":
                m[k] = None
                continue
            try:
                m[k] = int(v)
            except ValueError:
                try:
                    m[k] = float(v)
                except ValueError:
                    m[k] = v
    return m


def get(m, key, default=None):
    return m[key] if key in m and m[key] is not None else default


_CORNER_RE = re.compile(r"^(.*)__corner:(.+)$")


def corners_of(m, base):
    """Return {corner_or_None: value} for metric `base` and its per-corner
    variants `base__corner:<name>`."""
    out = {}
    if base in m:
        out[None] = m[base]
    for k, v in m.items():
        mm = _CORNER_RE.match(k)
        if mm and mm.group(1) == base:
            out[mm.group(2)] = v
    return out


def build_report(m, csv_path):
    inst_count = get(m, "design__instance__count")
    inst_area = get(m, "design__instance__area")
    stdcell_area = get(m, "design__instance__area__stdcell")
    die_area = get(m, "design__die__area")
    core_area = get(m, "design__core__area")
    util = get(m, "design__instance__utilization")
    util_stdcell = get(m, "design__instance__utilization__stdcell")

    overview = {
        "instance_count": inst_count, "instance_area_um2": inst_area,
        "stdcell_area_um2": stdcell_area, "die_area_um2": die_area, "core_area_um2": core_area,
        "utilization": util, "utilization_stdcell": util_stdcell,
        "displacement_total_um": get(m, "design__instance__displacement__total"),
        "displacement_mean_um": get(m, "design__instance__displacement__mean"),
        "displacement_max_um": get(m, "design__instance__displacement__max"),
    }

    classes = {}
    for k, v in m.items():
        mm = re.match(r"^design__instance__count__class:(.+)$", k)
        if mm:
            cls = mm.group(1)
            classes.setdefault(cls, {})["count"] = v
        mm = re.match(r"^design__instance__area__class:(.+)$", k)
        if mm:
            cls = mm.group(1)
            classes.setdefault(cls, {})["area_um2"] = v
    class_rows = [{"class": c, "count": d.get("count"), "area_um2": d.get("area_um2")}
                  for c, d in sorted(classes.items())]

    timing_rows = []
    corners = set()
    for base in ("timing__setup__wns", "timing__setup__tns", "timing__hold__wns", "timing__hold__tns"):
        corners |= set(k for k in corners_of(m, base) if k is not None)
    for c in sorted(corners):
        timing_rows.append({
            "corner": c,
            "setup_wns_ns": get(m, "timing__setup__wns__corner:%s" % c),
            "setup_tns_ns": get(m, "timing__setup__tns__corner:%s" % c),
            "hold_wns_ns": get(m, "timing__hold__wns__corner:%s" % c),
            "hold_tns_ns": get(m, "timing__hold__tns__corner:%s" % c),
            "max_slew_violations": get(m, "design__max_slew_violation__count__corner:%s" % c),
            "max_fanout_violations": get(m, "design__max_fanout_violation__count__corner:%s" % c),
        })
    overall_timing = {
        "setup_wns_ns": get(m, "timing__setup__wns"), "setup_tns_ns": get(m, "timing__setup__tns"),
        "hold_wns_ns": get(m, "timing__hold__wns"), "hold_tns_ns": get(m, "timing__hold__tns"),
        "max_slew_violations": get(m, "design__max_slew_violation__count"),
        "max_fanout_violations": get(m, "design__max_fanout_violation__count"),
    }

    drc = {
        "antenna_violating_nets": get(m, "antenna__violating__nets"),
        "antenna_violating_pins": get(m, "antenna__violating__pins"),
        "route_antenna_violation_count": get(m, "route__antenna_violation__count"),
        "antenna_diodes_count": get(m, "antenna_diodes_count"),
        "route_drc_errors_final": get(m, "route__drc_errors"),
        "magic_drc_error_count": get(m, "magic__drc_error__count"),
        "lint_error_count": get(m, "design__lint_error__count"),
        "lint_warning_count": get(m, "design__lint_warning__count"),
        "lint_timing_construct_count": get(m, "design__lint_timing_construct__count"),
        "inferred_latch_count": get(m, "design__inferred_latch__count"),
        "unmapped_cell_count": get(m, "design__instance_unmapped__count"),
    }
    drt_iters = sorted(((k, v) for k, v in m.items() if k.startswith("route__drc_errors__iter:")),
                       key=lambda kv: int(kv[0].split(":")[1]))

    flags = []
    if util is not None and util > UTIL_TARGET:
        ratio = (stdcell_area / 32800.0) if stdcell_area else float("nan")
        detail = ("utilization %.2f%% (stdcell area %s um^2 / core area %s um^2) exceeds the project's "
                  "<=60%% design target. The plan's pre-route yosys estimate was ~32.8k um^2; the real "
                  "post-route stdcell area is %s um^2 -- %.1fx the estimate." %
                  (util * 100, pvlib.fmt(stdcell_area, 1), pvlib.fmt(core_area, 1),
                   pvlib.fmt(stdcell_area, 1), ratio))
        flags.append(("FAIL vs. plan target", detail))
    for row in timing_rows:
        if row["setup_wns_ns"] is not None and row["setup_wns_ns"] < 0:
            flags.append(("setup timing", "corner %s: setup WNS %.3f ns, TNS %.3f ns (%d slew, %d fanout violations)" %
                          (row["corner"], row["setup_wns_ns"], row["setup_tns_ns"] or 0.0,
                           row["max_slew_violations"] or 0, row["max_fanout_violations"] or 0)))
        if row["hold_wns_ns"] is not None and row["hold_wns_ns"] < 0:
            flags.append(("hold timing", "corner %s: hold WNS %.3f ns, TNS %.3f ns" %
                          (row["corner"], row["hold_wns_ns"], row["hold_tns_ns"] or 0.0)))
    if overall_timing["max_fanout_violations"]:
        flags.append(("fanout", "%d max-fanout violation(s), present in every corner (structural, not "
                      "corner-dependent) -- metrics.csv does not name the offending net(s)." %
                      overall_timing["max_fanout_violations"]))
    for k, v in drc.items():
        if k in ("lint_warning_count",):
            continue
        if v:
            flags.append(("drc/antenna/lint", "%s = %s" % (k, v)))
    if drc["lint_warning_count"]:
        flags.append(("lint (informational)", "%d lint warning(s) in the synthesised design." % drc["lint_warning_count"]))

    return {
        "csv": os.path.relpath(csv_path), "overview": overview, "classes": class_rows,
        "timing_per_corner": timing_rows, "timing_overall": overall_timing,
        "drc_antenna_lint": drc, "route_drc_iterations": [(k, v) for k, v in drt_iters],
        "flags": [{"category": c, "detail": d} for c, d in flags],
    }


def render_markdown(rep):
    o = rep["overview"]
    lines = ["# BINNER LibreLane metrics summary", ""]
    lines.append("Source: `%s`" % rep["csv"])
    lines.append("")
    status = "OVER TARGET" if (o["utilization"] or 0) > UTIL_TARGET else "within target"
    lines.append("**Utilization: %s%% (%s, target <= %d%%)**" %
                 (pvlib.fmt((o["utilization"] or 0) * 100, 2), status, int(UTIL_TARGET * 100)))
    lines.append("")
    lines.append(pvlib.md_table(
        ["metric", "value"],
        [["instance count", o["instance_count"]],
         ["instance area (um^2)", pvlib.fmt(o["instance_area_um2"], 1)],
         ["stdcell area (um^2)", pvlib.fmt(o["stdcell_area_um2"], 1)],
         ["core area (um^2)", pvlib.fmt(o["core_area_um2"], 1)],
         ["die area (um^2)", pvlib.fmt(o["die_area_um2"], 1)],
         ["utilization (instance/core)", pvlib.fmt((o["utilization"] or 0) * 100, 2) + "%"],
         ["utilization (stdcell/core)", pvlib.fmt((o["utilization_stdcell"] or 0) * 100, 2) + "%"],
         ["placement displacement total/mean/max (um)",
          "%s / %s / %s" % (pvlib.fmt(o["displacement_total_um"]), pvlib.fmt(o["displacement_mean_um"]),
                            pvlib.fmt(o["displacement_max_um"]))],
         ]))
    lines.append("")
    lines.append("## Cell class breakdown")
    lines.append("")
    lines.append(pvlib.md_table(["class", "count", "area (um^2)"],
                                [[c["class"], c["count"], pvlib.fmt(c["area_um2"], 2)] for c in rep["classes"]]))
    lines.append("")
    lines.append("## Timing WNS/TNS and slew/fanout violations per corner")
    lines.append("")
    lines.append(pvlib.md_table(
        ["corner", "setup WNS (ns)", "setup TNS (ns)", "hold WNS (ns)", "hold TNS (ns)",
         "slew violations", "fanout violations"],
        [[r["corner"], pvlib.fmt(r["setup_wns_ns"]), pvlib.fmt(r["setup_tns_ns"]),
          pvlib.fmt(r["hold_wns_ns"]), pvlib.fmt(r["hold_tns_ns"]),
          r["max_slew_violations"], r["max_fanout_violations"]] for r in rep["timing_per_corner"]]))
    lines.append("")
    ot = rep["timing_overall"]
    lines.append("Overall (worst across corners): setup WNS %s ns, setup TNS %s ns, hold WNS %s ns, "
                 "hold TNS %s ns, %s slew violations, %s fanout violations." %
                 (pvlib.fmt(ot["setup_wns_ns"]), pvlib.fmt(ot["setup_tns_ns"]), pvlib.fmt(ot["hold_wns_ns"]),
                  pvlib.fmt(ot["hold_tns_ns"]), ot["max_slew_violations"], ot["max_fanout_violations"]))
    lines.append("")
    lines.append("## Antenna / DRC / lint")
    lines.append("")
    d = rep["drc_antenna_lint"]
    lines.append(pvlib.md_table(["metric", "value"], [[k, v] for k, v in d.items()]))
    lines.append("")
    if rep["route_drc_iterations"]:
        lines.append("Detailed-routing DRC error count by repair iteration: " +
                     ", ".join("%s=%s" % (k.split(":")[1], v) for k, v in rep["route_drc_iterations"]) + ".")
        lines.append("")
    lines.append("## Flags")
    lines.append("")
    if rep["flags"]:
        lines.append(pvlib.md_table(["category", "detail"], [[f["category"], f["detail"]] for f in rep["flags"]]))
    else:
        lines.append("None.")
    lines.append("")
    return "\n".join(lines)


def write_csv(path, rep):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["section", "key", "value"])
        for k, v in rep["overview"].items():
            w.writerow(["overview", k, v])
        for c in rep["classes"]:
            w.writerow(["class", c["class"] + ".count", c["count"]])
            w.writerow(["class", c["class"] + ".area_um2", c["area_um2"]])
        for r in rep["timing_per_corner"]:
            for k, v in r.items():
                if k == "corner":
                    continue
                w.writerow(["timing." + r["corner"], k, v])
        for k, v in rep["drc_antenna_lint"].items():
            w.writerow(["drc_antenna_lint", k, v])
        for f in rep["flags"]:
            w.writerow(["flag", f["category"], f["detail"]])


def discover(ci_dir):
    cand = glob.glob(os.path.join(ci_dir, "tt_submission", "tt_submission", "stats", "metrics.csv"))
    return cand[0] if cand else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ci-dir")
    ap.add_argument("--csv")
    ap.add_argument("--out")
    a = ap.parse_args()

    path = a.csv
    if not path and a.ci_dir:
        path = discover(a.ci_dir)
    if not path:
        ap.error("need metrics.csv: pass --ci-dir or --csv")

    m = load_metrics(path)
    rep = build_report(m, path)
    md = render_markdown(rep)
    print(md)

    if a.out:
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, "metrics_summary.md"), "w", encoding="utf-8") as f:
            f.write(md)
        with open(os.path.join(a.out, "metrics_summary.json"), "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2)
        write_csv(os.path.join(a.out, "metrics_summary.csv"), rep)

    sys.exit(1 if any(f["category"].startswith("FAIL") for f in rep["flags"]) else 0)


if __name__ == "__main__":
    main()
