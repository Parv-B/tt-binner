# SPDX-FileCopyrightText: © 2026 Parv Bhadra
# SPDX-License-Identifier: Apache-2.0
"""BINNER smoke test: runs in both RTL (BINNER_BEHAV) and gate-level mode.

Rings stay disabled throughout (gate-level simulation is zero-delay, and a
running ring would hang it). The counters are exercised with the clk/2 test
source.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

CLK_NS = 100  # 10 MHz


async def spi_xfer(dut, tx_bytes):
    """SPI mode 0 bit-bang, SCK = clk/16. Returns the bytes read on MISO."""
    rx = []
    ui = int(dut.ui_in.value) & ~0x07
    dut.ui_in.value = ui | 0x01  # CS_N high
    await ClockCycles(dut.clk, 8)
    dut.ui_in.value = ui  # CS_N low
    await ClockCycles(dut.clk, 8)
    for b in tx_bytes:
        r = 0
        for i in range(7, -1, -1):
            mosi = (b >> i) & 1
            dut.ui_in.value = ui | (mosi << 2)  # SCK low, set MOSI
            await ClockCycles(dut.clk, 8)
            dut.ui_in.value = ui | (mosi << 2) | 0x02  # SCK high: sample
            r = (r << 1) | ((int(dut.uo_out.value) >> 3) & 1)
            await ClockCycles(dut.clk, 8)
        rx.append(r)
    dut.ui_in.value = ui  # SCK low
    await ClockCycles(dut.clk, 8)
    dut.ui_in.value = ui | 0x01  # CS_N high
    await ClockCycles(dut.clk, 8)
    return rx


async def rd(dut, addr, n=1):
    r = await spi_xfer(dut, [addr & 0x7F] + [0] * n)
    return r[1:] if n > 1 else r[1]


async def wr(dut, addr, *data):
    await spi_xfer(dut, [0x80 | addr] + list(data))


async def reset(dut):
    clock = Clock(dut.clk, CLK_NS, unit="ns")
    cocotb.start_soon(clock.start())
    dut.ena.value = 1
    dut.ui_in.value = 0x01
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 10)


@cocotb.test()
async def test_smoke(dut):
    await reset(dut)
    assert int(dut.uio_oe.value) == 0, "uio must be inputs after reset"

    ids = await rd(dut, 0x00, 3)
    assert ids == [0x42, 0x4E, 0x02], f"ID/VER readback {ids}"

    # SRCA/SRCB registers (0x04/0x05) carry the 5-bit source in bits[4:0]
    await wr(dut, 0x04, 20)              # SRCA = clk/2
    await wr(dut, 0x05, 20)              # SRCB = clk/2
    assert (await rd(dut, 0x04)) & 0x1F == 20
    # GEXP = 7 -> gate = 128 clk cycles (0x06 low nibble)
    await wr(dut, 0x06, 0x07)
    await wr(dut, 0x03, 0x01)            # CTRL.RUN = 1
    await wr(dut, 0x07, 0x01)            # CMD.START
    for _ in range(300):
        st = await rd(dut, 0x08)
        if st & 0x02:
            break
    assert st & 0x02, f"measurement did not complete, STATUS={st:#x}"
    ca = (await rd(dut, 0x09)) | (await rd(dut, 0x0A)) << 8
    cb = (await rd(dut, 0x0B)) | (await rd(dut, 0x0C)) << 8
    dut._log.info(f"STATUS={st:#04x} CNTA={ca} CNTB={cb}")
    assert abs(ca - 64) <= 1 and abs(cb - 64) <= 1
    assert st & 0x30 == 0x30, "both channels must acknowledge"
