# SPDX-FileCopyrightText: © 2026 Parv Bhadra
# SPDX-License-Identifier: Apache-2.0
"""LFSR (SPEC section 7): exhaustive model proof and RTL known answers.

v0.2 note: the gate is TIMING.GEXP (gate = 2**GEXP, GEXP in 0..15), not a free
16-bit GATE register, so a single gated measurement can only advance the LFSR
by a power of two. `lfsr_advance_gated()` composes an arbitrary N (0..65535)
from consecutive un-reseeded gated measurements, one per set bit of N's binary
representation -- the LFSR keeps stepping from wherever it is between STARTs
(LFSR_GATED stays 1, no RESEED in between), so this is a legitimate sequence
of real gated measurements, not a shortcut around the hardware.
"""

from binner_tb import (
    C_LFSR_GATED, C_LFSR_RUN, CMD, CTRL, K_RESEED, K_START, LFSR_L, LFSR_SEED,
    S_DONE, SRC_CLK2, SRCA, TB, gate_len, gl_safe, lfsr_advance, lfsr_distance,
    lfsr_next,
)
from cocotb.triggers import FallingEdge

# ---------------------------------------------------------------------------
# Pure-model proofs (no simulation needed; run inside the cocotb regression so
# they are part of `make`, and also importable by pytest).
# ---------------------------------------------------------------------------


def prove_lfsr_period():
    """All 65536 states are on one cycle (period 65536) -> no lock-up state."""
    # 1. The successor function is a bijection on 16-bit states.
    succ = [lfsr_next(q) for q in range(65536)]
    assert len(set(succ)) == 65536, "next() is not a bijection"
    # 2. Walking from the seed visits every state exactly once and returns after 65536 steps.
    seen = bytearray(65536)
    q = LFSR_SEED
    for n in range(65536):
        assert not seen[q], f"state {q:#06x} revisited after {n} steps (period < 65536)"
        seen[q] = 1
        q = succ[q]
    assert q == LFSR_SEED, "did not return to seed after 65536 steps"
    assert all(seen), "some state never visited"
    # 3. The underlying plain LFSR (no zero insertion) is maximal: period 65535,
    #    confirming the polynomial is primitive; 0x0000 is its lock-up state.
    q, n = LFSR_SEED, 0
    while True:
        q = lfsr_next(q, debruijn=False)
        n += 1
        if q == LFSR_SEED:
            break
        assert n <= 65535
    assert n == 65535, f"plain LFSR period {n}, expected 65535"
    assert lfsr_next(0, debruijn=False) == 0
    # 4. The splice: 0x8000 -> 0x0000 -> 0x0001 (plain: 0x8000 -> 0x0001).
    assert lfsr_next(0x8000) == 0x0000 and lfsr_next(0x0000) == 0x0001
    assert lfsr_next(0x8000, debruijn=False) == 0x0001
    return True


def test_lfsr_model_pytest():
    """pytest entry point for the pure model proof."""
    assert prove_lfsr_period()


@gl_safe
async def test_lfsr_model_period(dut):
    """Model: period 65536, single cycle through all states, no lock-up."""
    assert prove_lfsr_period()
    d = lfsr_distance(LFSR_SEED, 0x8000)
    dut._log.info(f"steps from 0xACE1 to 0x8000 = {d} (splice)")


async def lfsr_kat_pow2(tb, k):
    """SPEC 7 known answer, literal procedure: RESEED, LFSR_GATED, TIMING.GEXP=k,
    CMD.START -> state after 2**k gated steps."""
    await tb.wr(CMD, K_RESEED)
    assert await tb.rd16(LFSR_L) == LFSR_SEED, "LFSR_RESEED did not load 0xACE1"
    await tb.wr(CTRL, C_LFSR_GATED)
    await tb.wr(SRCA, SRC_CLK2, SRC_CLK2)
    await tb.set_timing(gexp=k)
    await tb.wr(CMD, K_START)
    await tb.wait_done(gate_len(k) + 400)
    got = await tb.rd16(LFSR_L)
    await tb.wr(CTRL, 0)
    return got


