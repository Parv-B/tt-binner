# SPDX-FileCopyrightText: © 2026 Parv Bhadra
# SPDX-License-Identifier: Apache-2.0
"""Shared helpers and independent reference models for the BINNER cocotb tests.

Everything here is derived from docs/SPEC.md v0.2 (the contract), not from src/.

  * TB            : clock / reset / SPI master / measurement helpers
  * lfsr_*        : independent model of the SPEC section 7 LFSR
  * ring_* / tap_*: expected behavioural-model frequencies and delays from the
                    simulation plusargs (SPEC section 8)
  * GL            : True in gate-level mode (GATES=yes); tests that would start
                    a ring oscillator or need behavioural delays are skipped.
"""

import os
import random
import zlib

import cocotb
from cocotb.clock import Clock
from cocotb.simtime import get_sim_time
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge, Timer, with_timeout

# ---------------------------------------------------------------------------
# Simulation mode
# ---------------------------------------------------------------------------
def _pa():
    """Simulator plusargs ({} when imported outside a simulation, e.g. by pytest)."""
    return getattr(cocotb, "plusargs", None) or {}


GL = os.environ.get("GATES", "").lower() == "yes" or "GL_TEST" in _pa()
STRUCT = "STRUCT" in _pa()


def rtl_only(func=None, **kw):
    """cocotb.test that is skipped in gate-level mode (rings / behavioural delays / hierarchy)."""
    kw.setdefault("skip", GL)
    if func is None:
        return lambda f: cocotb.test(**kw)(f)
    return cocotb.test(**kw)(func)


def gl_safe(func=None, **kw):
    """cocotb.test that runs in RTL and gate-level mode (rings stay off; only
    source 20 (clk/2) and behaviour that does not depend on ring timing)."""
    if func is None:
        return lambda f: cocotb.test(**kw)(f)
    return cocotb.test(**kw)(func)


BASE_SEED = int(os.environ.get("BINNER_SEED", "20260929"))

# ---------------------------------------------------------------------------
# Register map (SPEC section 4, v0.2)
# ---------------------------------------------------------------------------
ID0, ID1, VER, CTRL, SRCA, SRCB, TIMING, CMD, STATUS = range(0x00, 0x09)
CNTA_L, CNTA_H, CNTB_L, CNTB_H = 0x09, 0x0A, 0x0B, 0x0C
LFSR_L, LFSR_H, FFAIL, FCAP, MISC = 0x0D, 0x0E, 0x0F, 0x10, 0x11

# CTRL bits (0x03)
C_RUN, C_FREE, C_LFSR_RUN, C_LFSR_GATED, C_FMAX_EN, C_FMAX_INV, C_UIOOE = (1 << i for i in range(7))
# CMD bits (0x07, write-1-to-trigger, one-cycle pulses)
K_START, K_CLEAR, K_RESEED, K_FCLR = (1 << i for i in range(4))
# STATUS bits (0x08). Bit 7 is not in the SPEC table but the RTL packs
# FMAX_ARMED there too (status = {f_armed, mstat}), mirroring uo_out[7].
S_BUSY, S_DONE, S_OVF_A, S_OVF_B, S_SEEN_A, S_SEEN_B, S_TIMEOUT, S_ARMED = (1 << i for i in range(8))
# MISC bits (0x11)
M_PINMODE, M_ACK_A, M_ACK_B, M_FMAX_PIN, M_FVALID, M_ENA, M_CNT_EN, M_RING_CLR = (1 << i for i in range(8))

# RW registers: address -> (reset value, writable/readback mask) (SPEC section 4)
RW_REGS = {
    CTRL: (0x00, 0x7F),     # bit 7 unused, always reads 0
    SRCA: (0x00, 0xFF),     # [4:0] source, [7:5] DTAP
    SRCB: (0x08, 0xFF),     # [4:0] source, [7:5] DBG
    TIMING: (0x5A, 0xFF),   # [3:0] GEXP, [7:4] PINDIV
}
# RO registers with a defined, input-independent reset value.
# MISC is checked separately: it reflects live inputs (ena, pinmode, ...).
RO_RESET = {
    ID0: 0x42, ID1: 0x4E, VER: 0x02, CMD: 0x00, STATUS: 0x00,
    CNTA_L: 0, CNTA_H: 0, CNTB_L: 0, CNTB_H: 0,
    LFSR_L: 0xE1, LFSR_H: 0xAC, FFAIL: 0x00, FCAP: 0x00,
}
MAPPED = set(RW_REGS) | set(RO_RESET) | {MISC}
UNMAPPED = [a for a in range(128) if a not in MAPPED]

