# SPDX-FileCopyrightText: (c) 2026 Parv Bhadra
# SPDX-License-Identifier: Apache-2.0
"""Fake ttboard.demoboard.DemoBoard -- the object bringup/binner_bringup.py
gets from DemoBoard.get() and drives exactly as it would on real hardware.
All actual work is delegated to ttboard._sim_bridge (cocotb bridge/resume).
"""

from ttboard import _sim_bridge as _sb


class _ByteBus(object):
    """Stands in for a ttboard pin bus: .value get/set, and per-bit
    __getitem__/__setitem__, exactly as bringup/binner_bringup.py uses
    tt.ui_in / tt.uo_out / tt.uio_in.
    """

    def __init__(self, get_fn, set_fn=None):
        self._get = get_fn
        self._set = set_fn

    def _get_value(self):
        return self._get()

    def _set_value(self, v):
        if self._set is None:
            raise AttributeError("this bus is read-only in the fake board")
        self._set(v & 0xFF)

    value = property(_get_value, _set_value)

    def __getitem__(self, i):
        return (self._get() >> i) & 1

    def __setitem__(self, i, bitval):
        if self._set is None:
            raise AttributeError("this bus is read-only in the fake board")
        cur = self._get()
        if bitval:
            cur |= (1 << i)
        else:
            cur &= ~(1 << i) & 0xFF
        self._set(cur)


class _Adc(object):
    @property
    def core_temp(self):
        return _sb.core_temp()


class _Project(object):
    def __init__(self, name="tt_um_parv_b_binner"):
        self.name = name

    def enable(self):
        _sb.select_project()


class _Shuttle(object):
    """The real shuttle object exposes .find(name), attribute access
    tt_um_xxx, and indexing by numeric tile address. The virtual board has
    exactly one project instantiated in the testbench, so every one of
    these paths resolves to it -- this exists so binner_bringup.py's
    fallback-selection logic (docs task: firmware ships no ttgf26d shuttle
    index yet) runs unmodified against the sim too.
    """

    def find(self, name):
        if name and "binner" in name.lower():
            return _Project()
        return None

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if "binner" in name.lower() or name.startswith("tt_um"):
            return _Project(name)
        raise AttributeError(name)

    def __getitem__(self, addr):
        return _Project()


class DemoBoard(object):
    _instance = None

    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def _reset_singleton(cls):
        # test-only: population runs create a fresh cocotb test process per
        # chip, but this guards against accidental reuse within one process.
        cls._instance = None

    def __init__(self):
        self.ui_in = _ByteBus(_sb.read_ui_in, _sb.write_ui_in)
        self.uo_out = _ByteBus(_sb.read_uo_out, None)
        self.uio_in = _ByteBus(_sb.read_uio, _sb.write_uio)
        self.uio_oe_pico = _ByteBus(lambda: 0, None)
        self.shuttle = _Shuttle()
        self.adc = _Adc()
        self.mode = None
        self.auto_clocking_freq = None

    def reset_project(self, state):
        _sb.reset_project(bool(state))

    def clock_project_PWM(self, freq_hz, duty_u16=0x8000, quiet=False, max_rp2040_freq=0):
        achieved = _sb.set_clock(freq_hz, duty_u16, max_rp2040_freq)
        self.auto_clocking_freq = achieved
        if not quiet and abs(achieved - freq_hz) > 1:
            print("freq_jitter_free: requested %d achieved %g" % (freq_hz, achieved))
        return achieved

    def clock_project_stop(self):
        _sb.clock_stop()

    def clock_project_once(self):
        pass
