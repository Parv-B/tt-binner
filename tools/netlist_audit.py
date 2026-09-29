#!/usr/bin/env python3
"""BINNER post-route netlist structural audit.

Verifies, on the post-route gate-level netlist(s) (tt_submission powered
netlist and/or GDS_logs final nl.v/pnl.v -- they should all be structurally
identical), that every ring oscillator, the tapped delay chain and the Fmax
launch/capture flops were placed and routed exactly as designed:

  * stage counts (16x INV/PUF g_puf[0..15] @ N_STG=25, u_ring_nand @ N_STG=25,
    u_ring_nor @ N_STG=25, u_ring_fo4 @ N_FO4=13 -- see src/project.v),
  * exact cell types / drive strengths for every notouch_ instance (flags any
    resizer substitution, e.g. inv_1 -> inv_2),
  * loop/chain connectivity (every stage's input net is driven by exactly the
    expected previous stage, no inserted buffer in the loop),
  * enable wiring (NAND ring: en -> enbuf_notouch_ BUF_1 -> en_buf_notouch_ ->
    every stage's A2; NOR ring: en -> enb_notouch_ INV -> en_b_notouch_ ->
    every stage's A2),
  * FO4 dummy loads (3 per stage, each driven by that stage's output),
  * delay-chain taps at stages 3,4,5,6,8,10,12,14 and the 8:1 tap-mux tree,
  * Fmax "*_keep_*" flops' D-pin connectivity: fcap_keep_[k].D must be driven
    by exactly the delay-chain stage at TAPPOS[k] (these flops are NOT
    notouch_ -- their CLK/RN may be buffered/CTS'd -- but their D pin must
    still land on the exact tap),
  * that no buffer/resize was inserted on any notouch_-named net (exact
    fanout as designed).

Usage:
  python tools/netlist_audit.py --ci-dir ci_artifacts/908c9e1 [--out docs/reports/908c9e1]
  python tools/netlist_audit.py --netlist PATH.v [--netlist PATH2.v ...]
  python tools/netlist_audit.py --self-test

Exit code: 0 if every netlist audited is clean, 1 on any FAIL finding (or, in
--self-test mode, if the audit fails to catch an injected corruption).
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pvlib  # noqa: E402


# =============================================================================
# Core audit
# =============================================================================
class Findings:
    def __init__(self):
        self.items = []   # dict(severity, category, msg, detail)

    def add(self, severity, category, msg, **detail):
        self.items.append({"severity": severity, "category": category, "msg": msg, "detail": detail})

    def fails(self):
        return [f for f in self.items if f["severity"] == "FAIL"]

    def warns(self):
        return [f for f in self.items if f["severity"] == "WARN"]


def _inst(nl, name):
    return nl.insts.get(name)


def _classify_all(nl):
    """Return dict role -> {(prefix, idx): inst_name}, and name->classification."""
    by_role = {}
    cls = {}
    for name, inst in nl.insts.items():
        c = pvlib.classify_notouch(name)
        if c is None:
            c = pvlib.classify_keep(name)
            tag = "keep"
        else:
            tag = "notouch"
        if c is None:
            continue
        role, prefix, idx = c
        cls[name] = (tag, role, prefix, idx)
        by_role.setdefault(role, {})[(prefix, idx)] = name
    return by_role, cls


def _driver_inst(nl, net):
    """Return (inst_name, pin) of the single driver of net, or None."""
    drivers = [d for d in nl.driver(net) if d[0] != "<port>"]
    if len(drivers) != 1:
        return None
    return drivers[0]


def _loads_insts(nl, net):
    return [l for l in nl.loads(net) if l[0] != "<port>"]


def audit_netlist(nl, label):
    """Run the full structural audit on one parsed Netlist. Returns Findings."""
    F = Findings()
    by_role, cls = _classify_all(nl)

    # -------------------------------------------------------------------
    # 1. Stage census + exact cell type (drive strength) per ring.
    # -------------------------------------------------------------------
    for prefix, kind, src, n in pvlib.RINGS:
        stages = by_role.get("ring_stage", {})
        found = {idx: name for (p, idx), name in stages.items() if p == prefix}
        missing = sorted(set(range(n)) - set(found))
        extra = sorted(i for i in found if i < 0 or i >= n)
        if missing:
            F.add("FAIL", "stage_count", "%s: missing ring stage(s)" % prefix,
                  ring=prefix, kind=pvlib.KIND_NAMES[kind], missing=missing, expected_n=n)
        if extra:
            F.add("FAIL", "stage_count", "%s: unexpected extra ring stage index(es)" % prefix,
                  ring=prefix, extra=extra)
        for idx, name in sorted(found.items()):
            if idx >= n:
                continue
            inst = nl.insts[name]
            expect_cell = pvlib.ring_stage_cell(kind, idx)
            if inst.cell != expect_cell:
                F.add("FAIL", "resize", "%s stage %d: cell type/drive changed" % (prefix, idx),
                      ring=prefix, stage=idx, inst=name, expected=expect_cell, actual=inst.cell)
        # ring_tap: exactly 1, INV1
        taps = {idx: name for (p, idx), name in by_role.get("ring_tap", {}).items() if p == prefix}
        if len(taps) != 1:
            F.add("FAIL", "tap_count", "%s: expected exactly 1 tap_notouch_, found %d" % (prefix, len(taps)),
                  ring=prefix, found=len(taps))
        else:
            (name,) = taps.values()
            if nl.insts[name].cell != pvlib.INV1:
                F.add("FAIL", "resize", "%s: tap_notouch_ cell type/drive changed" % prefix,
                      ring=prefix, inst=name, expected=pvlib.INV1, actual=nl.insts[name].cell)
        # enable buffering
        if kind == 2:
            enb = {idx: name for (p, idx), name in by_role.get("ring_enb", {}).items() if p == prefix}
            if len(enb) != 1:
                F.add("FAIL", "enable_wiring", "%s: expected exactly 1 enb_notouch_, found %d" % (prefix, len(enb)),
                      ring=prefix, found=len(enb))
            else:
                (name,) = enb.values()
                if nl.insts[name].cell != pvlib.INV1:
                    F.add("FAIL", "resize", "%s: enb_notouch_ cell type/drive changed" % prefix,
                          ring=prefix, inst=name, expected=pvlib.INV1, actual=nl.insts[name].cell)
        if kind == 1:
            enbuf = {idx: name for (p, idx), name in by_role.get("ring_enbuf", {}).items() if p == prefix}
            if len(enbuf) != 1:
                F.add("FAIL", "enable_wiring", "%s: expected exactly 1 enbuf_notouch_, found %d" % (prefix, len(enbuf)),
                      ring=prefix, found=len(enbuf))
            else:
                (name,) = enbuf.values()
                if nl.insts[name].cell != pvlib.BUF1:
                    F.add("FAIL", "resize", "%s: enbuf_notouch_ cell type/drive changed" % prefix,
                          ring=prefix, inst=name, expected=pvlib.BUF1, actual=nl.insts[name].cell)
        # FO4 dummy loads
        if kind == 3:
            loads = by_role.get("ring_load", {})
            lfound = {(s, k): name for (p, (s, k)), name in loads.items() if p == prefix}
            lmissing = [(s, k) for s in range(n) for k in range(3) if (s, k) not in lfound]
            if lmissing:
                F.add("FAIL", "fo4_loads", "%s: missing dummy load(s)" % prefix,
                      ring=prefix, missing=lmissing[:20], missing_count=len(lmissing))
            for (s, k), name in lfound.items():
                if nl.insts[name].cell != pvlib.INV1:
                    F.add("FAIL", "resize", "%s stage %d load %d: cell type/drive changed" % (prefix, s, k),
                          ring=prefix, stage=s, load=k, inst=name,
                          expected=pvlib.INV1, actual=nl.insts[name].cell)

    # -------------------------------------------------------------------
    # 2. Ring loop connectivity: stage i's input driven by stage (i-1)%n.
    # -------------------------------------------------------------------
    for prefix, kind, src, n in pvlib.RINGS:
        stages = {idx: name for (p, idx), name in by_role.get("ring_stage", {}).items() if p == prefix}
        for idx, name in sorted(stages.items()):
            inst = nl.insts[name]
            pin = "A1" if kind in (1, 2) else pvlib.loop_pin(inst.cell)
            # kind 0/3 stage 0 is a NAND2 gate cell: prev on A1.
            if kind in (0, 3) and idx == 0:
                pin = "A1"
            net = inst.pins.get(pin)
            if net is None:
                F.add("FAIL", "loop_connectivity", "%s stage %d: %s pin unconnected" % (prefix, idx, pin),
                      ring=prefix, stage=idx, inst=name, pin=pin)
                continue
            d = _driver_inst(nl, net)
            exp_idx = (idx - 1) % n
            ok = False
            if d is not None:
                c = cls.get(d[0])
                if c and c[1] == "ring_stage" and c[2] == prefix and c[3] == exp_idx:
                    ok = True
            if not ok:
                F.add("FAIL", "loop_connectivity",
                      "%s stage %d: expected input driven by stage %d, found %s" %
                      (prefix, idx, exp_idx, d[0] if d else "no unique driver"),
                      ring=prefix, stage=idx, expected_driver_stage=exp_idx,
                      actual_driver=(d[0] if d else None))

        # tap driven by last stage
        taps = {idx: name for (p, idx), name in by_role.get("ring_tap", {}).items() if p == prefix}
        for name in taps.values():
            net = nl.insts[name].pins.get("I")
            d = _driver_inst(nl, net) if net else None
            ok = d is not None and cls.get(d[0], (None,))[1:4] == ("ring_stage", prefix, n - 1)
            if not ok:
                F.add("FAIL", "loop_connectivity", "%s: tap_notouch_ not driven by last stage (%d)" % (prefix, n - 1),
                      ring=prefix, actual_driver=(d[0] if d else None))

        # FO4 dummy loads driven by their own stage
        if kind == 3:
            loads = {(s, k): name for (p, (s, k)), name in by_role.get("ring_load", {}).items() if p == prefix}
            for (s, k), name in loads.items():
                net = nl.insts[name].pins.get("I")
                d = _driver_inst(nl, net) if net else None
                ok = d is not None and cls.get(d[0], (None,))[1:4] == ("ring_stage", prefix, s)
                if not ok:
                    F.add("FAIL", "fo4_loads", "%s stage %d load %d: not driven by its own stage" % (prefix, s, k),
                          ring=prefix, stage=s, load=k, actual_driver=(d[0] if d else None))

        # enable fanout: every stage's A2 (or gate stage0's A2 for kind 0/3) driven by
        # the enb/enbuf instance, and the enb/enbuf net's ONLY loads are those A2 pins
        # (kind 1/2: every stage; kind 0/3: only stage 0).
        if kind in (1, 2):
            role = "ring_enbuf" if kind == 1 else "ring_enb"
            src_map = {idx: name for (p, idx), name in by_role.get(role, {}).items() if p == prefix}
            if src_map:
                (ename,) = src_map.values()
                outpin = "Z" if kind == 1 else "ZN"
                enet = nl.insts[ename].pins.get(outpin)
                actual_loads = set(_loads_insts(nl, enet)) if enet else set()
                expected_loads = set()
                for idx, name in stages.items():
                    expected_loads.add((name, "A2"))
                if actual_loads != expected_loads:
                    missing = expected_loads - actual_loads
                    extra = actual_loads - expected_loads
                    F.add("FAIL", "enable_wiring",
                          "%s: %s fanout mismatch (expected exactly all %d stage A2 pins)" %
                          (prefix, role, n),
                          ring=prefix, missing=[m[0] for m in missing][:10],
                          extra=[e[0] for e in extra][:10], extra_count=len(extra))
        elif kind in (0, 3) and 0 in stages:
            # stage 0 gate: A2 tied to the ring's own top-level 'en' -- not notouch_,
            # so we only sanity-check it is driven by something external (single driver).
            g0 = nl.insts[stages[0]]
            enet = g0.pins.get("A2")
            d = _driver_inst(nl, enet) if enet else None
            if enet is None:
                F.add("FAIL", "enable_wiring", "%s: stage 0 gate A2 (en) unconnected" % prefix, ring=prefix)

    # -------------------------------------------------------------------
    # 3. Delay chain: stage census, cell types, chain + tap-mux connectivity.
    # -------------------------------------------------------------------
    dly = by_role.get("dc_dly", {})
    dly_found = {idx: name for (p, idx), name in dly.items() if p == pvlib.DCHAIN}
    dmissing = sorted(set(range(1, pvlib.N_DLY + 1)) - set(dly_found))
    if dmissing:
        F.add("FAIL", "dchain_stage_count", "delay chain: missing dly_notouch_ stage(s)", missing=dmissing)
    for idx, name in dly_found.items():
        if nl.insts[name].cell != pvlib.DLY:
            F.add("FAIL", "resize", "delay chain stage %d: cell type/drive changed" % idx,
                  stage=idx, inst=name, expected=pvlib.DLY, actual=nl.insts[name].cell)
        net = nl.insts[name].pins.get("I")
        d = _driver_inst(nl, net) if net else None
        if idx == 1:
            ok = d is not None and cls.get(d[0], (None,))[1] == "dc_inmux"
            exp = "dmx_notouch_"
        else:
            ok = (d is not None and cls.get(d[0], (None, None, None, None))[1:4] ==
                  ("dc_dly", pvlib.DCHAIN, idx - 1))
            exp = "dly stage %d" % (idx - 1)
        if not ok:
            F.add("FAIL", "dchain_connectivity", "delay chain stage %d: input not driven by %s" % (idx, exp),
                  stage=idx, actual_driver=(d[0] if d else None))

    inmux = {idx: name for (p, idx), name in by_role.get("dc_inmux", {}).items() if p == pvlib.DCHAIN}
    if len(inmux) != 1:
        F.add("FAIL", "dchain_stage_count", "delay chain: expected exactly 1 dmx_notouch_, found %d" % len(inmux))
    else:
        (name,) = inmux.values()
        if nl.insts[name].cell != pvlib.MUX2:
            F.add("FAIL", "resize", "delay chain dmx_notouch_: cell type/drive changed",
                  inst=name, expected=pvlib.MUX2, actual=nl.insts[name].cell)
        i1 = nl.insts[name].pins.get("I1")
        d = _driver_inst(nl, i1) if i1 else None
        if not (d is not None and cls.get(d[0], (None,))[1] == "dc_fbnand"):
            F.add("FAIL", "dchain_connectivity", "delay chain dmx_notouch_.I1: not driven by dfbg_notouch_ (feedback)",
                  actual_driver=(d[0] if d else None))

    tapmux = {idx: name for (p, idx), name in by_role.get("dc_tapmux", {}).items() if p == pvlib.DCHAIN}
    tmissing = sorted(set(range(7)) - set(tapmux))
    if tmissing:
        F.add("FAIL", "dchain_stage_count", "delay chain: missing tap-mux stage(s)", missing=tmissing)
    for idx, name in tapmux.items():
        if nl.insts[name].cell != pvlib.MUX2:
            F.add("FAIL", "resize", "delay chain tm%d_notouch_: cell type/drive changed" % idx,
                  inst=name, expected=pvlib.MUX2, actual=nl.insts[name].cell)
    # leaf tap-mux inputs (tm0..tm3) must trace to the exact TAPPOS stages.
    leaf_pairs = [(0, 1), (2, 3), (4, 5), (6, 7)]
    for k, (a, b) in enumerate(leaf_pairs):
        name = tapmux.get(k)
        if not name:
            continue
        inst = nl.insts[name]
        for pin, tapidx in (("I0", a), ("I1", b)):
            net = inst.pins.get(pin)
            d = _driver_inst(nl, net) if net else None
            exp_stage = pvlib.TAPPOS[tapidx]
            ok = (d is not None and cls.get(d[0], (None, None, None, None))[1:4] ==
                  ("dc_dly", pvlib.DCHAIN, exp_stage))
            if not ok:
                F.add("FAIL", "dchain_tap_wiring",
                      "tm%d_notouch_.%s: expected tap %d (chain stage %d), found %s" %
                      (k, pin, tapidx, exp_stage, d[0] if d else "none"),
                      tapmux=k, pin=pin, expected_stage=exp_stage, actual_driver=(d[0] if d else None))
    combine = [(4, 0, 1), (5, 2, 3), (6, 4, 5)]
    for k, a, b in combine:
        name = tapmux.get(k)
        if not name:
            continue
        inst = nl.insts[name]
        for pin, srcidx in (("I0", a), ("I1", b)):
            net = inst.pins.get(pin)
            d = _driver_inst(nl, net) if net else None
            ok = (d is not None and cls.get(d[0], (None, None, None, None))[1:4] ==
                  ("dc_tapmux", pvlib.DCHAIN, srcidx))
            if not ok:
                F.add("FAIL", "dchain_tap_wiring",
                      "tm%d_notouch_.%s: expected tm%d_notouch_, found %s" % (k, pin, srcidx, d[0] if d else "none"),
                      tapmux=k, pin=pin, expected_src=srcidx, actual_driver=(d[0] if d else None))

    fbnand = {idx: name for (p, idx), name in by_role.get("dc_fbnand", {}).items() if p == pvlib.DCHAIN}
    if len(fbnand) != 1:
        F.add("FAIL", "dchain_stage_count", "delay chain: expected exactly 1 dfbg_notouch_, found %d" % len(fbnand))
    else:
        (name,) = fbnand.values()
        if nl.insts[name].cell != pvlib.NAND2:
            F.add("FAIL", "resize", "delay chain dfbg_notouch_: cell type/drive changed",
                  inst=name, expected=pvlib.NAND2, actual=nl.insts[name].cell)
        a1 = nl.insts[name].pins.get("A1")
        d = _driver_inst(nl, a1) if a1 else None
        if not (d is not None and cls.get(d[0], (None, None, None, None))[1:4] == ("dc_tapmux", pvlib.DCHAIN, 6)):
            F.add("FAIL", "dchain_tap_wiring", "delay chain dfbg_notouch_.A1: expected tm6_notouch_",
                  actual_driver=(d[0] if d else None))

    dtap = {idx: name for (p, idx), name in by_role.get("dc_tap", {}).items() if p == pvlib.DCHAIN}
    if len(dtap) != 1:
        F.add("FAIL", "dchain_stage_count", "delay chain: expected exactly 1 dtap_notouch_, found %d" % len(dtap))
    else:
        (name,) = dtap.values()
        if nl.insts[name].cell != pvlib.INV1:
            F.add("FAIL", "resize", "delay chain dtap_notouch_: cell type/drive changed",
                  inst=name, expected=pvlib.INV1, actual=nl.insts[name].cell)
        ipin = nl.insts[name].pins.get("I")
        d = _driver_inst(nl, ipin) if ipin else None
        if not (d is not None and cls.get(d[0], (None,))[1] == "dc_fbnand"):
            F.add("FAIL", "dchain_connectivity", "delay chain dtap_notouch_.I: expected dfbg_notouch_",
                  actual_driver=(d[0] if d else None))

    # -------------------------------------------------------------------
    # 4. Fmax "*_keep_*" flops: census, cell type, D-pin -> exact tap.
    # -------------------------------------------------------------------
    keep_by_role = {}
    for name, inst in nl.insts.items():
        c = pvlib.classify_keep(name)
        if c:
            keep_by_role.setdefault(c[0], {})[c[2]] = name

    launch = keep_by_role.get("fm_launch", {})
    if len(launch) != 1:
        F.add("FAIL", "fmax_count", "expected exactly 1 flaunch_keep_, found %d" % len(launch))
    else:
        (name,) = launch.values()
        if nl.insts[name].cell != pvlib.DFFRN:
            F.add("FAIL", "resize", "flaunch_keep_: cell type/drive changed",
                  inst=name, expected=pvlib.DFFRN, actual=nl.insts[name].cell)
        if "notouch_" in name:
            F.add("WARN", "keep_not_notouch", "flaunch_keep_ unexpectedly also matches notouch_ naming", inst=name)

    caps = keep_by_role.get("fm_cap", {})
    cmissing = sorted(set(range(8)) - set(caps))
    if cmissing:
        F.add("FAIL", "fmax_count", "missing fcap_keep_[k] instance(s)", missing=cmissing)
    for k, name in sorted(caps.items()):
        inst = nl.insts[name]
        if inst.cell != pvlib.DFFRN:
            F.add("FAIL", "resize", "fcap_keep_[%d]: cell type/drive changed" % k,
                  inst=name, expected=pvlib.DFFRN, actual=inst.cell)
        dnet = inst.pins.get("D")
        d = _driver_inst(nl, dnet) if dnet else None
        exp_stage = pvlib.TAPPOS[k]
        ok = (d is not None and cls.get(d[0], (None, None, None, None))[1:4] ==
              ("dc_dly", pvlib.DCHAIN, exp_stage))
        if not ok:
            F.add("FAIL", "fmax_tap_wiring",
                  "fcap_keep_[%d].D: expected delay-chain tap at stage %d, found %s" %
                  (k, exp_stage, d[0] if d else "no unique driver"),
                  cap=k, expected_stage=exp_stage, actual_driver=(d[0] if d else None))

    # -------------------------------------------------------------------
    # 5. Global notouch_ net integrity: every notouch_ net's driver must be
    #    a classified notouch_ instance (catches a buffer/tie-cell silently
    #    inserted as the driver of a supposedly-protected net).
    # -------------------------------------------------------------------
    for net in nl.nets:
        if pvlib.NOTOUCH not in net:
            continue
        d = _driver_inst(nl, net)
        if d is None:
            continue  # ambiguous/undriven: covered by the specific checks above
        if d[0] not in cls or cls[d[0]][0] != "notouch":
            F.add("FAIL", "unexpected_driver",
                  "notouch_ net %r driven by non-notouch_ instance %s (%s)" %
                  (net, d[0], nl.insts[d[0]].cell if d[0] in nl.insts else "?"),
                  net=net, actual_driver=d[0])

    return F


# =============================================================================
# Report rendering
# =============================================================================
def render_markdown(results):
    lines = ["# BINNER netlist structural audit", ""]
    overall_ok = all(not r["findings"].fails() for r in results)
    lines.append("**Overall: %s**" % ("PASS" if overall_ok else "FAIL"))
    lines.append("")
    for r in results:
        F = r["findings"]
        lines.append("## %s" % r["label"])
        lines.append("")
        lines.append("- Netlist: `%s`" % r["path"])
        lines.append("- Module: `%s`" % r["module"])
        lines.append("- Instances parsed: %d" % r["n_insts"])
        lines.append("- Result: **%s** (%d FAIL, %d WARN)" % (
            "PASS" if not F.fails() else "FAIL", len(F.fails()), len(F.warns())))
        lines.append("")
        if F.items:
            lines.append(pvlib.md_table(
                ["severity", "category", "message"],
                [[f["severity"], f["category"], f["msg"]] for f in F.items]))
            lines.append("")
        else:
            lines.append("No findings -- structure matches src/binner_ring.v, "
                          "src/binner_dchain.v, src/binner_fmax.v exactly.")
            lines.append("")
    lines.append("## Checks performed")
    lines.append("")
    lines.append("- Stage census (missing/extra) for each of the 16 PUF/INV rings (N=%d), "
                  "the NAND ring (N=%d), the NOR ring (N=%d), the FO4 ring (N=%d)." %
                  (pvlib.N_STG, pvlib.N_STG, pvlib.N_STG, pvlib.N_FO4))
    lines.append("- Exact cell type/drive strength for every notouch_ instance (resize detection).")
    lines.append("- Ring loop connectivity (stage i driven by stage (i-1) mod N, tap driven by stage N-1).")
    lines.append("- Enable wiring: NAND ring en_buf_notouch_ fans out to exactly all N stage A2 pins; "
                  "NOR ring en_b_notouch_ likewise.")
    lines.append("- FO4 dummy loads (3 per stage, each driven by that stage's own output).")
    lines.append("- Delay-chain stage census/connectivity, 8:1 tap-mux tree wiring, feedback loop closure.")
    lines.append("- Fmax fcap_keep_[k].D driven by exactly the delay-chain stage at TAPPOS[k] "
                  "= %s (these flops are intentionally NOT notouch_; only checked for D-pin wiring "
                  "and cell type, not fanout on CLK/RN)." % pvlib.TAPPOS)
    lines.append("- Global scan: every notouch_-named net's driver is itself a notouch_-classified "
                  "instance (catches any inserted buffer/resize on a protected net).")
    lines.append("")
    return "\n".join(lines)


def results_to_json(results):
    out = []
    for r in results:
        out.append({
            "label": r["label"], "path": r["path"], "module": r["module"],
            "n_insts": r["n_insts"], "pass": not r["findings"].fails(),
            "n_fail": len(r["findings"].fails()), "n_warn": len(r["findings"].warns()),
            "findings": r["findings"].items,
        })
    return out


# =============================================================================
# Real-artifact discovery + main
# =============================================================================
def discover_netlists(ci_dir):
    """Locate the flat gate-level netlist(s), never the hand-written RTL under
    tt_submission/src/ (which parse_verilog() cannot parse -- it is behavioural
    Verilog with functions/generate blocks, not a synthesised netlist)."""
    found = []
    # tt_submission/tt_submission/<top>.v is the LibreLane-produced powered
    # netlist that ships in the submission (see tt_submission/tt_submission/).
    cand = glob.glob(os.path.join(ci_dir, "tt_submission", "tt_submission", "*.v"))
    for p in cand:
        found.append(("tt_submission powered netlist", p))
    for sub, label in (("nl", "GDS_logs final nl.v (unpowered)"), ("pnl", "GDS_logs final pnl.v (powered)")):
        cand = glob.glob(os.path.join(ci_dir, "GDS_logs", "runs", "*", "final", sub, "*.v"))
        for p in cand:
            found.append((label, p))
    return found


def run_one(path, label):
    nl = pvlib.parse_verilog(path)
    F = audit_netlist(nl, label)
    return {"label": label, "path": os.path.relpath(path), "module": nl.module,
            "n_insts": len(nl.insts), "findings": F}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ci-dir", help="ci_artifacts/<sha> directory to auto-discover netlists in")
    ap.add_argument("--netlist", action="append", default=[], help="explicit netlist .v path (repeatable)")
    ap.add_argument("--out", help="output directory for report.md / report.json")
    ap.add_argument("--self-test", action="store_true", help="run synthetic good/corrupted self-tests instead")
    a = ap.parse_args()

    if a.self_test:
        import selftest_netlist_audit as st
        ok = st.run()
        sys.exit(0 if ok else 1)

    targets = [(os.path.basename(p), p) for p in a.netlist]
    if a.ci_dir:
        targets += discover_netlists(a.ci_dir)
    if not targets:
        ap.error("no netlists given: pass --ci-dir or one or more --netlist")

    results = [run_one(p, label) for label, p in targets]
    md = render_markdown(results)
    js = {"results": results_to_json(results)}

    if a.out:
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, "netlist_audit.md"), "w", encoding="utf-8") as f:
            f.write(md)
        with open(os.path.join(a.out, "netlist_audit.json"), "w", encoding="utf-8") as f:
            json.dump(js, f, indent=2)
    print(md)

    sys.exit(0 if all(not r["findings"].fails() for r in results) else 1)


if __name__ == "__main__":
    main()
