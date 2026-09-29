# SPDX-FileCopyrightText: © 2026 Parv Bhadra
# SPDX-License-Identifier: Apache-2.0
"""SPI slave and register file (SPEC sections 1, 3, 4)."""

from binner_tb import (
    C_FREE, C_RUN, C_UIOOE, CMD, CTRL, GL, K_START, MAPPED, MISC, RO_RESET,
    RW_REGS, SRCA, SRCB, SRC_CLK2, STATUS, S_BUSY, S_DONE, TB, TIMING,
    UNMAPPED, gl_safe,
)


def safe_ctrl(v):
    """In gate-level mode never set CTRL.RUN (a running ring hangs zero-delay GL)."""
    return v & ~C_RUN if GL else v


async def read_rw(tb):
    regs = await tb.rd(0x00, 0x07)
    return {a: regs[a] for a in RW_REGS}


@gl_safe
async def test_spi_rw_registers(dut):
    """Every RW register: random write/readback, unused bits read 0 (SPEC 4 masks)."""
    tb = TB(dut, "test_spi_rw_registers")
    await tb.start()
    for addr, (_, mask) in RW_REGS.items():
        vals = [0x00, 0xFF, 0x55, 0xAA] + [tb.rng.randrange(256) for _ in range(6)]
        for v in vals:
            if addr == CTRL:
                v = safe_ctrl(v)
            await tb.wr(addr, v)
            got = await tb.rd(addr)
            assert got == v & mask, (
                f"reg {addr:#04x}: wrote {v:#04x}, read {got:#04x}, expected {v & mask:#04x} (mask {mask:#04x})")
        await tb.wr(addr, RW_REGS[addr][0])
    # One register write must not disturb the others.
    ref = {a: rv for a, (rv, _) in RW_REGS.items()}
    assert await read_rw(tb) == ref, "RW registers not back at reset values"
    await tb.wr(TIMING, 0x3C)
    ref[TIMING] = 0x3C
    assert await read_rw(tb) == ref, "TIMING write disturbed another register"
    await tb.wr(TIMING, RW_REGS[TIMING][0])


@gl_safe
async def test_spi_ro_and_unmapped_ignore_writes(dut):
    """Writes to RO and unmapped addresses are ignored; unmapped addresses read 0."""
    tb = TB(dut, "test_spi_ro_and_unmapped_ignore_writes")
    await tb.start()
    before_rw = await read_rw(tb)
    for addr in sorted(RO_RESET):
        if addr == CMD:
            continue
        for v in (0xFF, 0x00, tb.rng.randrange(256)):
            await tb.wr(addr, v)
            got = await tb.rd(addr)
            assert got == RO_RESET[addr], f"RO reg {addr:#04x} changed to {got:#04x} after write {v:#04x}"
    misc = await tb.rd(MISC)
    await tb.wr(MISC, 0xFF)
    assert await tb.rd(MISC) == misc, "MISC changed after write"
    # Burst write random junk over the whole unmapped range 0x12..0x7F.
    await tb.wr(0x12, *[tb.rng.randrange(1, 256) for _ in range(0x80 - 0x12)])
    after = await tb.rd(0x00, 0x80)
    for a in UNMAPPED:
        assert after[a] == 0, f"unmapped address {a:#04x} reads {after[a]:#04x}"
    for a, v in before_rw.items():
        assert after[a] == v, f"RW reg {a:#04x} changed by RO/unmapped writes: {v:#04x} -> {after[a]:#04x}"
    for a, v in RO_RESET.items():
        assert after[a] == v, f"RO reg {a:#04x} = {after[a]:#04x}, expected {v:#04x}"


@gl_safe
async def test_spi_cmd_reads_zero(dut):
    """CMD (0x07) is write-only and always reads 0."""
    tb = TB(dut, "test_spi_cmd_reads_zero")
    await tb.start()
    assert await tb.rd(CMD) == 0
    await tb.wr(CMD, 0xF0)          # no defined command bits
    assert await tb.rd(CMD) == 0
    await tb.wr(CMD, 0x04)          # LFSR_RESEED (harmless)
    assert await tb.rd(CMD) == 0
    st = await tb.rd(STATUS)
    assert st == 0, f"STATUS after undefined/benign CMD writes: {st:#04x}"


