# SPDX-FileCopyrightText: (c) 2026 Parv Bhadra
# SPDX-License-Identifier: Apache-2.0
"""All the cocotb-facing plumbing for the virtual demo board lives here.

Every function that touches the DUT or advances simulated time is an
`async def _a_*` wrapped by `cocotb._bridge.resume` into a *blocking*
function (`resume(coro_fn)` -> ordinary callable). Those blocking wrappers
are what the fake `ttboard`/`machine` classes call, so that
bringup/binner_bringup.py -- which is a plain, synchronous, MicroPython-style
script with no `async`/`await` in it at all -- can drive the simulator.

This only works because binner_bringup.main() itself runs inside a `bridge`
thread (see test/vboard/sim_tb.py): a bridge thread is a real OS thread that
is allowed to run freely, but it must periodically call a `resume`-wrapped
function (which blocks the OS thread and hands control back to the cocotb
scheduler) or simulated time never advances underneath it and the test
hangs. Concretely: EVERY pin read/write and EVERY sleep in this module goes
through `resume`, even reads that don't need to advance time, specifically
so that any tight polling loop in the bring-up script (e.g. count_edges(),
poll_done()) still yields to the scheduler once per iteration.
"""

import random

import cocotb
from cocotb._bridge import resume
from cocotb.clock import Clock
from cocotb.triggers import Timer

_dut = None
_variation = {}
_clock_task = None
_clock_period_ns = 100.0  # 10 MHz default, matches RESET_TIMING etc.
_clock_hz = 10000000.0

# ---------------------------------------------------------------------------
# setup (called once from sim_tb.py before the bridge thread starts)
# ---------------------------------------------------------------------------
def init(dut, variation=None):
    global _dut, _variation
    _dut = dut
    _variation = variation or {}


# ---------------------------------------------------------------------------
# pins
#
# GPIO_READ_NS models the wall-clock cost of an RP2350 byte-wide GPIO read
# from MicroPython (bit-bang overhead, not a hardware limit) as simulated
# time. This matters for correctness, not just realism: TTBoardHAL.
# count_edges() polls read_uo() in a tight loop with NO other sleep in
# between, and its exit condition is time.ticks_ms() (itself sourced from
# simulated time on the virtual board, via ticks_ms() below) reaching a
# window -- if reads never advanced simulated time, that loop would spin
# forever at a frozen timestamp instead of ever seeing the window elapse.
# ---------------------------------------------------------------------------
GPIO_READ_NS = 1000  # 1us/read -> ~1MHz software poll rate, MicroPython-plausible


async def _a_read_ui_in():
    await Timer(GPIO_READ_NS, "ns")
    return int(_dut.ui_in.value) & 0xFF


async def _a_write_ui_in(v):
    _dut.ui_in.value = v & 0xFF
    await Timer(GPIO_READ_NS, "ns")


async def _a_read_uo_out():
    await Timer(GPIO_READ_NS, "ns")
    return int(_dut.uo_out.value) & 0xFF


async def _a_read_uio():
    # uio is bidirectional; when the DUT drives it (uio_oe=1) a read from
    # the Pico side reflects uio_out, matching real hardware pad behaviour.
    await Timer(GPIO_READ_NS, "ns")
    oe = int(_dut.uio_oe.value) & 0xFF
    out = int(_dut.uio_out.value) & 0xFF
    return out & oe


async def _a_write_uio(v):
    _dut.uio_in.value = v & 0xFF
    await Timer(1, "ns")


read_ui_in = resume(_a_read_ui_in)
write_ui_in = resume(_a_write_ui_in)
read_uo_out = resume(_a_read_uo_out)
read_uio = resume(_a_read_uio)
write_uio = resume(_a_write_uio)


# ---------------------------------------------------------------------------
# reset / enable
# ---------------------------------------------------------------------------
async def _a_reset_project(hold_reset):
    _dut.rst_n.value = 0 if hold_reset else 1
    await Timer(50, "ns")


reset_project = resume(_a_reset_project)


async def _a_select_project():
    await Timer(1, "ns")


select_project = resume(_a_select_project)


