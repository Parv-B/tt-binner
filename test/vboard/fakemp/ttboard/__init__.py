# SPDX-FileCopyrightText: (c) 2026 Parv Bhadra
# SPDX-License-Identifier: Apache-2.0
"""Fake `ttboard` package for the BINNER virtual demo board.

Mirrors the subset of tt-micropython-firmware v3.1.1's public API that
bringup/binner_bringup.py uses, backed by cocotb + Icarus Verilog instead of
real RP2350 GPIO. See test/vboard/fakemp/ttboard/_sim_bridge.py for the
cocotb glue and test/vboard/sim_tb.py for how a test wires this up.
"""

IS_SIM = True
FIRMWARE_VERSION = "vboard-fake-0.1.0 (models tt-micropython-firmware v3.1.1)"
