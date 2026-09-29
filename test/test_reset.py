# SPDX-FileCopyrightText: © 2026 Parv Bhadra
# SPDX-License-Identifier: Apache-2.0
"""Reset behaviour (SPEC sections 2 and 4)."""

from binner_tb import (
    CMD, CTRL, K_START, MISC, M_ENA, RO_RESET, RW_REGS, SRCA, SRC_CLK2,
    STATUS, S_BUSY, S_DONE, TB, TIMING, gl_safe, read_ring_enables, rtl_only,
)
import cocotb
from cocotb.triggers import Timer

# uo_out after reset, derived from SPEC section 1 / 4:
#   [0] LFSR[15] of 0xACE1 = 1, [1]/[2] counter bit PINDIV(=5) = 0 (counters cleared),
#   [3] MISO = 0 (CS_N high), [4] BUSY = 0, [5] no FFAIL = 0, [6] DONE = 0,
#   [7] FMAX_ARMED = 0 (CTRL.FMAX_EN = 0 after reset)
UO_RESET = 0x01


async def check_all_reset_values(tb, where):
    regs = await tb.rd(0x00, 0x12)   # 0x00 .. 0x11 inclusive
    for a, (rv, _) in RW_REGS.items():
        assert regs[a] == rv, f"{where}: reg {a:#04x} = {regs[a]:#04x}, spec reset {rv:#04x}"
    for a, rv in RO_RESET.items():
        assert regs[a] == rv, f"{where}: reg {a:#04x} = {regs[a]:#04x}, spec reset {rv:#04x}"
    # MISC: PINMODE 0, ACKs 0, FMAX pin 0, valid 0, ena 1, cnt_en 0, ring_clr 0
    assert regs[MISC] == M_ENA, f"{where}: MISC = {regs[MISC]:#04x}, expected {M_ENA:#04x}"
    for a in (0x12, 0x40, 0x7F):
        v = await tb.rd(a)
        assert v == 0, f"{where}: unmapped {a:#04x} reads {v:#04x}"


def check_outputs(tb, where):
    uo = tb.dut.uo_out.value
    assert uo.is_resolvable, f"{where}: uo_out has X/Z bits: {uo}"
    assert int(uo) == UO_RESET, f"{where}: uo_out = {int(uo):#04x}, expected {UO_RESET:#04x}"
    oe = tb.dut.uio_oe.value
    assert oe.is_resolvable and int(oe) == 0, f"{where}: uio_oe = {oe}, must be 0 (inputs)"
    assert tb.dut.uio_out.value.is_resolvable, f"{where}: uio_out has X/Z: {tb.dut.uio_out.value}"


@gl_safe
async def test_reset_values(dut):
    """Every register reads its SPEC section 4 reset value; outputs are clean."""
    tb = TB(dut, "test_reset_values")
    await tb.start()
    check_outputs(tb, "after reset")
    await check_all_reset_values(tb, "after reset")
    check_outputs(tb, "after register reads")


@gl_safe
async def test_reset_outputs_during_reset(dut):
    """While rst_n is held low the outputs are already defined (async assert)."""
    tb = TB(dut, "test_reset_outputs_during_reset")
    await tb.set_clock(100)
    dut.ena.value = 1
    dut.ui_in.value = 0x01
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await Timer(1, "ns")
    uo = dut.uo_out.value
    assert uo.is_resolvable, f"uo_out has X/Z during reset: {uo}"
    assert int(uo) == UO_RESET, f"uo_out during reset = {int(uo):#04x}"
    assert int(dut.uio_oe.value) == 0, "uio_oe must be 0 during reset"
    dut.rst_n.value = 1
    await tb.cycles(10)
    check_outputs(tb, "after release")


@gl_safe
async def test_reset_mid_measurement(dut):
    """rst_n asserted during a long clk/2 measurement aborts it; everything returns
    to reset values and the next measurement is correct."""
    tb = TB(dut, "test_reset_mid_measurement")
    await tb.start()
    await tb.wr(SRCA, SRC_CLK2, SRC_CLK2)
    await tb.set_timing(gexp=13)   # gate = 8192 clk cycles
    await tb.wr(CMD, K_START)
    await tb.cycles(1000)
    assert tb.pin("busy_pin") == 1, "measurement should be running"
    dut.rst_n.value = 0
    await Timer(3, "ns")          # asynchronous assertion: no clock edge needed
    assert tb.pin("busy_pin") == 0, "BUSY must clear asynchronously on reset"
    await tb.cycles(5)
    dut.rst_n.value = 1
    await tb.cycles(10)
    check_outputs(tb, "after mid-measurement reset")
    await check_all_reset_values(tb, "after mid-measurement reset")
    st, ca, cb = await tb.measure(SRC_CLK2, SRC_CLK2, gexp=8)   # gate = 256
    assert st & (S_DONE | S_BUSY) == S_DONE, f"STATUS={st:#04x}"
    assert abs(ca - 128) <= 1 and abs(cb - 128) <= 1, f"CNTA={ca} CNTB={cb}"


@gl_safe
async def test_reset_mid_spi(dut):
    """rst_n asserted in the middle of an SPI write: the partial write has no effect
    and the next transaction works."""
    tb = TB(dut, "test_reset_mid_spi")
    await tb.start()
    # A write to TIMING, reset asserted after 12 of 16 bits (CS_N stays low
    # through the reset, as a master that does not know about the reset would).
    task = tb.xfer([0x80 | TIMING, 0x33])
    t = cocotb.start_soon(task)
    await tb.wait_fs(tb.tclk_fs * tb.sck_div * 12)
    dut.rst_n.value = 0
    await tb.cycles(5)
    dut.rst_n.value = 1
    await t
    await tb.cycles(10)
    assert await tb.rd(TIMING) == 0x5A, "partial write before reset must not land in TIMING"
    await check_all_reset_values(tb, "after mid-SPI reset")
    await tb.wr(TIMING, 0xC3)
    assert await tb.rd(TIMING) == 0xC3


@rtl_only
async def test_rings_off_after_reset(dut):
    """All 20 ring enables are 0 after reset (hierarchical probe)."""
    tb = TB(dut, "test_rings_off_after_reset")
    await tb.start()
    en = read_ring_enables(dut)
    assert en == [0] * 20, f"ring enables after reset: {en}"
    # Also after reset from a running state.
    await tb.wr(CTRL, 1)  # RUN with reset SRCA=0, SRCB=8
    en = read_ring_enables(dut)
    assert en[0] == 1 and en[8] == 1 and sum(en) == 2, f"RUN: enables {en}"
    dut.rst_n.value = 0
    await Timer(3, "ns")
    en = read_ring_enables(dut)
    assert en == [0] * 20, f"ring enables during reset: {en}"
    dut.rst_n.value = 1
    await tb.cycles(10)
    assert read_ring_enables(dut) == [0] * 20