async def lfsr_advance_gated(tb, n, reseed=True):
    """Advance the RTL LFSR by exactly n gated steps (0 <= n <= 65535), composed
    from one un-reseeded gated measurement per set bit of n (binary decomposition:
    GEXP = bit index, so each measurement contributes 2**bit steps)."""
    if reseed:
        await tb.wr(CMD, K_RESEED)
    await tb.wr(CTRL, C_LFSR_GATED)
    await tb.wr(SRCA, SRC_CLK2, SRC_CLK2)
    remaining, k = n, 0
    while remaining:
        if remaining & 1:
            await tb.set_timing(gexp=k)
            await tb.wr(CMD, K_START)
            await tb.wait_done(gate_len(k) + 400)
        remaining >>= 1
        k += 1
    got = await tb.rd16(LFSR_L)
    await tb.wr(CTRL, 0)
    return got


@gl_safe
async def test_lfsr_known_answer(dut):
    """Literal SPEC procedure: TIMING.GEXP=k, CMD.START, for every k = 0..15."""
    tb = TB(dut, "test_lfsr_known_answer")
    await tb.start(period_ns=20.0)   # 50 MHz: long gates are cheap in sim time
    for k in range(16):
        got = await lfsr_kat_pow2(tb, k)
        exp = lfsr_advance(LFSR_SEED, gate_len(k))
        assert got == exp, f"LFSR after 2**{k}={gate_len(k)} gated steps: {got:#06x}, expected {exp:#06x}"


@gl_safe
async def test_lfsr_arbitrary_advance(dut):
    """Composed (binary-decomposed) gated advance for arbitrary N, including the
    values the original raw-GATE known-answer used (SPEC v0.1 compatibility check
    of the underlying stepping, now expressed as v0.2 GEXP measurements)."""
    tb = TB(dut, "test_lfsr_arbitrary_advance")
    await tb.start(period_ns=20.0)
    ns = [0, 1, 2, 3, 15, 16, 17, 100, 1000, 4097, tb.rng.randrange(1, 65536)]
    for n in ns:
        got = await lfsr_advance_gated(tb, n)
        exp = lfsr_advance(LFSR_SEED, n)
        assert got == exp, f"LFSR after N={n} gated steps: {got:#06x}, expected {exp:#06x}"


@gl_safe
async def test_lfsr_splice_known_answer(dut):
    """Cross the de Bruijn splice 0x8000 -> 0x0000 -> 0x0001 in RTL/GL, using
    composed gated steps (the splice distance from the seed, 39191, exceeds the
    32768 max of a single GEXP=15 measurement)."""
    tb = TB(dut, "test_lfsr_splice_known_answer")
    await tb.start(period_ns=20.0)
    d = lfsr_distance(LFSR_SEED, 0x8000)
    assert d is not None
    for n, exp in ((d, 0x8000), (d + 1, 0x0000), (d + 2, 0x0001), (d + 3, lfsr_next(1))):
        got = await lfsr_advance_gated(tb, n)
        assert got == exp, f"N={n}: LFSR {got:#06x}, expected {exp:#06x}"
    # 65535 steps (max representable N): one step short of the full period.
    got = await lfsr_advance_gated(tb, 65535)
    exp = lfsr_advance(LFSR_SEED, 65535)
    assert got == exp and lfsr_next(got) == LFSR_SEED, f"N=65535: {got:#06x}, expected {exp:#06x}"


async def capture_stream(tb, n):
    """Sample uo_out[0] once per clk cycle (at the falling edge). No ReadOnly()
    here: the signal is driven purely by the DUT's hardware (no other
    coroutine races it this cycle), and parking the coroutine in the ReadOnly
    phase would make the caller's very next register write raise
    "settings a value during the ReadOnly phase" in cocotb 2.x."""
    out = []
    for _ in range(n):
        await FallingEdge(tb.dut.clk)
        out.append(tb.pin("lfsr_pin"))
    return out


