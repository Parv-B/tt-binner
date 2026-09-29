# SPDX-FileCopyrightText: © 2026 Parv Bhadra
# SPDX-License-Identifier: Apache-2.0
"""Measurement controller, counters and status (SPEC section 5).

Most tests here use the clk/2 source and dead sources only, so they are
gate-level safe: no ring is ever enabled. A few (marked rtl_only) exercise a
real behavioural ring, e.g. to force a counter overflow.
"""

import cocotb
from binner_tb import (
    CMD, CTRL, C_FREE, C_RUN, C_UIOOE, DBG_CNTA_H, DEAD_SRCS, K_CLEAR,
    K_START, S_BUSY, S_DONE, S_OVF_A, S_OVF_B, S_SEEN_A, S_SEEN_B, S_TIMEOUT,
    SRCA, SRCB, SRC_CLK2, STATUS, TB, gate_len, gl_safe, rtl_only,
)
from cocotb.triggers import FallingEdge, RisingEdge


def exp_clk2(gexp):
    return gate_len(gexp) / 2


@gl_safe
async def test_clk2_known_answer(dut):
    """Source 20 (clk/2) on both channels: CNT = gate/2 +-1 for GEXP = 0..15."""
    tb = TB(dut, "test_clk2_known_answer")
    await tb.start(period_ns=20.0)
    await tb.wr(SRCA, SRC_CLK2, SRC_CLK2)
    for gexp in range(16):
        st, ca, cb = await tb.measure(gexp=gexp)
        e = exp_clk2(gexp)
        tb.log.info(f"GEXP={gexp:2d} gate={gate_len(gexp):5d}: STATUS={st:#04x} CNTA={ca} CNTB={cb} (expect {e})")
        assert st & (S_BUSY | S_DONE) == S_DONE, f"GEXP={gexp}: STATUS={st:#04x} not DONE/idle"
        assert abs(ca - e) <= 1 and abs(cb - e) <= 1, f"GEXP={gexp}: CNTA={ca} CNTB={cb}, expected {e}+-1"
        assert abs(ca - cb) <= 1, f"GEXP={gexp}: channels disagree CNTA={ca} CNTB={cb}"
        assert not st & (S_OVF_A | S_OVF_B | S_TIMEOUT), f"GEXP={gexp}: OVF/TIMEOUT set, STATUS={st:#04x}"
        if ca > 0:
            assert st & S_SEEN_A, f"GEXP={gexp}: CNTA={ca} but SEEN_A=0"
        if cb > 0:
            assert st & S_SEEN_B, f"GEXP={gexp}: CNTB={cb} but SEEN_B=0"
        if gexp >= 3:   # gate >= 8: certainly long enough for the ack round trip
            assert st & (S_SEEN_A | S_SEEN_B) == S_SEEN_A | S_SEEN_B, f"GEXP={gexp}: SEEN bits {st:#04x}"


async def edge_time(sig, rising=True):
    await (RisingEdge(sig) if rising else FallingEdge(sig))
    return TB.now_fs()


@gl_safe
async def test_done_busy_timing(dut):
    """BUSY (STATUS[0], uo_out[4]) is high for gate + ~10 cycles; DONE (STATUS[1],
    uo_out[6]) rises as BUSY falls, stays until the next START, which clears it."""
    tb = TB(dut, "test_done_busy_timing")
    await tb.start()
    await tb.wr(SRCA, SRC_CLK2, SRC_CLK2)
    for gexp in (0, 4, 6, 9):
        g = gate_len(gexp)
        await tb.set_timing(gexp=gexp)
        t_busy = cocotb.start_soon(edge_time(dut.busy_pin, True))
        t_idle = cocotb.start_soon(edge_time(dut.busy_pin, False))
        t_done = cocotb.start_soon(edge_time(dut.done_pin, True))
        await tb.wr(CMD, K_START)
        await tb.wait_done(g + 400)
        tb_, ti, td = await t_busy, await t_idle, await t_done
        busy_cycles = (ti - tb_) / tb.tclk_fs
        tb.log.info(f"GEXP={gexp} gate={g}: BUSY for {busy_cycles:.1f} cycles")
        assert ti == td, f"GEXP={gexp}: DONE rose at {td} fs but BUSY fell at {ti} fs"
        assert g + 2 <= busy_cycles <= g + 20, f"GEXP={gexp}: BUSY lasted {busy_cycles} cycles (spec: gate + ~10)"
        st = await tb.rd(STATUS)
        assert st & (S_BUSY | S_DONE) == S_DONE and tb.pin("done_pin") == 1 and tb.pin("busy_pin") == 0
    # DONE persists.
    await tb.cycles(500)
    assert tb.pin("done_pin") == 1 and (await tb.rd(STATUS)) & S_DONE, "DONE must be sticky until next START"
    # Mid-measurement: BUSY=1, DONE=0 in STATUS and on the pins.
    await tb.set_timing(gexp=12)   # gate = 4096
    await tb.wr(CMD, K_START)
    st = await tb.rd(STATUS)
    assert st & (S_BUSY | S_DONE) == S_BUSY, f"during measurement STATUS={st:#04x}"
    assert tb.pin("busy_pin") == 1 and tb.pin("done_pin") == 0
    await tb.wait_done(4096 + 400)


