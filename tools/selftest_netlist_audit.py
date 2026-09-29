#!/usr/bin/env python3
"""Synthetic self-test for tools/netlist_audit.py.

Generates a flat gate-level Verilog netlist that is structurally identical
(same instance-naming scheme -- classify_notouch()/classify_keep() operate
on instance names only -- and the same connectivity graph) to what
src/binner_ring.v, src/binner_dchain.v and src/binner_fmax.v synthesise to.
It is built mechanically from the same pvlib constants the audit checks
against (pvlib.RINGS, pvlib.TAPPOS, pvlib.N_DLY, ...), so a clean run of
this generator must pass the audit with zero findings.

Instance names are real dotted/bracketed hierarchical paths (escaped per
Verilog syntax, as OpenROAD/Yosys write them) because classify_notouch()'s
regexes require that shape. Net names are kept flat, simple identifiers
(no dots/brackets) -- the audit identifies structural roles from instance
names and net *identity* (via driver/load graph lookups), never from a net
name's literal spelling, so flat net names are fully equivalent to the real
hierarchical ones for every check exercised here, and they sidestep Verilog
identifier-escaping edge cases in this generator.

Then applies four independent single-point corruptions (a resize, an
inserted buffer on a notouch_ net, a deleted ring stage, and a mis-wired
Fmax tap) and asserts the audit flags each one. This is the proof, required
by the tooling task, that the audit actually catches insertions and resizes
rather than trivially passing.

Run directly (`python tools/selftest_netlist_audit.py`) or via
`python tools/netlist_audit.py --self-test`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pvlib  # noqa: E402
import netlist_audit as na  # noqa: E402


class Inst:
    def __init__(self, cell, name, pins):
        self.cell, self.name, self.pins = cell, name, dict(pins)


class Gen:
    """Structured instance list -> renders to escaped-identifier flat Verilog."""

    def __init__(self):
        self.insts = []          # list[Inst], order preserved
        self._by_name = {}

    def inst(self, cell, name, **pins):
        i = Inst(cell, name, pins)
        self.insts.append(i)
        self._by_name[name] = i
        return i

    def get(self, name):
        return self._by_name[name]

    def remove(self, name):
        i = self._by_name.pop(name)
        self.insts.remove(i)

    def clone(self):
        g = Gen()
        for i in self.insts:
            g.inst(i.cell, i.name, **i.pins)
        return g

    def render(self, top_ports=("clk", "rst_n")):
        lines = ["module top (%s);" % ", ".join(top_ports)]
        for p in top_ports:
            lines.append("input %s;" % p)
        for i in self.insts:
            pinstr = ", ".join(".%s(%s)" % (p, n) for p, n in i.pins.items())
            lines.append("%s \\%s  (%s);" % (i.cell, i.name, pinstr))
        lines.append("endmodule")
        return "\n".join(lines)


def _flat(prefix):
    return prefix.replace("[", "").replace("]", "").replace(".", "_")


def build_golden():
    """Build a full structurally-correct BINNER netlist as a Gen object."""
    g = Gen()

    for prefix, kind, src, n in pvlib.RINGS:
        fp = _flat(prefix)
        ring_w = ["%s_ring_notouch_%d" % (fp, i) for i in range(n)]
        en_top = "en_%s" % fp
        enbuf_net = enb_net = None
        if kind == 1:
            enbuf_net = "%s_en_buf_notouch" % fp
            g.inst(pvlib.BUF1, "%s.enbuf_notouch_" % prefix, I=en_top, Z=enbuf_net)
        if kind == 2:
            enb_net = "%s_en_b_notouch" % fp
            g.inst(pvlib.INV1, "%s.enb_notouch_" % prefix, I=en_top, ZN=enb_net)
        for i in range(n):
            prev = ring_w[(i - 1) % n]
            out = ring_w[i]
            name = "%s.g_stg[%d].stg_notouch_" % (prefix, i)
            if kind == 1:
                g.inst(pvlib.NAND2, name, A1=prev, A2=enbuf_net, ZN=out)
            elif kind == 2:
                g.inst(pvlib.NOR2, name, A1=prev, A2=enb_net, ZN=out)
            elif i == 0:
                g.inst(pvlib.NAND2, name, A1=prev, A2=en_top, ZN=out)
            else:
                g.inst(pvlib.INV1, name, I=prev, ZN=out)
            if kind == 3:
                for k in range(3):
                    ld = "%s_stg%d_ld%d_dummy" % (fp, i, k)
                    g.inst(pvlib.INV1, "%s.g_stg[%d].ld%d_notouch_" % (prefix, i, k), I=out, ZN=ld)
        g.inst(pvlib.INV1, "%s.tap_notouch_" % prefix, I=ring_w[n - 1], ZN="%s_tap_out_dummy" % fp)

    # ---- delay chain ----
    d = pvlib.DCHAIN
    dch = ["dchain_notouch_%d" % i for i in range(pvlib.N_DLY + 1)]
    launch, ring_mode, ring_en = "launch_top", "ring_mode_top", "ring_en_top"
    dfb = "dchain_dfb_notouch"
    g.inst(pvlib.MUX2, "%s.dmx_notouch_" % d, I0=launch, I1=dfb, S=ring_mode, Z=dch[0])
    for i in range(1, pvlib.N_DLY + 1):
        g.inst(pvlib.DLY, "%s.g_stg[%d].dly_notouch_" % (d, i), I=dch[i - 1], Z=dch[i])
    # taps[k] is a pure `assign` alias of dch[TAPPOS[k]] in the real RTL
    # (binner_dchain.v); model that directly by wiring the tap-mux leaves to
    # dch[] straight -- equivalent for every check the audit performs (it
    # resolves connectivity through the net/driver graph, never through a
    # net's literal name).
    tmx = ["dchain_tmx_notouch_%d" % i for i in range(7)]
    leaf = [(0, 1), (2, 3), (4, 5), (6, 7)]
    for k, (a, b) in enumerate(leaf):
        g.inst(pvlib.MUX2, "%s.tm%d_notouch_" % (d, k), I0=dch[pvlib.TAPPOS[a]], I1=dch[pvlib.TAPPOS[b]],
               S="tap_sel0", Z=tmx[k])
    combine = [(4, 0, 1), (5, 2, 3), (6, 4, 5)]
    for k, a, b in combine:
        g.inst(pvlib.MUX2, "%s.tm%d_notouch_" % (d, k), I0=tmx[a], I1=tmx[b], S="tap_sel1", Z=tmx[k])
    g.inst(pvlib.NAND2, "%s.dfbg_notouch_" % d, A1=tmx[6], A2=ring_en, ZN=dfb)
    g.inst(pvlib.INV1, "%s.dtap_notouch_" % d, I=dfb, ZN="dchain_ring_out_dummy")

    # ---- fmax ----
    f = pvlib.FMAX
    launch_d = "fmax_launch_d"
    g.inst(pvlib.DFFRN, "%s.flaunch_keep_" % f, D=launch_d, CLK="clk", RN="rst_n", Q=launch)
    for k in range(8):
        g.inst(pvlib.DFFRN, "%s.g_cap[%d].fcap_keep_" % (f, k),
               D=dch[pvlib.TAPPOS[k]], CLK="clk", RN="rst_n", Q="fmax_capq_dummy_%d" % k)

    return g


def _audit(g):
    nl = pvlib.parse_verilog(g.render(), top="top")
    return na.audit_netlist(nl, "self-test")


def run():
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("PASS" if cond else "FAIL") + " - " + name)
        ok = ok and cond

    # 1. Golden netlist must be completely clean.
    golden = build_golden()
    F = _audit(golden)
    if F.fails():
        for item in F.fails()[:10]:
            print("    unexpected finding:", item["category"], "-", item["msg"])
    check("golden netlist has zero FAIL findings (%d found)" % len(F.fails()), len(F.fails()) == 0)

    # 2. Resize: bump one PUF ring's stage 5 INV1 -> INV2. Must be caught as 'resize'.
    g2 = build_golden()
    victim = "g_puf[3].u_ring.g_stg[5].stg_notouch_"
    inst = g2.get(victim)
    inst.cell = pvlib.LIB + "inv_2"
    F2 = _audit(g2)
    resize_hits = [x for x in F2.fails() if x["category"] == "resize"]
    check("resized stage (inv_1 -> inv_2) is caught as a 'resize' FAIL", len(resize_hits) >= 1)

    # 3. Insertion: splice a spurious buffer into the NAND ring's enable fanout
    #    (stage 0's A2 now goes through an unnamed inserted buffer instead of
    #    tying directly to en_buf_notouch_). Must be caught (enable fanout
    #    mismatch and/or unexpected_driver on the notouch_ net it bypasses).
    g3 = build_golden()
    stage0 = g3.get("u_ring_nand.g_stg[0].stg_notouch_")
    orig_en = stage0.pins["A2"]           # u_ring_nand_en_buf_notouch
    sneak_net = "u_ring_nand_sneaky_inserted_notouch"
    stage0.pins["A2"] = sneak_net
    g3.inst(pvlib.BUF1, "u_ring_nand.g_stg[0].sneaky_clone_buf", I=orig_en, Z=sneak_net)
    F3 = _audit(g3)
    insertion_hits = [x for x in F3.fails() if x["category"] in ("enable_wiring", "unexpected_driver")]
    check("inserted buffer on en_buf_notouch_ fanout is caught (enable_wiring / unexpected_driver)",
          len(insertion_hits) >= 1)

    # 4. Deleted stage: remove PUF ring 7's stage 12 entirely and rewire stage 13
    #    to take its input straight from stage 11 (collapsed loop). Must be
    #    caught as a missing stage AND/OR a loop_connectivity break.
    g4 = build_golden()
    prefix = "g_puf[7].u_ring"
    fp = _flat(prefix)
    g4.remove("%s.g_stg[12].stg_notouch_" % prefix)
    stg13 = g4.get("%s.g_stg[13].stg_notouch_" % prefix)
    stg13.pins["I"] = "%s_ring_notouch_11" % fp   # was stage 12's output
    F4 = _audit(g4)
    stage_hits = [x for x in F4.fails() if x["category"] in ("stage_count", "loop_connectivity")]
    check("deleted ring stage 12 is caught (stage_count / loop_connectivity)", len(stage_hits) >= 1)

    # 5. Mis-wired Fmax tap: fcap_keep_[3] (should sample TAPPOS[3]=6) is
    #    rewired to sample chain stage 7 instead. Must be caught as
    #    'fmax_tap_wiring'.
    g5 = build_golden()
    cap3 = g5.get("u_fmax.g_cap[3].fcap_keep_")
    assert cap3.pins["D"] == "dchain_notouch_%d" % pvlib.TAPPOS[3]
    cap3.pins["D"] = "dchain_notouch_7"
    F5 = _audit(g5)
    tap_hits = [x for x in F5.fails() if x["category"] == "fmax_tap_wiring"]
    check("mis-wired fcap_keep_[3].D is caught as 'fmax_tap_wiring'", len(tap_hits) >= 1)

    print()
    print("SELF-TEST %s" % ("PASS" if ok else "FAIL"))
    return ok


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
