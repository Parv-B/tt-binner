# SPDX-FileCopyrightText: (c) 2026 Parv Bhadra
# SPDX-License-Identifier: Apache-2.0
"""Minimal fake `machine` module. binner_bringup.py's default/portable SPI
path is bit-banged directly through ttboard's ui_in/uo_out (SpiBitBang in
bringup/binner_bringup.py) and never touches this module. It exists so that
code which optionally imports `machine.Pin`/`machine.SPI` (documented as an
optional hardware-SPI path on real RP2350 GPIO17-19/36) does not crash under
the virtual board; it is not exercised by the population runs.
"""

from ttboard import _sim_bridge as _sb


class Pin(object):
    IN = 0
    OUT = 1

    def __init__(self, num, mode=IN, *a, **kw):
        self.num = num
        self.mode = mode

    def value(self, v=None):
        # Not wired to the DUT: the RP2350 GPIO map (rst_n=14, clk=16,
        # ui_in=17..24, uio=25..32, uo_out=33..40) is a hardware-only detail
        # bringup/binner_bringup.py never needs directly (it always goes
        # through ttboard's ui_in/uo_out byte buses).
        return 0


class SPI(object):
    """Not used by the default bit-bang path; provided only so
    `machine.SPI(0, ...)` does not raise ImportError if a future variant of
    the bring-up script opts into the hardware-SPI path documented in
    bringup/README.md."""

    def __init__(self, id, baudrate=1000000, polarity=0, phase=0, sck=None,
                 mosi=None, miso=None, *a, **kw):
        self.id = id
        self.baudrate = baudrate

    def write_readinto(self, wbuf, rbuf):
        # byte-at-a-time through the same underlying ui_in/uo_out bit-bang
        # primitives used by SpiBitBang, so behaviour stays consistent even
        # though the timing model differs from real SPI0 hardware.
        for i, b in enumerate(wbuf):
            cur = _sb.read_ui_in() & ~0x07
            rx = 0
            for bit in range(7, -1, -1):
                mosi = (b >> bit) & 1
                _sb.write_ui_in(cur | (mosi << 2))
                _sb.write_ui_in(cur | (mosi << 2) | 0x02)
                rx = (rx << 1) | ((_sb.read_uo_out() >> 3) & 1)
                _sb.write_ui_in(cur | (mosi << 2))
            if i < len(rbuf):
                rbuf[i] = rx