# ---------------------------------------------------------------------------
# clock / PWM quantisation
#
# Reconstructed from the documented tt-micropython-firmware v3.1.1 behaviour
# (facts supplied for this task, not read from firmware source, which this
# environment does not have access to): search sysclk in 1MHz steps from
# 48MHz (2MHz steps above 136MHz) up to a ~250MHz ceiling, for f = sysclk /
# even_divisor closest to the requested frequency. Documented as a
# reconstruction, not a verified copy, in bringup/README.md.
# ---------------------------------------------------------------------------
def quantize_pwm(freq_hz, max_rp2040_freq=0):
    lo = 48000000
    hi = max_rp2040_freq if max_rp2040_freq else 250000000
    best_err = None
    best_f = float(freq_hz)
    sysclk = lo
    while sysclk <= hi:
        step = 2000000 if sysclk > 136000000 else 1000000
        div = int(round(sysclk / float(freq_hz)))
        if div < 2:
            div = 2
        if div % 2:
            div += 1
        achieved = sysclk / float(div)
        err = abs(achieved - freq_hz)
        if best_err is None or err < best_err:
            best_err = err
            best_f = achieved
            if err < 0.5:
                return best_f
        sysclk += step
    return best_f


async def _a_set_clock(freq_hz, duty_u16, max_rp2040_freq):
    global _clock_task, _clock_period_ns, _clock_hz
    achieved = quantize_pwm(freq_hz, max_rp2040_freq)
    # cocotb's Clock rejects a period with rounding error beyond the
    # simulator's time precision (COCOTB_HDL_TIMEPRECISION=1fs here); most
    # achievable frequencies give a repeating-decimal period in ns (e.g.
    # 12MHz -> 83.3333...ns), so round to a whole number of femtoseconds
    # instead of handing Clock a float number of ns. cocotb's Clock also
    # requires an EVEN period in fs when period_high isn't given explicitly
    # (it derives a 50% duty cycle by bit-shifting); round-to-nearest can
    # land on an odd fs count (e.g. FMAX_LO_HZ=12MHz -> 83333333.33ns ->
    # 83333333333fs, odd), which raised
    # "ValueError: Bad `period`: Must be divisible by 2" every time Stage 3
    # armed a bisection trial at such a frequency. Bump to the nearest even
    # fs instead -- a <=1fs error on a multi-microsecond-to-nanosecond
    # period is many orders of magnitude below anything this model cares
    # about.
    period_fs = int(round(1.0e15 / achieved))
    if period_fs % 2:
        period_fs += 1
    if _clock_task is not None:
        _clock_task.cancel()
    clk = Clock(_dut.clk, period_fs, unit="fs")
    _clock_task = cocotb.start_soon(clk.start())
    _clock_period_ns = period_fs / 1.0e6
    # Report the frequency the simulator is actually toggling at (post
    # even-fs rounding above), not the pre-rounding PWM-quantizer output --
    # they can differ by up to 1fs of period, which is negligible in
    # absolute terms but binner_bringup.py's f_src = CNT*f_clk/2^GEXP uses
    # this value directly, so keep it exact rather than compounding two
    # separate roundings silently.
    _clock_hz = 1.0e15 / period_fs
    await Timer(max(2000, period_fs + 1000), "fs")
    return _clock_hz


set_clock = resume(_a_set_clock)


async def _a_clock_stop():
    global _clock_task
    if _clock_task is not None:
        _clock_task.cancel()
        _clock_task = None
    await Timer(1, "ns")


clock_stop = resume(_a_clock_stop)


# ---------------------------------------------------------------------------
# time (used by the fake `time` module's ticks_ms/sleep_ms)
# ---------------------------------------------------------------------------
async def _a_sleep_ns(ns):
    await Timer(max(1, int(ns)), "ns")


_sleep_ns = resume(_a_sleep_ns)


def sleep_ms(n):
    _sleep_ns(int(n) * 1000000)


def sleep_us(n):
    _sleep_ns(int(n) * 1000)


async def _a_now_ns():
    return cocotb.utils.get_sim_time(unit="ns")


_now_ns = resume(_a_now_ns)


def ticks_ms():
    return int(_now_ns() / 1.0e6) & 0x3FFFFFFF


def ticks_us():
    return int(_now_ns() / 1.0e3) & 0x3FFFFFFF


def ticks_diff(a, b):
    return a - b


# ---------------------------------------------------------------------------
# ADC / temperature: report the injected per-chip T_c (docs/VARIATION_MODEL.md)
# with a little measurement noise, exactly like a real RP2350 core temp read.
# ---------------------------------------------------------------------------
_temp_rng = random.Random(0xADC)


def core_temp():
    base = _variation.get("T_c", 27.0)
    return base + _temp_rng.uniform(-0.3, 0.3)
