# SPDX-FileCopyrightText: © 2026 Parv Bhadra
# SPDX-License-Identifier: Apache-2.0
"""Fmax (at-speed) checker (SPEC section 6).

Procedure follows SPEC section 6 exactly: arm/clear at a safe clock, switch to
the test frequency, pulse ui_in[7] for the test window, switch back to the
safe clock, read FFAIL. The polarity self-test (FMAX_INV) and arming logic
need no ring and no precise behavioural timing, so they run in gate-level mode
too; the per-tap threshold sweep needs the behavioural delay-chain model and
is RTL-only.
"""

from binner_tb import (
    CMD, CTRL, C_FMAX_EN, C_FMAX_INV, FFAIL, K_FCLR, STATUS, S_ARMED, TAPPOS,
    TB, dovh_fs, dstg_fs, gl_safe, rtl_only, tap_delay_fs,
)

SAFE_NS = 100.0   # 10 MHz: default tap delays (<=48.2 ns) always fit


async def fmax_window(tb, period_ns, window_cycles=300, inv=False, safe_ns=SAFE_NS, clear=True):
    """SPEC section 6 procedure. Returns FFAIL after the window."""
    await tb.set_clock(safe_ns)
    await tb.wr(CTRL, C_FMAX_EN | (C_FMAX_INV if inv else 0))
    if clear:
        await tb.wr(CMD, K_FCLR)
    tb.set_fmax_pin(0)
    await tb.cycles(5)
    await tb.set_clock(period_ns, clean=False)
    await tb.cycles(3)
    tb.set_fmax_pin(1)
    await tb.cycles(window_cycles)
    tb.set_fmax_pin(0)
    await tb.cycles(5)
    await tb.set_clock(safe_ns)
    await tb.cycles(3)
    ffail = await tb.rd(FFAIL)
    await tb.wr(CTRL, 0)
    return ffail


@gl_safe
async def test_fmax_polarity_inv(dut):
    """FMAX_INV=1 must fail every tap (self-test of the comparators and sticky
    flags), at a clock slow enough that every tap normally passes."""
    tb = TB(dut, "test_fmax_polarity_inv")
    await tb.start()
    ffail = await fmax_window(tb, SAFE_NS, inv=True)
    assert ffail == 0xFF, f"FMAX_INV=1: FFAIL={ffail:#04x}, expected 0xFF (every tap fails)"
    # Sanity: without inversion, at the same safe (slow) clock, nothing fails.
    ffail0 = await fmax_window(tb, SAFE_NS, inv=False)
    assert ffail0 == 0x00, f"FMAX_INV=0 at a safe clock: FFAIL={ffail0:#04x}, expected 0x00"


@gl_safe
async def test_fmax_clear(dut):
    """CMD.FMAX_CLEAR resets sticky FFAIL to 0."""
    tb = TB(dut, "test_fmax_clear")
    await tb.start()
    ffail = await fmax_window(tb, SAFE_NS, inv=True)
    assert ffail == 0xFF
    await tb.wr(CTRL, C_FMAX_EN)
    await tb.wr(CMD, K_FCLR)
    assert await tb.rd(FFAIL) == 0x00, "FMAX_CLEAR did not clear FFAIL"
    await tb.wr(CTRL, 0)


