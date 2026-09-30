# SPDX-FileCopyrightText: © 2026 Parv Bhadra
# SPDX-License-Identifier: Apache-2.0
"""Pin-strap mode (SPEC section 1, ui_in[3] = PINMODE): sources come from
ui_in[7:4], counters free-run, the LFSR steps every clk, uio stays input, and
SPI still works. RTL-only: the frequency checks need a real behavioural ring."""

from binner_tb import RO_RESET, TB, TIMING, gl_safe, ring_freq_hz, rtl_only


@rtl_only
async def test_pinmode_source_select(dut):
    """SPEC section 1: bank=0 -> A = source `sel`; bank=1 -> A = source 16+sel;
    B = source 8+sel always. Checked by hierarchical probe of src_a/src_b."""
    tb = TB(dut, "test_pinmode_source_select")
    await tb.start()
    up = dut.user_project
    for bank in (0, 1):
        for sel in range(8):
            tb.set_pinmode(1, sel=sel, bank=bank)
            await tb.cycles(3)
            exp_a = (16 + sel) if bank else sel
            exp_b = 8 + sel
            assert int(up.src_a.value) == exp_a, f"bank={bank} sel={sel}: src_a={int(up.src_a.value)}, expected {exp_a}"
            assert int(up.src_b.value) == exp_b, f"bank={bank} sel={sel}: src_b={int(up.src_b.value)}, expected {exp_b}"
            assert int(up.run.value) == 1, f"bank={bank} sel={sel}: run must be 1 in pin mode (ena=1)"
    tb.set_pinmode(0)


@rtl_only
async def test_pinmode_counters_free_run(dut):
    """Channel A = source 20 (clk/2, bank=1 sel=4): uo_out[1] toggles at exactly
    clk/2/2^(PINDIV+1), no SPI START needed (counters free-run in pin mode).
    Channel B = source 12 (ring, bank irrelevant, sel=4): uo_out[2] toggles near
    the ring's behavioural frequency."""
    tb = TB(dut, "test_pinmode_counters_free_run")
    await tb.start(period_ns=20.0)
    await tb.set_timing(pindiv=0)
    tb.set_pinmode(1, sel=4, bank=1)   # A = src 20 (clk/2), B = src 12 (ring)
    await tb.cycles(8)
    exp_a = 2 * (2 ** 1) * tb.tclk_fs       # source(=clk/2) / 2^(PINDIV+1) = clk/4
    per_a = await tb.period_of(dut.cha_div, 6, 20 * exp_a)
    assert per_a == exp_a, f"channel A (clk/2) period {per_a / 1e6} ns, expected {exp_a / 1e6} ns"
    f_ring = ring_freq_hz(12)
    exp_b_hz = f_ring / (2 ** 1)
    per_b = await tb.period_of(dut.chb_div, 6, int(20e15 / exp_b_hz))
    got_hz = 1e15 / per_b
    assert abs(got_hz - exp_b_hz) / exp_b_hz < 0.02, f"channel B (ring12) freq {got_hz:.3e} Hz, expected {exp_b_hz:.3e} Hz"
    tb.set_pinmode(0)


@rtl_only
async def test_pinmode_uio_stays_input(dut):
    """uio pins stay inputs in pin mode when CTRL.UIOOE has not been set (its
    reset value): uio_oe == 0 across the whole sel/bank sweep."""
    tb = TB(dut, "test_pinmode_uio_stays_input")
    await tb.start()
    assert int(dut.uio_oe.value) == 0
    for bank in (0, 1):
        for sel in range(8):
            tb.set_pinmode(1, sel=sel, bank=bank)
            await tb.cycles(3)
            assert int(dut.uio_oe.value) == 0, f"bank={bank} sel={sel}: uio_oe != 0 in pin mode"
    tb.set_pinmode(0)


@gl_safe
async def test_pinmode_spi_still_works(dut):
    """SPI reads (and writes) still work while ui_in[3] (PINMODE) is high."""
    tb = TB(dut, "test_pinmode_spi_still_works")
    await tb.start()
    tb.set_pinmode(1, sel=2, bank=0)
    await tb.cycles(3)
    ids = await tb.rd(0x00, 3)
    exp = [RO_RESET[0x00], RO_RESET[0x01], RO_RESET[0x02]]
    assert ids == exp, f"ID/VER readback in pin mode: {ids}, expected {exp}"
    await tb.wr(TIMING, 0x37)
    assert await tb.rd(TIMING) == 0x37, "TIMING write/readback failed in pin mode"
    await tb.wr(TIMING, 0x5A)
    tb.set_pinmode(0)