@gl_safe
async def test_spi_burst(dut):
    """Burst write 0x03..0x0C with auto-increment, burst read back across RW/RO."""
    tb = TB(dut, "test_spi_burst")
    await tb.start()
    for trial in range(4):
        addrs = list(range(0x03, 0x07))   # CTRL, SRCA, SRCB, TIMING
        vals = [tb.rng.randrange(256) for _ in addrs]
        vals[CTRL - 0x03] = safe_ctrl(vals[CTRL - 0x03]) & ~C_FREE
        await tb.wr(0x03, *vals)
        got = await tb.rd(0x00, 0x12)
        assert got[0:3] == [0x42, 0x4E, 0x02], f"trial {trial}: ID burst {got[0:3]}"
        for a, v in zip(addrs, vals):
            exp = v & RW_REGS[a][1]
            assert got[a] == exp, f"trial {trial}: burst reg {a:#04x} = {got[a]:#04x}, expected {exp:#04x}"
        # Partial burst starting mid-map (SRCA..TIMING) must only touch those registers.
        p = [tb.rng.randrange(256) for _ in range(2)]
        await tb.wr(SRCA, *p)
        got2 = await tb.rd(0x03, 4)
        for i, a in enumerate(range(0x03, 0x07)):
            exp = (p[a - SRCA] if SRCA <= a <= SRCA + 1 else vals[a - 0x03]) & RW_REGS[a][1]
            assert got2[i] == exp, f"trial {trial}: partial burst reg {a:#04x} = {got2[i]:#04x}, expected {exp:#04x}"
    await tb.wr(0x03, *[RW_REGS[a][0] for a in range(0x03, 0x07)])


@gl_safe
async def test_spi_abort_mid_byte(dut):
    """CS_N raised after k bits (k = 1..15) of a write: nothing is written, and the
    next transaction is clean. Same for an aborted read."""
    tb = TB(dut, "test_spi_abort_mid_byte")
    await tb.start()
    await tb.wr(TIMING, 0x11)
    for k in range(1, 16):
        await tb.xfer([0x80 | TIMING, 0xEE], abort_after_bits=k)
        got = await tb.rd(TIMING)
        assert got == 0x11, f"abort after {k} bits: TIMING = {got:#04x} (partial write landed)"
        v = tb.rng.randrange(256)
        await tb.xfer([0x80 | TIMING, 0xEE], abort_after_bits=k)
        await tb.wr(TIMING, v)
        assert await tb.rd(TIMING) == v, f"clean write after abort at {k} bits failed"
        await tb.wr(TIMING, 0x11)
    # Aborted read in the middle of the data byte, then clean burst read.
    for k in (3, 9, 13):
        await tb.xfer([0x00, 0, 0], abort_after_bits=k)
        assert await tb.rd(0x00, 3) == [0x42, 0x4E, 0x02], f"ID read after read abort at {k} bits"
    # Write abort in the 2nd data byte: the first data byte lands, the second must not.
    await tb.wr(TIMING, 0x00, 0x00)   # TIMING, CMD (CMD write of 0 is harmless)
    await tb.xfer([0x80 | TIMING, 0x77, 0x02], abort_after_bits=8 + 8 + 5)
    got = await tb.rd(TIMING, 2)
    assert got == [0x77, 0x00], f"after abort in 2nd data byte: TIMING/CMD readback = {got}"
    await tb.wr(TIMING, RW_REGS[TIMING][0])


@gl_safe
async def test_spi_miso_zero_when_cs_high(dut):
    """MISO (uo_out[3]) is 0 whenever CS_N is high, even with SCK/MOSI toggling
    and right after a read whose last bit was 1."""
    tb = TB(dut, "test_spi_miso_zero_when_cs_high")
    await tb.start()
    await tb.wr(TIMING, 0xFF)
    assert await tb.rd(TIMING) == 0xFF
    for i in range(64):
        tb.spi = 0x01 | (tb.rng.randrange(4) << 1)   # CS_N high, random SCK/MOSI
        tb._drive()
        await tb.cycles(3)
        assert tb.pin("miso_pin") == 0, f"MISO = 1 with CS_N high (step {i})"
    tb.spi = 0x01
    tb._drive()
    # A read cut off mid-byte while MISO is 1: MISO must return to 0 after CS_N rises.
    await tb.xfer([TIMING, 0], abort_after_bits=11)
    await tb.cycles(4)
    assert tb.pin("miso_pin") == 0, "MISO stuck at 1 after CS_N rose mid-read"
    await tb.wr(TIMING, RW_REGS[TIMING][0])