@gl_safe
async def test_fmax_arming_pin(dut):
    """armed (uo_out[7], STATUS[7]) = CTRL.FMAX_EN & sync(ui_in[7]) & !PINMODE."""
    tb = TB(dut, "test_fmax_arming_pin")
    await tb.start()

    async def armed_after_settle():
        await tb.cycles(6)   # 2-flop pin sync + 1-cycle armed register
        st = await tb.rd(STATUS)
        assert tb.pin("farmed_pin") == (1 if st & S_ARMED else 0), "uo_out[7] != STATUS[7] (FMAX_ARMED)"
        return tb.pin("farmed_pin")

    # FMAX_EN=0, pin=1: never arms.
    tb.set_fmax_pin(1)
    await tb.wr(CTRL, 0)
    assert await armed_after_settle() == 0, "armed with CTRL.FMAX_EN=0"
    # FMAX_EN=1, pin=0: never arms.
    tb.set_fmax_pin(0)
    await tb.wr(CTRL, C_FMAX_EN)
    assert await armed_after_settle() == 0, "armed with ui_in[7]=0"
    # FMAX_EN=1, pin=1, pinmode=0: arms.
    tb.set_fmax_pin(1)
    assert await armed_after_settle() == 1, "did not arm with FMAX_EN=1, ui_in[7]=1, PINMODE=0"
    # Pin mode forces armed=0 even with FMAX_EN=1 and ui_in[7]=1 (bank select reuses the pin).
    tb.set_pinmode(1, bank=1)   # ui_in[3]=1, ui_in[7]=1
    assert await armed_after_settle() == 0, "armed while PINMODE=1 (must be forced 0)"
    tb.set_pinmode(0)
    await tb.wr(CTRL, 0)
    tb.set_fmax_pin(0)


@gl_safe
async def test_fmax_disarmed_accumulates_nothing(dut):
    """While disarmed (CTRL.FMAX_EN=0), clock retuning (even to very fast, glitchy
    periods) and a raised ui_in[7] must not set any FFAIL bit."""
    tb = TB(dut, "test_fmax_disarmed_accumulates_nothing")
    await tb.start()
    await tb.wr(CTRL, 0)
    await tb.wr(CMD, K_FCLR)
    tb.set_fmax_pin(1)   # pin high, but disarmed (FMAX_EN=0)
    for period in (SAFE_NS, 3.0, 1.7, 50.0, 0.9):
        await tb.set_clock(period, clean=False)
        await tb.cycles(50)
    tb.set_fmax_pin(0)
    await tb.set_clock(SAFE_NS)
    await tb.cycles(5)
    assert await tb.rd(FFAIL) == 0x00, "FFAIL set while CTRL.FMAX_EN=0 (disarmed)"


@rtl_only
async def test_fmax_tap_thresholds(dut):
    """Sweep clk period across every tap's threshold (behavioural default: 0.6 ns
    mux overhead + 3.4 ns/stage). At each period, the expected sticky FFAIL
    bitmask is exactly the taps whose delay exceeds the period (delay increases
    monotonically with tap index, since TAPPOS is increasing)."""
    tb = TB(dut, "test_fmax_tap_thresholds")
    await tb.start()
    delays_fs = [tap_delay_fs(k) for k in range(8)]
    assert delays_fs == sorted(delays_fs), "test assumption: tap delay increases with index"
    mids = [delays_fs[0] * 0.5] + [(delays_fs[i] + delays_fs[i + 1]) / 2 for i in range(7)] + [delays_fs[7] * 1.5]
    for period_fs in mids:
        period_ns = period_fs / 1e6
        exp_mask = sum(1 << k for k in range(8) if delays_fs[k] > period_fs)
        ffail = await fmax_window(tb, period_ns, window_cycles=400)
        assert ffail == exp_mask, (
            f"period={period_ns:.2f} ns: FFAIL={ffail:#04x}, expected {exp_mask:#04x} "
            f"(tap delays ns: {[d / 1e6 for d in delays_fs]})")


@rtl_only
async def test_fmax_tap_delay_matches_dstg_model(dut):
    """Sanity: tap_delay_fs(k) (used above) equals overhead + sum of the first
    TAPPOS[k] per-stage delays, both defaulted from the SPEC section 8 plusargs
    (3.4 ns/stage, 0.6 ns overhead) with no plusarg override in this run."""
    assert dovh_fs() == 600_000, "default DCHAIN_OVH_FS changed underfoot"
    for i in range(1, 15):
        assert dstg_fs(i) == 3_400_000, f"default DSTG{i}_FS changed underfoot"
    for k, n in enumerate(TAPPOS):
        assert tap_delay_fs(k) == 600_000 + n * 3_400_000
