# SPDX-FileCopyrightText: (c) 2026 Parv Bhadra
# SPDX-License-Identifier: Apache-2.0
"""Placeholder fake `rp2` module (PIO). bringup/binner_bringup.py's edge
counter (TTBoardHAL.count_edges) uses the pure-software polling fallback
described in docs/SPEC.md bring-up notes, not a PIO program, so nothing here
is exercised today. Kept as an import-safety net and a marker for the PIO
edge-counter improvement noted in bringup/README.md as future work.
"""


class PIO(object):
    pass


def asm_pio(*a, **kw):
    def deco(f):
        return f
    return deco
