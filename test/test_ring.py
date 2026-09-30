# SPDX-FileCopyrightText: © 2026 Parv Bhadra
# SPDX-License-Identifier: Apache-2.0
"""Ring gating (SPEC section 5): `ren[gi] = run & ((SRCA==gi) | (SRCB==gi))`,
`run = ena & (CTRL.RUN | PINMODE)`.

RTL-only: gate-level simulation never enables a ring. The NAND ring's new
en_buf_notouch_ buffer (project.v / binner_ring.v KIND==1, added to fix
RSZ-3006) only exists in the physical (non-BINNER_BEHAV) netlist, so this file
checks end-to-end that enabling/disabling source 16 (NAND ring) still starts
and stops oscillation correctly; the buffer's *structural* placement and its
zero contribution to the loop period are checked separately by `make struct`
(test_struct.py), where the buffer actually exists in the simulated netlist.
"""

from binner_tb import (
    CMD, CTRL, C_RUN, DEAD_SRCS, K_START, N_RINGS, SRCA, SRC_DCHAIN,
    SRC_NAND, S_DONE, S_SEEN_A, S_SEEN_B, TAPPOS, TB, chain_ring_freq_hz,
    gate_len, pack_srca, read_ring_enables, ring_freq_hz, rtl_only,
)

GEXP = 10           # gate = 1024 clk cycles
CLK_NS = 13.0        # deliberately off the rings' ~200 MHz nominal frequency
TOL = 4              # count tolerance: CDC start/stop is +-1 src_clk edge each way


def expected_count(freq_hz, gate_cycles, tclk_fs):
    gate_s = gate_cycles * tclk_fs * 1e-15
    return freq_hz * gate_s


@rtl_only
async def test_ring_enable_sweep(dut):
    """Hierarchical probe of all 20 ring `en` inputs across a sweep of
    SRCA/SRCB/CTRL.RUN/ena: enabled set == {SRCA,SRCB} & [0,19] iff run; at
    most two enabled; ena=0 or CTRL.RUN=0 -> none."""
    tb = TB(dut, "test_ring_enable_sweep")
    await tb.start()

    async def check(srca, srcb, run, ena, where):
        dut.ena.value = ena
        await tb.wr(SRCA, srca, srcb)
        await tb.wr(CTRL, C_RUN if run else 0)
        await tb.cycles(2)
        en = read_ring_enables(dut)
        assert sum(en) <= 2, f"{where}: more than two rings enabled: {en}"
        expect = set()
        if run and ena:
            if srca < 20:
                expect.add(srca)
            if srcb < 20:
                expect.add(srcb)
        got = {i for i, v in enumerate(en) if v}
        assert got == expect, f"{where}: SRCA={srca} SRCB={srcb} RUN={run} ena={ena}: enabled {got}, expected {expect}"

    combos = [
        (0, 8, 1, 1), (19, 0, 1, 1), (5, 5, 1, 1), (0, 19, 1, 1),
        (16, 17, 1, 1), (18, 19, 1, 1), (0, 8, 0, 1), (0, 8, 1, 0),
        (20, 21, 1, 1), (31, 20, 1, 1), (19, 19, 1, 1),
    ]
    combos += [(tb.rng.randrange(32), tb.rng.randrange(32), tb.rng.randrange(2), 1)
               for _ in range(12)]
    for srca, srcb, run, ena in combos:
        await check(srca, srcb, run, ena, f"combo({srca},{srcb},{run},{ena})")
    # Restore ena=1 (TB helpers assume it elsewhere) and rings off.
    dut.ena.value = 1
    await tb.wr(CTRL, 0)
    await tb.wr(SRCA, 0, 8)


@rtl_only
async def test_ring_ena_gates_everything(dut):
    """ena=0 disables every ring even with CTRL.RUN=1 and every SRCA/SRCB pair
    live over several cycles (not just a single sample)."""
    tb = TB(dut, "test_ring_ena_gates_everything")
    await tb.start()
    await tb.wr(SRCA, 3, 11)
    await tb.wr(CTRL, C_RUN)
    await tb.cycles(2)
    assert sum(read_ring_enables(dut)) == 2, "sanity: rings should be on with ena=1"
    dut.ena.value = 0
    for _ in range(20):
        await tb.cycles(5)
        assert read_ring_enables(dut) == [0] * 20, "a ring is enabled with ena=0"
    dut.ena.value = 1
    await tb.cycles(2)
    assert sum(read_ring_enables(dut)) == 2, "rings did not re-enable when ena returned to 1"
    await tb.wr(CTRL, 0)


