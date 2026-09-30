# SPDX-FileCopyrightText: (c) 2026 Parv Bhadra
# SPDX-License-Identifier: Apache-2.0
"""Minimal stand-in for ttboard.mode.RPMode -- bring-up only reads/writes
tt.mode = RPMode.ASIC_RP_CONTROL, it never branches on the value here."""


class RPMode:
    ASIC_RP_CONTROL = "ASIC_RP_CONTROL"
    ASIC_MANUAL_INPUTS = "ASIC_MANUAL_INPUTS"
    SAFE = "SAFE"