@gl_safe
async def test_counters_static_after_done(dut):
    """CNTA/CNTB are the ring-domain counters themselves (SPEC section 4/5): from
    DONE until the next START/CLEAR they must read back identically on repeated
    SPI reads, however many times and however long after DONE."""
    tb = TB(dut, "test_counters_static_after_done")
    await tb.start(period_ns=20.0)
    st, ca, cb = await tb.measure(SRC_CLK2, SRC_CLK2, gexp=10)   # gate 1024
    assert st & S_DONE and ca > 0 and cb > 0
    for i in range(8):
        await tb.cycles(tb.rng.randrange(1, 500))
        st2, ca2, cb2 = await tb.read_result()
        assert (st2 & 0xFF, ca2, cb2) == (st, ca, cb), (
            f"read {i}: STATUS/CNTA/CNTB drifted after DONE: "
            f"({st2:#04x},{ca2},{cb2}) != ({st:#04x},{ca},{cb})")
    # A fresh START (different gate, so a different expected count) changes them;
    # CLEAR zeroes them.
    st3, ca3, cb3 = await tb.measure(SRC_CLK2, SRC_CLK2, gexp=6)   # gate 64
    assert (ca3, cb3) != (ca, cb), f"CNTA/CNTB did not change after a new START: {(ca3, cb3)}"
    await tb.wr(CMD, K_CLEAR)
    st4, ca4, cb4 = await tb.read_result()
    assert (st4 & 0x7F, ca4, cb4) == (0, 0, 0), f"CLEAR did not zero CNTA/CNTB: {st4:#04x} {ca4} {cb4}"


@gl_safe
async def test_dead_sources(dut):
    """Sources 21..31 (constant 0) and a disabled ring (RUN=0): SEEN=0, CNT=0,
    measurement still completes without TIMEOUT (SPEC: 16-cycle fixed wait for
    an unseen channel)."""
    tb = TB(dut, "test_dead_sources")
    await tb.start(period_ns=20.0)
    for s in DEAD_SRCS:
        st, ca, cb = await tb.measure(s, SRC_CLK2, gexp=7, extra_cycles=100)   # gate 128
        assert st & (S_DONE | S_BUSY | S_TIMEOUT) == S_DONE, f"A={s}: STATUS={st:#04x}"
        assert not st & S_SEEN_A and st & S_SEEN_B, f"A={s}: SEEN bits wrong, STATUS={st:#04x}"
        assert ca == 0 and abs(cb - 64) <= 1, f"A={s}: CNTA={ca} CNTB={cb}"
        st, ca, cb = await tb.measure(SRC_CLK2, s, gexp=7, extra_cycles=100)
        assert not st & S_SEEN_B and st & S_SEEN_A, f"B={s}: SEEN bits wrong, STATUS={st:#04x}"
        assert cb == 0 and abs(ca - 64) <= 1, f"B={s}: CNTA={ca} CNTB={cb}"
    # Both dead, and rings selected with CTRL.RUN = 0 (rings off -> dead).
    for a, b in ((21, 31), (0, 8), (16, 19), (18, 17)):
        st, ca, cb = await tb.measure(a, b, gexp=8, extra_cycles=100)   # gate 256
        assert st & (S_DONE | S_BUSY | S_TIMEOUT | S_SEEN_A | S_SEEN_B) == S_DONE, f"A={a},B={b}: STATUS={st:#04x}"
        assert ca == 0 and cb == 0, f"A={a},B={b}: CNTA={ca} CNTB={cb}"


