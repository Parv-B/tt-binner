# SPDX-FileCopyrightText: (c) 2026 Parv Bhadra
# SPDX-License-Identifier: Apache-2.0
"""Fake ttboard.util.platform: the fast-path byte-wide GPIO helpers the real
firmware exposes (write_ui_in_byte/read_uo_out_byte). TTBoardHAL prefers
these when present, on both real hardware and the virtual board."""

from ttboard import _sim_bridge as _sb


def write_ui_in_byte(v):
    _sb.write_ui_in(v & 0xFF)


def read_uo_out_byte():
    return _sb.read_uo_out()