# Debug byte select (SRCB[7:5]): 0 LFSR[7:0], 1 LFSR[15:8], 2 CNTA[7:0],
# 3 CNTB[7:0], 4 STATUS, 5 FFAIL, 6 MISC, 7 CNTA[15:8].
DBG_LFSR_L, DBG_LFSR_H, DBG_CNTA_L, DBG_CNTB_L, DBG_STATUS, DBG_FFAIL, DBG_MISC, DBG_CNTA_H = range(8)

# ---------------------------------------------------------------------------
# Sources (SPEC section 5)
# ---------------------------------------------------------------------------
N_PUF_RINGS = 16                       # sources 0..15: identical INV rings
SRC_NAND, SRC_NOR, SRC_FO4, SRC_DCHAIN = 16, 17, 18, 19
SRC_CLK2 = 20                          # clk/2 known-answer source
DEAD_SRCS = list(range(21, 32))        # constant 0
RING_SRCS = list(range(0, 20))         # sources gated by ren[19:0] (has an `en` input)
N_RINGS = 19                           # binner_ring instances: sources 0..18 (19 is the delay chain)

# Stage counts per ring source, for structural oscillation-period checks
# (period = 2 * N * t_arc). project.v: N_STG = 25 (INV/NAND/NOR rings),
# N_FO4 = 13 (FO4 ring, v0.2: was 25).
STAGE_COUNTS = {i: 25 for i in range(N_PUF_RINGS)}
STAGE_COUNTS[SRC_NAND] = 25
STAGE_COUNTS[SRC_NOR] = 25
STAGE_COUNTS[SRC_FO4] = 13

TAPPOS = (3, 4, 5, 6, 8, 10, 12, 14)    # binner_dchain stage counts at each Fmax tap


def pack_srca(src, dtap=0):
    return (src & 0x1F) | ((dtap & 0x07) << 5)


def pack_srcb(src, dbg=0):
    return (src & 0x1F) | ((dbg & 0x07) << 5)


def gate_len(gexp):
    """gate = 2**GEXP clk cycles (SPEC section 4/5)."""
    return 1 << (gexp & 0x0F)


# ---------------------------------------------------------------------------
# Independent LFSR model (SPEC section 7)
# x^16 + x^15 + x^13 + x^4 + 1, Fibonacci, shift left, de Bruijn zero insertion.
# Taps derived from the polynomial exponents: exponent e -> state bit e-1.
# ---------------------------------------------------------------------------
LFSR_SEED = 0xACE1
LFSR_POLY_EXPONENTS = (16, 15, 13, 4)


def lfsr_next(q, debruijn=True):
    fb = 0
    for e in LFSR_POLY_EXPONENTS:
        fb ^= (q >> (e - 1)) & 1
    if debruijn and (q & 0x7FFF) == 0:
        fb ^= 1
    return ((q << 1) & 0xFFFF) | fb


def lfsr_advance(q, n):
    for _ in range(n):
        q = lfsr_next(q)
    return q


def lfsr_distance(a, b, limit=65536):
    """Number of steps from state a to state b (None if not within limit)."""
    q = a
    for n in range(limit + 1):
        if q == b:
            return n
        q = lfsr_next(q)
    return None


# ---------------------------------------------------------------------------
# Behavioural-model expectations (SPEC section 8)
# ---------------------------------------------------------------------------
def _plusarg_int(name, default):
    v = _pa().get(name)
    return int(v) if v not in (None, True) else default


def ring_hp_fs(idx):
    return _plusarg_int(f"RING{idx}_HP_FS", 2_500_000 + idx * 1000)


def ring_freq_hz(idx):
    return 1e15 / (2 * ring_hp_fs(idx))


def dstg_fs(i):
    return _plusarg_int(f"DSTG{i}_FS", 3_400_000)