@gl_safe
async def test_start_clears_previous_status(dut):
    """A new START clears DONE/SEEN/TIMEOUT of the previous measurement."""
    tb = TB(dut, "test_start_clears_previous_status")
    await tb.start(period_ns=20.0)
    st, _, _ = await tb.measure(SRC_CLK2, SRC_CLK2, gexp=9)
    assert st & (S_SEEN_A | S_SEEN_B) == S_SEEN_A | S_SEEN_B
    st, ca, cb = await tb.measure(21, 22, gexp=9)
    assert st & (S_SEEN_A | S_SEEN_B) == 0 and ca == 0 and cb == 0, f"stale status: {st:#04x} {ca} {cb}"


@gl_safe
async def test_clear_during_run(dut):
    """CMD.CLEAR while BUSY aborts: BUSY/DONE/SEEN/OVF/TIMEOUT and counters cleared,
    no late DONE, and the next measurement is correct. CLEAR when idle clears too."""
    tb = TB(dut, "test_clear_during_run")
    await tb.start()
    st, ca, cb = await tb.measure(SRC_CLK2, SRC_CLK2, gexp=10)   # gate 1024
    assert st & S_DONE and ca > 0 and cb > 0
    await tb.set_timing(gexp=13)   # gate 8192
    await tb.wr(CMD, K_START)
    await tb.cycles(1500)
    assert tb.pin("busy_pin") == 1
    await tb.wr(CMD, K_CLEAR)
    assert tb.pin("busy_pin") == 0 and tb.pin("done_pin") == 0, "CLEAR did not abort"
    st, ca, cb = await tb.read_result()
    assert (st & 0x7F, ca, cb) == (0, 0, 0), f"after CLEAR: STATUS={st:#04x} CNTA={ca} CNTB={cb}"
    await tb.cycles(8000)   # past the original gate end: nothing may complete
    assert tb.pin("done_pin") == 0 and tb.pin("busy_pin") == 0, "aborted measurement completed later"
    assert await tb.rd(STATUS) & 0x7F == 0
    st, ca, cb = await tb.measure(gexp=9)   # gate 512
    assert st & S_DONE and abs(ca - 256) <= 1 and abs(cb - 256) <= 1, f"after CLEAR: {st:#04x} {ca} {cb}"
    # CLEAR when idle.
    await tb.wr(CMD, K_CLEAR)
    st, ca, cb = await tb.read_result()
    assert (st & 0x7F, ca, cb) == (0, 0, 0), f"idle CLEAR: STATUS={st:#04x} CNTA={ca} CNTB={cb}"


@gl_safe
async def test_start_while_busy_ignored(dut):
    """START during a measurement is ignored: DONE arrives at the time set by the
    first START, the result covers the first gate, and nothing is queued."""
    tb = TB(dut, "test_start_while_busy_ignored")
    await tb.start()
    gexp = 12
    g = gate_len(gexp)
    await tb.wr(SRCA, SRC_CLK2, SRC_CLK2)
    await tb.set_timing(gexp=gexp)
    t_busy = cocotb.start_soon(edge_time(dut.busy_pin, True))
    t_done = cocotb.start_soon(edge_time(dut.done_pin, True))
    await tb.wr(CMD, K_START)
    await tb.cycles(1000)
    await tb.wr(CMD, K_START)
    await tb.cycles(1000)
    await tb.wr(CMD, K_START)
    await tb.wait_done(g + 400)
    dur = (await t_done - await t_busy) / tb.tclk_fs
    assert g + 2 <= dur <= g + 20, f"DONE {dur} cycles after BUSY rose: a re-START restarted the measurement"
    st, ca, cb = await tb.read_result()
    assert abs(ca - g / 2) <= 1 and abs(cb - g / 2) <= 1, f"CNTA={ca} CNTB={cb}"
    await tb.cycles(200)
    assert tb.pin("busy_pin") == 0 and tb.pin("done_pin") == 1, "a START issued while busy was queued"