@gl_safe
async def test_spi_reads_no_side_effects(dut):
    """Reading every address (including CMD and STATUS) twice changes nothing:
    no START, no CLEAR, counters/LFSR/FFAIL unchanged."""
    tb = TB(dut, "test_spi_reads_no_side_effects")
    await tb.start()
    st, ca, cb = await tb.measure(SRC_CLK2, SRC_CLK2, gexp=6, extra_cycles=100)
    assert st & S_DONE
    a1 = await tb.rd(0x00, 0x80)
    for _ in range(3):
        await tb.rd(CMD)
        await tb.rd(STATUS)
    a2 = await tb.rd(0x00, 0x80)
    assert a1 == a2, f"register image changed by reads: {[(hex(i), x, y) for i, (x, y) in enumerate(zip(a1, a2)) if x != y]}"
    assert a2[STATUS] & (S_DONE | S_BUSY) == S_DONE, "reads started or cleared a measurement"
    assert (a2[0x09] | a2[0x0A] << 8) == ca and (a2[0x0B] | a2[0x0C] << 8) == cb


@gl_safe
async def test_spi_sck_rates(dut):
    """SPI works at SCK = clk/8 (the spec limit), clk/10, clk/12, clk/16 and at
    several clk frequencies (1..50 MHz range)."""
    tb = TB(dut, "test_spi_sck_rates")
    await tb.start()
    for period in (100.0, 20.0, 37.3, 1000.0):
        await tb.set_clock(period)
        for div in (8, 10, 12, 16):
            tb.sck_div = div
            v = tb.rng.randrange(256)
            await tb.wr(TIMING, v)
            got = await tb.rd(0x00, 7)   # ID0,ID1,VER,CTRL,SRCA,SRCB,TIMING
            assert got[0:3] == [0x42, 0x4E, 0x02] and got[TIMING] == v, (
                f"clk {period} ns, SCK=clk/{div}: read {got}, TIMING {v:#04x}")
            await tb.wr(SRCA, v & 0x1F, (v ^ 0xFF) & 0x1F)
            assert await tb.rd(SRCA, 2) == [v & 0x1F, (v ^ 0xFF) & 0x1F], f"clk {period} ns, SCK=clk/{div}: SRCA/SRCB burst"
    tb.sck_div = 16
    await tb.set_clock(100.0)


@gl_safe
async def test_spi_below_clk8_characterisation(dut):
    """Informational: SCK faster than clk/8 is outside the spec. Logs which rates
    still work (no assertion beyond the spec limit)."""
    tb = TB(dut, "test_spi_below_clk8_characterisation")
    await tb.start()
    for div in (2, 4, 6):
        ok = 0
        for _ in range(8):
            v = tb.rng.randrange(256)
            await tb.wr(TIMING, v, div=div)
            ok += (await tb.rd(TIMING, div=div)) == v
        tb.log.info(f"SCK = clk/{div}: {ok}/8 write/readback pairs correct (outside spec)")
    await tb.reset()
    # Back in spec: must work.
    await tb.wr(TIMING, 0x5A, div=8)
    assert await tb.rd(TIMING, div=8) == 0x5A


@gl_safe
async def test_debug_byte_and_armed_pin(dut):
    """SRCB[7:5] (DBG) selects the debug byte on uio_out (driven only when
    CTRL.UIOOE=1). uo_out[7] is FMAX_ARMED, no longer a debug-bit mux (v0.2)."""
    tb = TB(dut, "test_debug_byte_and_armed_pin")
    await tb.start()
    st, ca, cb = await tb.measure(SRC_CLK2, SRC_CLK2, gexp=10, extra_cycles=100)   # nonzero counts
    regs = await tb.rd(0x00, 0x12)
    lfsr = regs[0x0D] | regs[0x0E] << 8
    assert int(dut.uio_oe.value) == 0
    await tb.wr(CTRL, C_UIOOE)
    assert int(dut.uio_oe.value) == 0xFF, "CTRL.UIOOE=1 must drive all uio pins"
    srcb_base = await tb.rd(SRCB)   # keep the low 5 bits (source select) unchanged
    for sel in range(8):
        await tb.wr(SRCB, (srcb_base & 0x1F) | (sel << 5))
        misc = await tb.rd(MISC)
        exp = {0: lfsr & 0xFF, 1: lfsr >> 8, 2: ca & 0xFF, 3: cb & 0xFF,
               4: regs[STATUS], 5: regs[0x0F], 6: misc, 7: ca >> 8}[sel]
        got = int(dut.uio_out.value)
        assert got == exp, f"DBG sel {sel}: uio_out = {got:#04x}, expected {exp:#04x}"
        # uo_out[7] is FMAX_ARMED (0, CTRL.FMAX_EN=0 here) regardless of DBG select.
        assert (tb.uo() >> 7) & 1 == 0, f"DBG sel {sel}: uo_out[7] must be FMAX_ARMED (0), not a debug bit"
    await tb.wr(CTRL, 0)
    assert int(dut.uio_oe.value) == 0, "CTRL.UIOOE=0 must release uio"
    await tb.wr(SRCB, srcb_base)