async def _measure_ring(tb, srca, freq_hz, dtap=None):
    srca_byte = pack_srca(srca, dtap or 0)
    st, ca, cb = await tb.measure(srca_byte, DEAD_SRCS[0], gexp=GEXP, ctrl=C_RUN, extra_cycles=200)
    exp = expected_count(freq_hz, gate_len(GEXP), tb.tclk_fs)
    return st, ca, exp


@rtl_only
async def test_ring_oscillation_functional(dut):
    """Every ring source (0..18) oscillates only when selected+enabled, at
    (within tolerance) its plusarg-controlled behavioural frequency, and no
    other ring's `en` is asserted meanwhile -- including source 16 (NAND ring),
    whose enable now passes through the hand-instantiated BUF_1
    (en_buf_notouch_) rather than driving every stage's A2 pin directly."""
    tb = TB(dut, "test_ring_oscillation_functional")
    await tb.start(period_ns=CLK_NS)
    for idx in range(N_RINGS):   # 0..18: identical rings, NAND, NOR, FO4
        await tb.wr(SRCA, idx, DEAD_SRCS[0])
        await tb.wr(CTRL, C_RUN)
        await tb.wr(CMD, K_START)
        await tb.cycles(4)   # mid-measurement: confirm exactly one ring is enabled
        en = read_ring_enables(dut)
        assert en[idx] == 1 and sum(en) == 1, f"src {idx}: ring enables mid-run {en}"
        await tb.wait_done(gate_len(GEXP) + 200)
        st, ca, cb = await tb.read_result()
        exp = expected_count(ring_freq_hz(idx), gate_len(GEXP), tb.tclk_fs)
        assert st & S_DONE and st & S_SEEN_A, f"src {idx}: STATUS={st:#04x} (not seen)"
        assert not st & S_SEEN_B, f"src {idx}: dead channel B unexpectedly SEEN"
        assert abs(ca - exp) <= TOL, f"src {idx}: CNTA={ca}, expected {exp:.1f} +-{TOL}"
    await tb.wr(CTRL, 0)


@rtl_only
async def test_ring_at_most_two_with_both_channels_running(dut):
    """SRCA and SRCB select two different rings: both (and only both) oscillate,
    confirmed both structurally (en) and functionally (both SEEN, both counts
    consistent with their own frequency)."""
    tb = TB(dut, "test_ring_at_most_two_with_both_channels_running")
    await tb.start(period_ns=CLK_NS)
    pairs = [(0, 1), (16, 17), (18, 0), (SRC_DCHAIN, SRC_NAND)]
    for a, b in pairs:
        await tb.wr(SRCA, a, b)
        await tb.wr(CTRL, C_RUN)
        await tb.wr(CMD, K_START)
        await tb.cycles(4)
        en = read_ring_enables(dut)
        assert en[a] == 1 and en[b] == 1 and sum(en) == 2, f"pair {(a, b)}: ring enables {en}"
        await tb.wait_done(gate_len(GEXP) + 200)
        st, ca, cb = await tb.read_result()
        assert st & (S_SEEN_A | S_SEEN_B) == S_SEEN_A | S_SEEN_B, f"pair {(a, b)}: STATUS={st:#04x}"
        fa = chain_ring_freq_hz(0) if a == SRC_DCHAIN else ring_freq_hz(a)
        fb = chain_ring_freq_hz(0) if b == SRC_DCHAIN else ring_freq_hz(b)
        expa = expected_count(fa, gate_len(GEXP), tb.tclk_fs)
        expb = expected_count(fb, gate_len(GEXP), tb.tclk_fs)
        assert abs(ca - expa) <= TOL, f"pair {(a, b)}: CNTA={ca}, expected {expa:.1f}"
        assert abs(cb - expb) <= TOL, f"pair {(a, b)}: CNTB={cb}, expected {expb:.1f}"
    await tb.wr(CTRL, 0)


@rtl_only
async def test_dchain_ring_taps(dut):
    """Source 19 (delay-chain ring): frequency ~ 1/(2*(overhead + chain(tap)))
    for every DTAP (SRCA[7:5]) 0..7, i.e. stage counts 3,4,5,6,8,10,12,14."""
    tb = TB(dut, "test_dchain_ring_taps")
    await tb.start(period_ns=CLK_NS)
    for k in range(8):
        st, ca, exp = await _measure_ring(tb, SRC_DCHAIN, chain_ring_freq_hz(k), dtap=k)
        assert st & S_DONE and st & S_SEEN_A, f"tap {k} (stage {TAPPOS[k]}): STATUS={st:#04x}"
        assert abs(ca - exp) <= TOL, f"tap {k} (stage {TAPPOS[k]}): CNTA={ca}, expected {exp:.1f} +-{TOL}"
    await tb.wr(CTRL, 0)