@gl_safe
async def test_free_mode_clk2(dut):
    """CTRL.FREE: counters run continuously; uo_out[1]/[2] = counter bit PINDIV,
    i.e. source / 2^(PINDIV+1). Clearing FREE stops the counters."""
    tb = TB(dut, "test_free_mode_clk2")
    await tb.start(period_ns=20.0)
    await tb.wr(SRCA, SRC_CLK2, SRC_CLK2)
    await tb.wr(CTRL, C_FREE)
    for p in (0, 1, 2, 3, 5, 7):
        await tb.set_timing(pindiv=p)
        exp = 2 * (2 ** (p + 1)) * tb.tclk_fs
        for sig in (dut.cha_div, dut.chb_div):
            per = await tb.period_of(sig, 4, 20 * exp)
            assert per == exp, f"PINDIV={p}: {sig._name} period {per / 1e6} ns, expected {exp / 1e6} ns"
    # The live counter (debug select 7 = CNTA[15:8]) is moving.
    await tb.set_timing(pindiv=0)
    srcb_base = await tb.rd(SRCB)
    await tb.wr(SRCB, (srcb_base & 0x1F) | (DBG_CNTA_H << 5))
    await tb.wr(CTRL, C_FREE | C_UIOOE)
    vals = set()
    for _ in range(5):
        await tb.cycles(300)
        vals.add(int(dut.uio_out.value))
    assert len(vals) > 1, "FREE mode counter not counting"
    await tb.wr(CTRL, 0)
    await tb.cycles(20)
    a, b = tb.pin("cha_div"), tb.pin("chb_div")
    await tb.cycles(200)
    assert (tb.pin("cha_div"), tb.pin("chb_div")) == (a, b), "counters still running after FREE cleared"
    await tb.wr(SRCB, srcb_base)
    await tb.set_timing(pindiv=5)


@gl_safe
async def test_timeout_free_mode(dut):
    """In FREE mode the counters never stop, so the acknowledge never falls: the
    controller must capture anyway after 63 cycles and flag TIMEOUT (SPEC 5)."""
    tb = TB(dut, "test_timeout_free_mode")
    await tb.start()
    await tb.wr(SRCA, SRC_CLK2, SRC_CLK2)
    await tb.set_timing(gexp=6)   # gate 64
    await tb.wr(CTRL, C_FREE)
    t_busy = cocotb.start_soon(edge_time(dut.busy_pin, True))
    t_done = cocotb.start_soon(edge_time(dut.done_pin, True))
    await tb.wr(CMD, K_START)
    await tb.wait_done(500)
    dur = (await t_done - await t_busy) / tb.tclk_fs
    st = await tb.rd(STATUS)
    tb.log.info(f"FREE-mode START: STATUS={st:#04x}, BUSY {dur} cycles")
    assert st & S_TIMEOUT and st & S_DONE, f"STATUS={st:#04x}: TIMEOUT expected"
    assert 64 + 63 <= dur <= 64 + 63 + 20, f"timeout after {dur} cycles, expected gate + 63 + a few"
    await tb.wr(CTRL, 0)
    st, ca, cb = await tb.measure(gexp=6)
    assert not st & S_TIMEOUT and abs(ca - 32) <= 1, f"TIMEOUT not cleared by next START: {st:#04x} {ca}"


@rtl_only
async def test_overflow(dut):
    """A fast ring (default behavioural ~200 MHz) with a wide gate overflows the
    16-bit counter; OVF is set and sticky through STATUS/CNTA readback. The
    clk/2 channel over the same gate does not overflow."""
    tb = TB(dut, "test_overflow")
    await tb.start(period_ns=100.0)   # 10 MHz: gate 32768 cycles = 3.28 ms real time
    st, ca, cb = await tb.measure(0, SRC_CLK2, gexp=15, ctrl=C_RUN, extra_cycles=400)
    tb.log.info(f"overflow test: STATUS={st:#04x} CNTA={ca} CNTB={cb}")
    assert st & S_OVF_A, f"ring source did not overflow the counter: STATUS={st:#04x} CNTA={ca}"
    assert st & S_SEEN_A, "overflowed channel must still be SEEN"
    assert not st & S_OVF_B, f"clk/2 channel should not overflow: STATUS={st:#04x} CNTB={cb}"
    assert abs(cb - gate_len(15) / 2) <= 1, f"CNTB={cb}, expected {gate_len(15) / 2}"
