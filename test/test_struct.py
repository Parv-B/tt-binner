# SPDX-FileCopyrightText: © 2026 Parv Bhadra
# SPDX-License-Identifier: Apache-2.0
"""Structural tests: `make struct` compiles project.v (and binner_ring.v /
binner_dchain.v / binner_fmax.v) WITHOUT -DBINNER_BEHAV, against the real
GF180MCU PDK cell models WITHOUT -DFUNCTIONAL, so every hand-instantiated cell
carries its real specify-block timing. In this PDK every comb/seq arc used
here (INV_1, NAND2_1, NOR2_1, BUF_1, DLYD_1, MUX2_2, DFFRNQ_1) is (1.0, 1.0) ns
-- verified directly against gf180mcu_fd_sc_mcu7t5v0.v, not assumed.

A ring built from N inverting stages in a loop, with exactly one net-list
inversion per lap (odd total inversions), oscillates with period 2*N*t_arc.
This is the only place BINNER's actual cell structure (not the behavioural
stand-in) is exercised in simulation: it is what proves the hand-instantiated
netlist -- including the new NAND-ring enable buffer -- actually does what
binner_ring.v's header comment and docs/SPEC.md v0.2 claim.

Not run in CI; `make struct` is a developer/verification-only target (real PDK
models, no dumb behavioural shortcut). SPI, the measurement controller, the
counters and the LFSR are ordinary synthesisable RTL with no ifdef branches,
so the usual TB() driver works unchanged here.
"""

import cocotb
from binner_tb import (
    CTRL, C_RUN, DEAD_SRCS, N_PUF_RINGS, SRCA, STAGE_COUNTS, SRC_DCHAIN,
    TAPPOS, TB, pack_srca,
)

T_ARC_NS = 1.0        # every comb/seq arc in this library, per the specify blocks
TOL_NS = 1.5           # a little slack for edge-alignment / mux settle


def ring_period_ns(n_stages):
    return 2 * n_stages * T_ARC_NS


def dchain_ring_period_ns(tappos):
    # loop = input mux (1) + tappos DLYD stages + 3-level tap-select mux + NAND2 (1)
    return 2 * (1 + tappos + 3 + 1) * T_ARC_NS


def ring_out_handle(dut, idx):
    up = dut.user_project
    if idx < N_PUF_RINGS:
        return up.g_puf[idx].u_ring.out
    return {16: up.u_ring_nand.out, 17: up.u_ring_nor.out, 18: up.u_ring_fo4.out}[idx]


async def enable_only(tb, src, dtap=0):
    await tb.wr(SRCA, pack_srca(src, dtap), DEAD_SRCS[0])
    await tb.wr(CTRL, C_RUN)
    await tb.cycles(2)


@cocotb.test()
async def test_struct_smoke(dut):
    """Register file / SPI / ID work identically in structural mode (no ifdef
    branches there): confirms the compile and reset are sane before any ring
    timing check runs."""
    tb = TB(dut, "test_struct_smoke")
    await tb.start(period_ns=100.0)
    ids = await tb.rd(0x00, 3)
    assert ids == [0x42, 0x4E, 0x02], f"ID/VER readback in structural mode: {ids}"
    assert int(dut.uio_oe.value) == 0


@cocotb.test()
async def test_ring_periods_all_kinds(dut):
    """Every ring's oscillation period is 2*N*1ns, N = its real stage count
    (STAGE_COUNTS): 25 for the INV/NAND/NOR rings, 13 for the FO4 ring
    (project.v N_FO4, reduced from 25 in v0.2). Includes the NAND ring
    (source 16): its en_buf_notouch_ BUF_1 sits on the enable input, off the
    loop path, so its period must equal the INV ring's (same N), proving the
    buffer adds nothing to the loop."""
    tb = TB(dut, "test_ring_periods_all_kinds")
    await tb.start(period_ns=100.0)
    periods = {}
    for idx in (0, 1, 16, 17, 18):
        await enable_only(tb, idx)
        sig = ring_out_handle(dut, idx)
        exp = ring_period_ns(STAGE_COUNTS[idx])
        per_fs = await tb.period_of(sig, 4, int((exp * 6) * 1e6))
        per_ns = per_fs / 1e6
        periods[idx] = per_ns
        tb.log.info(f"ring {idx} (N={STAGE_COUNTS[idx]}): period {per_ns:.2f} ns, expected {exp:.2f} ns")
        assert abs(per_ns - exp) <= TOL_NS, f"ring {idx}: period {per_ns:.2f} ns, expected {exp:.2f} ns"
    assert abs(periods[16] - periods[0]) <= TOL_NS, (
        f"NAND ring (buffered enable) period {periods[16]:.2f} ns != INV ring period {periods[0]:.2f} ns: "
        f"the enbuf_notouch_ stage must not add to the loop period")
    await tb.wr(CTRL, 0)


@cocotb.test()
async def test_ring_disabled_static_no_x(dut):
    """A disabled ring's output is resolvable (no X/Z) and constant over time,
    for one of every kind (INV, NAND, NOR, FO4, delay-chain)."""
    tb = TB(dut, "test_ring_disabled_static_no_x")
    await tb.start(period_ns=100.0)
    await tb.wr(SRCA, DEAD_SRCS[0], DEAD_SRCS[1])
    await tb.wr(CTRL, 0)
    await tb.cycles(5)
    sigs = [ring_out_handle(dut, i) for i in (0, 16, 17, 18)]
    sigs.append(dut.user_project.u_dchain.ring_out)
    before = []
    for s in sigs:
        v = s.value
        assert v.is_resolvable, f"{str(s)}: X/Z while disabled: {v}"
        before.append(int(v))
    await tb.cycles(2000)
    for s, b in zip(sigs, before):
        v = s.value
        assert v.is_resolvable, f"{str(s)}: X/Z appeared while disabled: {v}"
        assert int(v) == b, f"{str(s)}: value changed while disabled ({b} -> {int(v)})"


@cocotb.test()
async def test_dchain_ring_tap_periods(dut):
    """Source 19 (delay-chain ring): period = 2*(1 + stages + 3 + 1)*1ns for
    every DTAP (SRCA[7:5]) 0..7, i.e. stage counts 3,4,5,6,8,10,12,14."""
    tb = TB(dut, "test_dchain_ring_tap_periods")
    await tb.start(period_ns=100.0)
    for k, stages in enumerate(TAPPOS):
        await enable_only(tb, SRC_DCHAIN, dtap=k)
        sig = dut.user_project.u_dchain.ring_out
        exp = dchain_ring_period_ns(stages)
        per_fs = await tb.period_of(sig, 4, int(exp * 8 * 1e6))
        per_ns = per_fs / 1e6
        tb.log.info(f"dchain tap {k} (stages={stages}): period {per_ns:.2f} ns, expected {exp:.2f} ns")
        assert abs(per_ns - exp) <= TOL_NS, f"tap {k}: period {per_ns:.2f} ns, expected {exp:.2f} ns"
    await tb.wr(CTRL, 0)
