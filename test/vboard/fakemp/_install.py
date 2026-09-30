# SPDX-FileCopyrightText: (c) 2026 Parv Bhadra
# SPDX-License-Identifier: Apache-2.0
"""Call install() once, from the cocotb test, before importing
bringup/binner_bringup.py. This augments the REAL stdlib `time` module *in
place* (adding ticks_ms/ticks_us/ticks_diff/sleep_ms/sleep_us -- names that
don't already exist in CPython's time module, so nothing already using
`time` -- including cocotb's own scheduler -- is affected) and points a new
`utime` module alias at the same augmented object, matching MicroPython
where `utime is time`.

We deliberately do NOT replace sys.modules['time'] wholesale: cocotb and
Python's own machinery use the real time module in the same process, and a
full replacement would be a much larger blast radius than necessary. Only
`machine` and `rp2` (which don't exist in CPython at all) are added as
brand-new fake modules with no collision risk.
"""

import sys
import time as _real_time

from ttboard import _sim_bridge as _sb


def install():
    _real_time.ticks_ms = _sb.ticks_ms
    _real_time.ticks_us = _sb.ticks_us
    _real_time.ticks_diff = _sb.ticks_diff
    _real_time.sleep_ms = _sb.sleep_ms
    _real_time.sleep_us = _sb.sleep_us
    sys.modules["utime"] = _real_time

    import machine  # noqa: F401  registers the fake `machine` module
    import rp2  # noqa: F401      registers the fake `rp2` module