def dovh_fs():
    return _plusarg_int("DCHAIN_OVH_FS", 600_000)


def tap_delay_fs(k):
    """Launch -> tap k delay in the behavioural chain: overhead + stages 1..TAPPOS[k]."""
    return dovh_fs() + sum(dstg_fs(i) for i in range(1, TAPPOS[k] + 1))


def chain_ring_freq_hz(k):
    """Source 19 in ring mode: period = 2 * (overhead + chain(tap))."""
    return 1e15 / (2 * tap_delay_fs(k))


def bits(v):
    return [(v >> i) & 1 for i in range(8)]


# ---------------------------------------------------------------------------
# Testbench driver
# ---------------------------------------------------------------------------
class TB:
    def __init__(self, dut, name="test"):
        self.dut = dut
        self.log = dut._log
        self.clock = None
        self.tclk_fs = None
        self.ui_hi = 0x00       # ui_in[7:3], owned by the test
        self.spi = 0x01         # ui_in[2:0] = {MOSI, SCK, CS_N}
        self.sck_div = 16       # SCK period in clk periods
        self.seed = (BASE_SEED ^ zlib.crc32(name.encode())) & 0xFFFFFFFF
        self.rng = random.Random(self.seed)
        self.log.info(f"[{name}] random seed = {self.seed} (BINNER_SEED={BASE_SEED})")

    # ---- clock / time ---------------------------------------------------
    async def set_clock(self, period_ns, clean=True):
        """(Re)start clk with the given period. clean=False switches immediately
        (can produce a runt pulse, like a PWM retune glitch)."""
        fs = int(round(period_ns * 1e6))
        fs -= fs % 2
        if self.clock is not None:
            if clean:
                await FallingEdge(self.dut.clk)
            self.clock.stop()
        self.clock = Clock(self.dut.clk, fs, unit="fs")
        self.clock.start(start_high=False)
        self.tclk_fs = fs

    @property
    def tclk_ns(self):
        return self.tclk_fs / 1e6

    @property
    def fclk_hz(self):
        return 1e15 / self.tclk_fs

    async def wait_fs(self, fs):
        fs = int(fs)
        if fs > 0:
            await Timer(fs, unit="fs")

    async def cycles(self, n):
        await self.wait_fs(n * self.tclk_fs)

    async def edges(self, n):
        await ClockCycles(self.dut.clk, n)

    @staticmethod
    def now_fs():
        return get_sim_time("fs")

    # ---- reset ---------------------------------------------------------
    async def start(self, period_ns=100.0, ena=1):
        await self.set_clock(period_ns)
        await self.reset(ena=ena)

    async def reset(self, cycles=10, ena=1):
        self.ui_hi = 0
        self.spi = 0x01
        self.dut.ena.value = ena
        self._drive()
        self.dut.uio_in.value = 0
        self.dut.rst_n.value = 0
        await self.cycles(cycles)
        self.dut.rst_n.value = 1
        await self.cycles(cycles)

    # ---- pins ------------------------------------------------------------
    def _drive(self):
        self.dut.ui_in.value = (self.ui_hi & 0xF8) | (self.spi & 0x07)

    def set_ui_hi(self, v):
        self.ui_hi = v & 0xF8
        self._drive()

    def set_pinmode(self, pm, sel=0, bank=0):
        self.set_ui_hi((pm << 3) | ((sel & 7) << 4) | ((bank & 1) << 7))

    def set_fmax_pin(self, v):
        self.set_ui_hi((self.ui_hi & 0x7F) | ((v & 1) << 7))

    def uo(self):
        return int(self.dut.uo_out.value)

    def pin(self, name):
        return int(getattr(self.dut, name).value)

    # ---- SPI master (mode 0, MSB first) ---------------------------------
    async def xfer(self, tx, div=None, abort_after_bits=None):
        """Full-duplex SPI transaction. Returns the bytes sampled on MISO.
        abort_after_bits: raise CS_N after that many bits (mid-byte abort)."""
        div = div or self.sck_div
        half = self.tclk_fs * div // 2
        self.spi = 0x00                    # CS_N low, SCK low
        self._drive()
        await self.wait_fs(half)
        rx, nbits = [], 0
        for b in tx:
            r = 0
            for i in range(7, -1, -1):
                mosi = (b >> i) & 1
                self.spi = mosi << 2       # SCK falls, MOSI changes
                self._drive()
                await self.wait_fs(half)
                r = (r << 1) | self.pin("miso_pin")   # value at the rising edge
                self.spi = (mosi << 2) | 0x02         # SCK rises
                self._drive()
                await self.wait_fs(half)
                nbits += 1
                if abort_after_bits is not None and nbits >= abort_after_bits:
                    self.spi = 0x01
                    self._drive()
                    await self.wait_fs(max(half, 8 * self.tclk_fs))
                    rx.append(r)
                    return rx
            rx.append(r)
        self.spi = 0x00
        self._drive()
        await self.wait_fs(half)
        self.spi = 0x01                    # CS_N high
        self._drive()
        await self.wait_fs(max(half, 8 * self.tclk_fs))
        return rx

    async def rd(self, addr, n=None, div=None):
        """Read one register (n=None) or a burst of n registers."""
        cnt = 1 if n is None else n
        r = await self.xfer([addr & 0x7F] + [0] * cnt, div=div)
        assert r[0] == 0, f"MISO must be 0 during the command byte, got {r[0]:#04x}"
        return r[1] if n is None else r[1:]

    async def wr(self, addr, *data, div=None):
        await self.xfer([0x80 | (addr & 0x7F)] + list(data), div=div)

    async def rd16(self, addr):
        lo, hi = await self.rd(addr, 2)
        return lo | (hi << 8)

    # ---- measurement -----------------------------------------------------
    async def set_timing(self, gexp=None, pindiv=None):
        """Read-modify-write TIMING (0x06): [3:0] GEXP, [7:4] PINDIV."""
        cur = await self.rd(TIMING)
        g = (cur & 0x0F) if gexp is None else (gexp & 0x0F)
        p = ((cur >> 4) & 0x0F) if pindiv is None else (pindiv & 0x0F)
        val = (p << 4) | g
        await self.wr(TIMING, val)
        return val

    async def wait_done(self, max_cycles):
        if self.pin("done_pin") == 1 and self.pin("busy_pin") == 0:
            return
        await with_timeout(RisingEdge(self.dut.done_pin), int(max_cycles * self.tclk_fs), "fs")

    async def measure(self, srca=None, srcb=None, gexp=None, ctrl=None, extra_cycles=400):
        """Configure (optional), START, wait for DONE, return (status, cnta, cntb)."""
        if srca is not None or srcb is not None:
            assert srca is not None and srcb is not None
            await self.wr(SRCA, srca, srcb)
        if gexp is not None:
            await self.set_timing(gexp=gexp)
        if ctrl is not None:
            await self.wr(CTRL, ctrl)
        g = gate_len(gexp) if gexp is not None else gate_len(await self.rd(TIMING) & 0x0F)
        await self.wr(CMD, K_START)
        await self.wait_done(max(g, 1) + extra_cycles)
        return await self.read_result()

    async def read_result(self):
        r = await self.rd(STATUS, 5)   # STATUS, CNTA_L, CNTA_H, CNTB_L, CNTB_H
        return r[0], r[1] | (r[2] << 8), r[3] | (r[4] << 8)

    # ---- edge timing -----------------------------------------------------
    async def period_of(self, sig, n_edges, timeout_fs):
        """Average period (fs) of signal sig over n_edges rising edges."""
        async def _run():
            await RisingEdge(sig)
            t0 = self.now_fs()
            for _ in range(n_edges):
                await RisingEdge(sig)
            return (self.now_fs() - t0) / n_edges
        return await with_timeout(_run(), int(timeout_fs), "fs")


def ring_en_handles(dut):
    """Hierarchical probes of the 20 ring enables (sources 0..19). RTL only."""
    up = dut.user_project
    h = [up.g_puf[i].u_ring.en for i in range(N_PUF_RINGS)]
    h += [up.u_ring_nand.en, up.u_ring_nor.en, up.u_ring_fo4.en, up.u_dchain.ring_en]
    return h


def read_ring_enables(dut):
    return [int(h.value) for h in ring_en_handles(dut)]