def check_stream(bitstream, where):
    """uo_out[0] = state[15]; state(t) = bits b[t..t+15] (q15..q0), since the
    register shifts left. Stepping every clk means state(t+1) = next(state(t))."""
    assert len(bitstream) >= 48
    s0 = 0
    for b in bitstream[:16]:
        s0 = (s0 << 1) | b
    q = s0
    for t in range(1, len(bitstream) - 15):
        q = lfsr_next(q)
        exp_bit = (q >> 15) & 1
        assert bitstream[t] == exp_bit, f"{where}: uo_out[0] at cycle {t} = {bitstream[t]}, model {exp_bit}"
    return s0


@gl_safe
async def test_lfsr_free_run_pin(dut):
    """CTRL.LFSR_RUN: steps every clk; uo_out[0] == state[15]; stops when cleared."""
    tb = TB(dut, "test_lfsr_free_run_pin")
    await tb.start()
    await tb.wr(CMD, K_RESEED)
    before = await tb.rd16(LFSR_L)
    assert before == LFSR_SEED
    assert await tb.rd16(LFSR_L) == before, "LFSR must not step when disabled"
    assert tb.pin("lfsr_pin") == 1, "uo_out[0] = bit 15 of 0xACE1 = 1"
    await tb.wr(CTRL, C_LFSR_RUN)
    stream = await capture_stream(tb, 200)
    s0 = check_stream(stream, "LFSR_RUN")
    d = lfsr_distance(LFSR_SEED, s0, limit=5000)
    assert d is not None, f"stream start state {s0:#06x} not reachable from seed"
    await tb.wr(CTRL, 0)
    q1 = await tb.rd16(LFSR_L)
    assert await tb.rd16(LFSR_L) == q1, "LFSR still stepping after LFSR_RUN cleared"
    assert (q1 >> 15) == tb.pin("lfsr_pin"), "uo_out[0] != LFSR[15]"
    # The stopped state lies ahead of the stream on the same sequence.
    dd = lfsr_distance(s0, q1, limit=20000)
    assert dd is not None and dd >= 200, f"final state {q1:#06x} not downstream of stream (distance {dd})"


@gl_safe
async def test_lfsr_pinmode_steps(dut):
    """Pin-strap mode: LFSR steps every clk without SPI. (ena=0 keeps rings off, so
    this is gate-level safe.)"""
    tb = TB(dut, "test_lfsr_pinmode_steps")
    await tb.start(ena=0)
    tb.set_pinmode(1, sel=4, bank=1)    # A = source 20 (clk/2), rings off with ena=0
    await tb.cycles(4)
    stream = await capture_stream(tb, 120)
    check_stream(stream, "pin mode")
    tb.set_pinmode(0)
    await tb.cycles(4)
    q1 = await tb.rd16(LFSR_L)
    assert await tb.rd16(LFSR_L) == q1, "LFSR still stepping after leaving pin mode"


@gl_safe
async def test_lfsr_gated_only_during_run(dut):
    """LFSR_GATED without START does not step; only the RUN window steps it."""
    tb = TB(dut, "test_lfsr_gated_only_during_run")
    await tb.start()
    await tb.wr(CMD, K_RESEED)
    await tb.wr(CTRL, C_LFSR_GATED)
    await tb.cycles(200)
    assert await tb.rd16(LFSR_L) == LFSR_SEED, "LFSR_GATED stepped outside a measurement"
    st, _, _ = await tb.measure(SRC_CLK2, SRC_CLK2, gexp=5)   # 32 gated steps
    assert st & S_DONE
    await tb.cycles(200)
    assert await tb.rd16(LFSR_L) == lfsr_advance(LFSR_SEED, 32)
