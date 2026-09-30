# SPDX-FileCopyrightText: (c) 2026 Parv Bhadra
# SPDX-License-Identifier: Apache-2.0
"""BINNER post-silicon bring-up script (TTGF26d, tt_um_parv_b_binner).

ONE file, MicroPython-compatible (no numpy, no dataclasses). Runs unmodified
against a real TT demo board (RP2350 + tt-micropython-firmware) and against
the virtual demo board in test/vboard/ (cocotb + fake `ttboard`/`machine`/
`time` modules). The only thing that differs between the two is which
`ttboard` package is on sys.path -- this script never checks for "sim" except
to label CSV rows / choose a default chip_id, and never branches its actual
measurement logic on it.

Usage on real hardware (mpremote, or an interactive MicroPython REPL):
    mpremote run binner_bringup.py
or:
    import binner_bringup
    binner_bringup.main(chip_id="parv01")

Register map: docs/SPEC.md v0.2 (VER=0x02). CSV schema: docs/CSV_SCHEMA.md.

Structure
  1. small portability shims (config.ini reader, CSV writer, time helpers)
  2. TTBoardHAL           -- thin wrapper around `ttboard`
  3. SpiBitBang / Regs    -- bit-banged SPI mode-0 register access
  4. LFSR model           -- pure-python mirror of src/binner_lfsr.v
  5. stage1..stage5       -- the bring-up stages
  6. main()               -- orchestrator
"""

import sys

try:
    import time
except ImportError:  # pragma: no cover
    time = None

# ---------------------------------------------------------------------------
# time.ticks_ms()/ticks_us()/ticks_diff()/sleep_ms()/sleep_us() are standard
# MicroPython. On a desktop/cocotb host `time` lacks them; add best-effort
# equivalents WITHOUT touching anything that already exists, so real firmware
# behaviour is never shadowed. On the virtual board these names are already
# provided (added in place, same trick) by test/vboard's fake time module,
# and are backed by simulated time via cocotb bridge/resume -- see
# test/vboard/fakemp/ttboard/_sim_bridge.py.
# ---------------------------------------------------------------------------
if not hasattr(time, "ticks_ms"):
    import time as _pytime

    def _ticks_ms():
        return int(_pytime.time() * 1000) & 0x3FFFFFFF

    def _ticks_us():
        return int(_pytime.time() * 1000000) & 0x3FFFFFFF

    def _ticks_diff(a, b):
        return a - b

    def _sleep_ms(n):
        _pytime.sleep(max(0, n) / 1000.0)

    def _sleep_us(n):
        _pytime.sleep(max(0, n) / 1000000.0)

    time.ticks_ms = _ticks_ms
    time.ticks_us = _ticks_us
    time.ticks_diff = _ticks_diff
    time.sleep_ms = _sleep_ms
    time.sleep_us = _sleep_us


SCRIPT_VERSION = "0.2.0"  # D-DTAP-RETUNE fix (disable-before-DTAP-change) + progress logging
CSV_SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# Register map (docs/SPEC.md v0.2) -- every register access in this file
# goes through Regs.read()/Regs.write(), which go through SpiBitBang, which
# is the only thing that talks to hardware/sim pins. Named constants only.
# ---------------------------------------------------------------------------
REG_ID0 = 0x00
REG_ID1 = 0x01
REG_VER = 0x02
REG_CTRL = 0x03
REG_SRCA = 0x04
REG_SRCB = 0x05
REG_TIMING = 0x06
REG_CMD = 0x07
REG_STATUS = 0x08
REG_CNTA_L = 0x09
REG_CNTA_H = 0x0A
REG_CNTB_L = 0x0B
REG_CNTB_H = 0x0C
REG_LFSR_L = 0x0D
REG_LFSR_H = 0x0E
REG_FFAIL = 0x0F
REG_FCAP = 0x10
REG_MISC = 0x11

ID0_EXPECT = 0x42
ID1_EXPECT = 0x4E
VER_EXPECT = 0x02

CTRL_RUN = 0x01
CTRL_FREE = 0x02
CTRL_LFSR_RUN = 0x04
CTRL_LFSR_GATED = 0x08
CTRL_FMAX_EN = 0x10
CTRL_FMAX_INV = 0x20
CTRL_UIOOE = 0x40

CMD_START = 0x01
CMD_CLEAR = 0x02
CMD_LFSR_RESEED = 0x04
CMD_FMAX_CLEAR = 0x08

STATUS_BUSY = 0x01
STATUS_DONE = 0x02
STATUS_OVF_A = 0x04
STATUS_OVF_B = 0x08
STATUS_SEEN_A = 0x10
STATUS_SEEN_B = 0x20
STATUS_TIMEOUT = 0x40

RESET_CTRL = 0x00
RESET_SRCA = 0x00
RESET_SRCB = 0x08
RESET_TIMING = 0x5A  # PINDIV=5, GEXP=10

# Sources (SRCA/SRCB[4:0])
SRC_NAND = 16
SRC_NOR = 17
SRC_FO4 = 18
SRC_DCH = 19
SRC_CLK2 = 20

# ui_in bit positions
UI_CS_N = 0
UI_SCK = 1
UI_MOSI = 2
UI_PINMODE = 3
UI_RINGSEL_LSB = 4  # ui_in[6:4]
UI_FMAX_RUN = 7

# uo_out bit positions
UO_LFSR15 = 0
UO_CNTA_BIT = 1
UO_CNTB_BIT = 2
UO_MISO = 3
UO_BUSY = 4
UO_FFAIL_ANY = 5
UO_DONE = 6
UO_FMAX_ARMED = 7

# Fmax tap stage counts, T0..T7 (docs/SPEC.md section 6)
FMAX_TAP_STAGES = (3, 4, 5, 6, 8, 10, 12, 14)

# Item list for stage 2 (ring characterisation). CLK2 is included both as a
# structure in its own right (known-answer cross-check) and as the forced
# channel-B partner for the DCH taps (see the DCH note below).
INV_RING_ITEMS = ["R%02d" % i for i in range(16)]
OTHER_RING_ITEMS = ["NAND", "NOR", "FO4"]
DCH_ITEMS = ["DCH%d" % k for k in range(8)]
ALL_RING_ITEMS = INV_RING_ITEMS + OTHER_RING_ITEMS + ["CLK2"] + DCH_ITEMS


def item_source(item):
    """item name -> (src_num, dtap). DTAP only exists on SRCA (see note in
    stage2_rings): the delay chain (source 19) has a single tap selector
    shared by both channels, so a DCH item can only ever be the channel-A
    member of a pair.
    """
    if item.startswith("DCH"):
        return SRC_DCH, int(item[3:])
    if item.startswith("R"):
        return int(item[1:]), 0
    if item == "NAND":
        return SRC_NAND, 0
    if item == "NOR":
        return SRC_NOR, 0
    if item == "FO4":
        return SRC_FO4, 0
    if item == "CLK2":
        return SRC_CLK2, 0
    raise ValueError("unknown item " + item)


# ---------------------------------------------------------------------------
# tiny config.ini reader (flat key=value, '#'/';' comments, optional
# [section] headers ignored -- keeps this MicroPython-safe without a real
# configparser)
# ---------------------------------------------------------------------------
def load_config(path="config.ini"):
    cfg = {}
    try:
        f = open(path)
    except OSError:
        return cfg
    try:
        for line in f:
            line = line.strip()
            if not line or line[0] in "#;" or line[0] == "[":
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    finally:
        f.close()
    return cfg


# ---------------------------------------------------------------------------
# CSV row writer -- streams rows to disk immediately (no in-memory table) so
# a long run doesn't grow RAM. See docs/CSV_SCHEMA.md for the exact columns.
# ---------------------------------------------------------------------------
CSV_COLUMNS = (
    "chip_id", "fingerprint", "run_id", "t_s", "stage", "test", "item",
    "rep", "x", "y", "unit", "aux", "temp_c", "flags",
)


def _csv_field(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return "%.6g" % v
    s = str(v)
    if "," in s or '"' in s or "\n" in s:
        s = '"' + s.replace('"', '""') + '"'
    return s


class CsvWriter(object):
    def __init__(self, path, meta):
        self.f = open(path, "w")
        for k in meta:
            self.f.write("#%s=%s\n" % (k, meta[k]))
        self.f.write(",".join(CSV_COLUMNS) + "\n")
        self.fingerprint = ""

    def row(self, t_s, stage, test, item, rep, x, y, unit, aux, temp_c, flags):
        vals = (
            self.chip_id, self.fingerprint, self.run_id, t_s, stage, test,
            item, rep, x, y, unit, aux, temp_c, flags,
        )
        self.f.write(",".join(_csv_field(v) for v in vals) + "\n")
        # flush often: MicroPython flash writes are buffered, and a bring-up
        # run that dies partway through should still leave usable data.
        try:
            self.f.flush()
        except Exception:
            pass

    def close(self):
        try:
            self.f.close()
        except Exception:
            pass


def flags_join(*flags):
    return ";".join(f for f in flags if f)


def aux_join(**kv):
    return ";".join("%s=%s" % (k, kv[k]) for k in kv)


# ---------------------------------------------------------------------------
# HAL -- everything that talks to the board/sim lives behind this class.
# Every field access goes through `ttboard`, exactly as documented for
# tt-micropython-firmware v3.1.1. On the virtual board `ttboard` is the fake
# package in test/vboard/fakemp/, providing the identical API.
# ---------------------------------------------------------------------------
class BringupError(Exception):
    pass


def _select_shuttle(tt, cfg):
    """Select the BINNER tile. Firmware v3.1.1 ships no ttgf26d shuttle
    index yet (404 today), so: try by name, then by the conventional
    attribute, then fall back to a configured tile address. `force_shuttle`
    in config.ini overrides everything (name or numeric address string).
    """
    project_name = cfg.get("project_name", "tt_um_parv_b_binner")
    tile_address = int(cfg.get("tile_address", "581"))
    force = cfg.get("force_shuttle", "").strip()

    def _enable(proj):
        proj.enable()

    if force:
        try:
            idx = int(force)
            _enable(tt.shuttle[idx])
            return "force_shuttle(addr=%d)" % idx
        except ValueError:
            _enable(getattr(tt.shuttle, force))
            return "force_shuttle(name=%s)" % force

    try:
        proj = tt.shuttle.find("binner")
        if proj is not None:
            _enable(proj)
            return "find('binner')"
    except Exception:
        pass

    try:
        proj = getattr(tt.shuttle, project_name)
        _enable(proj)
        return "attr(%s)" % project_name
    except Exception:
        pass

    _enable(tt.shuttle[tile_address])
    return "address(%d)" % tile_address


class TTBoardHAL(object):
    """Wraps ttboard.demoboard.DemoBoard. Every register access in this
    script funnels through SpiBitBang/Regs, which call write_ui()/read_uo()
    here -- there is no other path to the pins.
    """

    def __init__(self, cfg):
        import ttboard  # noqa: F401  (import guard: fail loudly if missing)
        from ttboard.demoboard import DemoBoard

        self.is_sim = bool(getattr(ttboard, "IS_SIM", False))
        self.tt = DemoBoard.get()
        self.selection_note = _select_shuttle(self.tt, cfg)

        try:
            from ttboard.mode import RPMode
            self.tt.mode = RPMode.ASIC_RP_CONTROL
        except Exception:
            pass

        try:
            from ttboard.util import platform as _plat
            self._plat = _plat
        except Exception:
            self._plat = None

        self._t0_ms = time.ticks_ms()
        self._clk_hz = 10000000
        self._ui_shadow = 0x01  # CS_N idle high, everything else 0 (matches reset)
        self.reset()

    # --- power / reset ---------------------------------------------------
    def reset(self):
        self.tt.reset_project(True)
        time.sleep_ms(1)
        self.tt.reset_project(False)
        time.sleep_ms(2)

    # --- clock -------------------------------------------------------------
    def set_clock(self, hz):
        try:
            self.tt.clock_project_PWM(hz, quiet=True)
        except TypeError:
            self.tt.clock_project_PWM(hz)
        achieved = getattr(self.tt, "auto_clocking_freq", None)
        self._clk_hz = achieved if achieved else hz
        return self._clk_hz

    def clock_hz(self):
        return self._clk_hz

    def clock_stop(self):
        try:
            self.tt.clock_project_stop()
        except Exception:
            pass

    # --- pins ----------------------------------------------------------
    # `_ui_shadow` mirrors the last byte written to ui_in. SpiBitBang reads
    # it to preserve whatever non-SPI bits (PINMODE, ring-select, FMAX_RUN)
    # are currently set instead of clobbering them on the next register
    # access -- set_ui_bit() and write_ui() are the only two ways ui_in ever
    # changes, and both keep this in sync.
    def write_ui(self, byte):
        byte &= 0xFF
        self._ui_shadow = byte
        if self._plat is not None:
            self._plat.write_ui_in_byte(byte)
        else:
            self.tt.ui_in.value = byte

    def read_uo(self):
        if self._plat is not None:
            return self._plat.read_uo_out_byte() & 0xFF
        return int(self.tt.uo_out.value) & 0xFF

    def set_ui_bit(self, idx, val):
        b = self._ui_shadow
        if val:
            b |= (1 << idx)
        else:
            b &= ~(1 << idx) & 0xFF
        self.write_ui(b)

    def read_uio(self):
        return int(self.tt.uio_in.value) & 0xFF

    # --- misc ------------------------------------------------------------
    def sleep_ms(self, n):
        time.sleep_ms(n)

    def sleep_us(self, n):
        time.sleep_us(n)

    def now_s(self):
        return time.ticks_diff(time.ticks_ms(), self._t0_ms) / 1000.0

    def temp_c(self):
        try:
            return float(self.tt.adc.core_temp)
        except Exception:
            return None

    def count_edges(self, uo_bit, window_ms):
        """Software polling edge counter on a uo_out bit (default/portable
        path). Only accurate while the toggle period is well above the
        polling loop's own period -- see bringup/README.md for the PIO-based
        alternative on real hardware at higher rates.
        """
        t0 = time.ticks_ms()
        last = (self.read_uo() >> uo_bit) & 1
        edges = 0
        samples = 0
        while time.ticks_diff(time.ticks_ms(), t0) < window_ms:
            v = (self.read_uo() >> uo_bit) & 1
            if v == 1 and last == 0:
                edges += 1
            last = v
            samples += 1
        elapsed_ms = time.ticks_diff(time.ticks_ms(), t0)
        return edges, max(1, elapsed_ms), samples


# ---------------------------------------------------------------------------
# Bit-banged SPI mode 0 (CPOL=0, CPHA=0), MSB first -- docs/SPEC.md section 3.
# Mirrors test/test.py's spi_xfer bit-for-bit (same code path philosophy:
# the cocotb smoke test and this bring-up script drive the pins identically).
# f_SCK <= f_clk/8 required, f_clk/16 recommended: half-period is sized off
# whatever f_clk the HAL last set (SPI is only ever used at the "safe" clock).
# ---------------------------------------------------------------------------
class SpiBitBang(object):
    def __init__(self, hal):
        self.hal = hal

    def _half_period_us(self):
        f_clk = self.hal.clock_hz() or 10000000
        # SCK period >= 16 clk periods -> half period >= 8 clk periods; use
        # 10 clk periods of margin, at least 1us (MicroPython sleep_us floor).
        hp_us = (10.0 * 1000000.0) / f_clk
        return max(1, int(hp_us + 0.999))

    def xfer(self, tx_bytes):
        hp = self._half_period_us()
        # Preserve whatever non-SPI bits (PINMODE/ring-select/FMAX_RUN) the
        # HAL currently has set on ui_in -- see TTBoardHAL._ui_shadow.
        base = self.hal._ui_shadow & ~(1 << UI_CS_N) & ~(1 << UI_SCK) & ~(1 << UI_MOSI)
        base &= 0xFF
        w = self.hal.write_ui
        r = self.hal.read_uo
        s = self.hal.sleep_us

        w(base | (1 << UI_CS_N))
        s(hp)
        w(base)  # CS_N low, SCK low
        s(hp)
        rx = []
        for b in tx_bytes:
            v = 0
            for i in range(7, -1, -1):
                mosi = (b >> i) & 1
                w(base | (mosi << UI_MOSI))
                s(hp)
                w(base | (mosi << UI_MOSI) | (1 << UI_SCK))
                v = (v << 1) | ((r() >> UO_MISO) & 1)
                s(hp)
            rx.append(v)
        w(base)  # SCK low
        s(hp)
        w(base | (1 << UI_CS_N))
        s(hp)
        return rx


class Regs(object):
    """Every register access goes through here -> SpiBitBang.xfer()."""

    def __init__(self, spi):
        self.spi = spi

    def write(self, addr, *data):
        self.spi.xfer([0x80 | (addr & 0x7F)] + list(data))

    def read(self, addr, n=1):
        r = self.spi.xfer([addr & 0x7F] + [0] * n)
        return r[1:] if n > 1 else r[1]

    def read16(self, addr_l):
        lo, hi = self.read(addr_l, 2)
        return lo | (hi << 8)

    def poll_done(self, max_iters=4000, delay_us=20):
        for _ in range(max_iters):
            st = self.read(REG_STATUS)
            if st & STATUS_DONE:
                return st
            self.spi.hal.sleep_us(delay_us)
        return None  # timed out at the SPI-polling level (not STATUS.TIMEOUT)


# ---------------------------------------------------------------------------
# Pure-python LFSR model, mirroring src/binner_lfsr.v exactly (including the
# de Bruijn zero-insertion) for the stage-1 known-answer test.
# ---------------------------------------------------------------------------
def lfsr_next(q):
    zero15 = 1 if (q & 0x7FFF) == 0 else 0
    fb = ((q >> 15) & 1) ^ ((q >> 14) & 1) ^ ((q >> 12) & 1) ^ ((q >> 3) & 1) ^ zero15
    return ((q << 1) | fb) & 0xFFFF


def lfsr_steps(seed, n):
    q = seed
    for _ in range(n):
        q = lfsr_next(q)
    return q


LFSR_SEED = 0xACE1


# ---------------------------------------------------------------------------
# measurement primitive shared by stages 1/2/3/4
# ---------------------------------------------------------------------------
def configure_and_measure(regs, src_a, src_b, dtap, gexp, pindiv=5, extra_ctrl=0):
    # docs/SPEC.md section 5 (DECISIONS.md D-DTAP-RETUNE): source 19's (the
    # delay-chain ring's) tap-select mux is a purely asynchronous
    # combinational tree inside the ring's own live feedback loop --
    # changing DTAP (packed into SRCA[7:5]) while the ring is still running
    # is an async-mux-in-a-loop hazard that can mode-lock it onto an
    # unintended, much shorter path through the tree. This function is the
    # single shared entry point for every paired measurement (stages 1/2/4),
    # including stage2_rings' back-to-back DCH0->DCH1->...->DCH7 sweep,
    # where consecutive calls would otherwise leave CTRL.RUN=1 across a live
    # SRCA/DTAP change. Rather than special-case "only when the previous
    # source was also 19", always disable every ring (CTRL.RUN=0) before
    # writing a new SRCA and re-enable after -- unconditionally safe for
    # every source, and the cost is one cheap extra register write per
    # measurement.
    regs.write(REG_CTRL, 0)
    regs.write(REG_SRCA, (src_a & 0x1F) | ((dtap & 0x07) << 5))
    regs.write(REG_SRCB, (src_b & 0x1F))
    regs.write(REG_TIMING, (gexp & 0x0F) | ((pindiv & 0x0F) << 4))
    regs.write(REG_CTRL, (CTRL_RUN | extra_ctrl) & 0x7F)
    regs.write(REG_CMD, CMD_START)
    st = regs.poll_done()
    if st is None:
        return None
    ca = regs.read16(REG_CNTA_L)
    cb = regs.read16(REG_CNTB_L)
    return {"status": st, "ca": ca, "cb": cb}


def auto_gexp(regs, src_a, src_b, dtap, pindiv=5, target=20000, gexp0=8):
    """Iteratively range the gate length (GEXP) so both channels land near
    `target` counts without overflowing the 16-bit ring-domain counters.
    Deliberately avoids math.log for MicroPython-portability; instead it
    doubles/halves the counts it already measured until they bracket the
    target.
    """
    gexp = gexp0
    result = None
    for _ in range(6):
        gexp = max(0, min(15, gexp))
        m = configure_and_measure(regs, src_a, src_b, dtap, gexp, pindiv)
        if m is None:
            return gexp0, None
        result = m
        st = m["status"]
        cmax = max(m["ca"], m["cb"])
        if (st & (STATUS_OVF_A | STATUS_OVF_B)) or cmax >= 60000:
            gexp -= 3
            continue
        if cmax == 0:
            gexp += 4
            continue
        if cmax < target // 4:
            shift = 0
            c = cmax
            while c < target and shift < 8:
                c <<= 1
                shift += 1
            gexp += shift
            continue
        if cmax > target * 4:
            shift = 0
            c = cmax
            while c > target and shift < 8:
                c >>= 1
                shift += 1
            gexp -= shift
            continue
        break
    return gexp, result


# ---------------------------------------------------------------------------
# Stage 1: sanity
# ---------------------------------------------------------------------------
def stage1_sanity(hal, regs, csv, log):
    t = csv.row
    ok_all = True

    # ID/VER -------------------------------------------------------------
    ids = regs.read(REG_ID0, 3)
    id_ok = (ids == [ID0_EXPECT, ID1_EXPECT, VER_EXPECT])
    t(hal.now_s(), 1, "id", "ID", 0, None, 1 if id_ok else 0, "bool",
      aux_join(id0="0x%02x" % ids[0], id1="0x%02x" % ids[1], ver="0x%02x" % ids[2]),
      hal.temp_c(), "" if id_ok else "SUSPECT")
    if not id_ok:
        log("ABORT: BINNER did not respond as expected on register 0x00-0x02 "
            "(got %r, expected [0x42,0x4E,0x02]). Check: SPI wiring "
            "(ui_in[0..2]/uo_out[3]), tile selection/address, and that "
            "reset_project(False) was called after enable(). Aborting "
            "further stages." % ids)
        return False

    # walking-pattern write/readback on CTRL/SRCA/SRCB/TIMING ------------
    regs_to_test = [
        ("CTRL", REG_CTRL, 0x7F, RESET_CTRL),
        ("SRCA", REG_SRCA, 0xFF, RESET_SRCA),
        ("SRCB", REG_SRCB, 0xFF, RESET_SRCB),
        ("TIMING", REG_TIMING, 0xFF, RESET_TIMING),
    ]
    for name, addr, mask, reset_val in regs_to_test:
        pass_ok = True
        patterns = [1 << i for i in range(8) if (mask >> i) & 1]
        patterns += [(~p) & mask for p in patterns]
        for pat in patterns:
            regs.write(addr, pat & 0xFF)
            rb = regs.read(addr) & mask
            if rb != (pat & mask):
                pass_ok = False
        regs.write(addr, reset_val)  # restore a known-good state
        t(hal.now_s(), 1, "readback", name, 0, None, 1 if pass_ok else 0,
          "bool", "", hal.temp_c(), "" if pass_ok else "SUSPECT")
        ok_all = ok_all and pass_ok

    # LFSR known-answer ----------------------------------------------------
    n_steps = 256
    k = 8  # 2**8 == 256
    regs.write(REG_CMD, CMD_LFSR_RESEED)
    regs.write(REG_CTRL, CTRL_LFSR_GATED)
    regs.write(REG_TIMING, (k & 0x0F) | (RESET_TIMING & 0xF0))
    regs.write(REG_CMD, CMD_START)
    st = regs.poll_done()
    lfsr_val = regs.read16(REG_LFSR_L) if st is not None else None
    exp = lfsr_steps(LFSR_SEED, n_steps)
    lfsr_ok = (st is not None) and (lfsr_val == exp)
    t(hal.now_s(), 1, "lfsr_kat", "N=%d" % n_steps, 0, n_steps,
      1 if lfsr_ok else 0, "bool",
      aux_join(sig="0x%04x" % (lfsr_val if lfsr_val is not None else 0),
               exp="0x%04x" % exp),
      hal.temp_c(), "" if lfsr_ok else "SUSPECT")
    regs.write(REG_CTRL, RESET_CTRL)
    ok_all = ok_all and lfsr_ok

    # clk/2 known-answer -----------------------------------------------
    k2 = 7
    gate = 1 << k2
    m = configure_and_measure(regs, SRC_CLK2, SRC_CLK2, 0, k2, RESET_TIMING >> 4)
    expect = gate // 2
    clk2_ok = (m is not None) and abs(m["ca"] - expect) <= 1 and abs(m["cb"] - expect) <= 1
    t(hal.now_s(), 1, "clk2_kat", "CLK2", 0, gate,
      m["ca"] if m else None, "count", aux_join(exp=expect),
      hal.temp_c(), "" if clk2_ok else "SUSPECT")
    ok_all = ok_all and clk2_ok

    # pin-mode divided-ring edge count on uo_out[1] -----------------------
    # PINDIV is chosen large enough that the software polling loop (whose
    # own per-sample overhead is itself a few hundred ns to ~1us, on real
    # MicroPython GPIO reads and, deliberately, in the virtual board's model
    # of that overhead -- see GPIO_READ_NS in
    # test/vboard/fakemp/ttboard/_sim_bridge.py) can Nyquist-sample the
    # divided output; PINDIV=10 divides a ~200MHz ring down to ~100-200kHz,
    # comfortably pollable. A too-small PINDIV here would silently alias.
    try:
        pindiv = 10  # divide by 2^(10+1) = 2048
        regs.write(REG_TIMING, (RESET_TIMING & 0x0F) | (pindiv << 4))
        regs.write(REG_SRCA, 0)  # R00
        regs.write(REG_SRCB, SRC_CLK2 << 0)
        regs.write(REG_CTRL, RESET_CTRL)
        ref = configure_and_measure(regs, 0, SRC_CLK2, 0, 10, pindiv)
        f_clk = hal.clock_hz()
        f_ref = (ref["ca"] * f_clk / 1024.0) if ref else None

        hal.set_ui_bit(UI_PINMODE, 1)
        hal.set_ui_bit(UI_RINGSEL_LSB, 0)
        hal.set_ui_bit(UI_RINGSEL_LSB + 1, 0)
        hal.set_ui_bit(UI_RINGSEL_LSB + 2, 0)
        hal.set_ui_bit(UI_FMAX_RUN, 0)  # bank A, s=0 -> R00
        hal.sleep_ms(2)
        edges, elapsed_ms, _ = hal.count_edges(UO_CNTA_BIT, 5)
        hal.set_ui_bit(UI_PINMODE, 0)
        divisor = 1 << (pindiv + 1)
        f_meas = edges * divisor * 1000.0 / elapsed_ms if elapsed_ms else None
        ratio = (f_meas / f_ref) if (f_meas and f_ref) else None
        pin_ok = ratio is not None and 0.5 < ratio < 2.0
        t(hal.now_s(), 1, "pinmode", "R00", 0, f_clk, f_meas, "Hz",
          aux_join(ref_hz=("%.3g" % f_ref) if f_ref else "", ratio=("%.3g" % ratio) if ratio else ""),
          hal.temp_c(), flags_join("PINMODE", "" if pin_ok else "SUSPECT"))
        ok_all = ok_all and pin_ok
    except Exception as e:
        t(hal.now_s(), 1, "pinmode", "R00", 0, None, None, "Hz",
          aux_join(error=str(e)), hal.temp_c(), flags_join("PINMODE", "SUSPECT"))
        ok_all = False

    regs.write(REG_CTRL, RESET_CTRL)
    regs.write(REG_SRCA, RESET_SRCA)
    regs.write(REG_SRCB, RESET_SRCB)
    regs.write(REG_TIMING, RESET_TIMING)
    return ok_all


# ---------------------------------------------------------------------------
# Stage 2: ring characterisation, every source, in A/B pairs.
# ---------------------------------------------------------------------------
def _pair_plan():
    items = INV_RING_ITEMS + OTHER_RING_ITEMS + ["CLK2"]
    pairs = []
    for i in range(0, len(items) - 1, 2):
        pairs.append((items[i], items[i + 1]))
    if len(items) % 2:
        pairs.append((items[-1], "CLK2"))
    # DCH taps: the delay-chain tap selector (SRCA[7:5]) is shared by both
    # channels, so a DCH item can only be the channel-A half of a pair --
    # partner it with CLK2 (a channel-B slot that needs no tap of its own).
    for item in DCH_ITEMS:
        pairs.append((item, "CLK2"))
    return pairs


def stage2_rings(hal, regs, csv, log, f_clk=10000000, repeats=5):
    hal.set_clock(f_clk)
    achieved_clk = hal.clock_hz()
    log("stage2: f_clk requested %d achieved %d" % (f_clk, achieved_clk))
    pindiv = 5
    pairs = _pair_plan()
    for pair_i, (item_a, item_b) in enumerate(pairs):
        src_a, dtap = item_source(item_a)
        src_b, _ = item_source(item_b)
        # Progress line per pair: on the virtual board each pair (auto-range
        # + `repeats` measurements) can take real wall-clock seconds even
        # though almost no simulated time elapses (cocotb bridge/resume
        # round-trip overhead per pin access, see test/vboard/fakemp/
        # ttboard/_sim_bridge.py's module docstring) -- without a line here,
        # a legitimately-progressing run can go visibly silent for minutes
        # at a time, indistinguishable from a hang from the console alone.
        log("stage2: pair %d/%d %s/%s" % (pair_i + 1, len(pairs), item_a, item_b))
        gexp, pilot = auto_gexp(regs, src_a, src_b, dtap, pindiv)
        for rep in range(repeats):
            m = configure_and_measure(regs, src_a, src_b, dtap, gexp, pindiv)
            temp = hal.temp_c()
            t_s = hal.now_s()
            gate = 1 << gexp
            if m is None:
                for item in (item_a, item_b):
                    csv.row(t_s, 2, "ring", item, rep, achieved_clk, None, "Hz",
                            aux_join(gate=gate, ch="?", pair=(item_b if item == item_a else item_a)),
                            temp, "TIMEOUT")
                continue
            st = m["status"]
            f_a = m["ca"] * achieved_clk / float(gate)
            f_b = m["cb"] * achieved_clk / float(gate)
            flags_a = flags_join(
                "OVF" if st & STATUS_OVF_A else "",
                "NOSEEN" if not (st & STATUS_SEEN_A) else "",
                "TIMEOUT" if st & STATUS_TIMEOUT else "",
            )
            flags_b = flags_join(
                "OVF" if st & STATUS_OVF_B else "",
                "NOSEEN" if not (st & STATUS_SEEN_B) else "",
                "TIMEOUT" if st & STATUS_TIMEOUT else "",
            )
            csv.row(t_s, 2, "ring", item_a, rep, achieved_clk, f_a, "Hz",
                    aux_join(cnt=m["ca"], gate=gate, ch="A", pair=item_b), temp, flags_a)
            csv.row(t_s, 2, "ring", item_b, rep, achieved_clk, f_b, "Hz",
                    aux_join(cnt=m["cb"], gate=gate, ch="B", pair=item_a), temp, flags_b)
    regs.write(REG_CTRL, RESET_CTRL)


# ---------------------------------------------------------------------------
# Stage 3: Fmax (at-speed checker), binary search per tap.
# ---------------------------------------------------------------------------
FMAX_SAFE_CLK = 10000000
FMAX_LO_HZ = 12000000
FMAX_HI_HZ = 125000000


def _fmax_arm_and_test(hal, regs, test_hz, window_ms, inv=False):
    """One arm-by-pin trial at test_hz. Returns (achieved_hz, fail_byte)."""
    hal.set_clock(FMAX_SAFE_CLK)
    regs.write(REG_CTRL, CTRL_FMAX_EN | (CTRL_FMAX_INV if inv else 0))
    regs.write(REG_CMD, CMD_FMAX_CLEAR)
    hal.set_ui_bit(UI_FMAX_RUN, 0)

    achieved = hal.set_clock(test_hz)
    hal.sleep_ms(2)  # let the new clock settle
    hal.set_ui_bit(UI_FMAX_RUN, 1)
    armed_seen = (hal.read_uo() >> UO_FMAX_ARMED) & 1
    hal.sleep_ms(window_ms)
    hal.set_ui_bit(UI_FMAX_RUN, 0)

    hal.set_clock(FMAX_SAFE_CLK)
    hal.sleep_ms(1)
    fail = regs.read(REG_FFAIL)
    regs.write(REG_CTRL, RESET_CTRL)
    return achieved, fail, armed_seen


def stage3_fmax(hal, regs, csv, log, trials=3, bisect_iters=7, window_ms=10,
                 lo_hz=FMAX_LO_HZ, hi_hz=FMAX_HI_HZ):
    n_taps = len(FMAX_TAP_STAGES)
    for k, stages in enumerate(FMAX_TAP_STAGES):
        item = "T%d" % k
        bit = 1 << k
        lo_req, hi_req = lo_hz, hi_hz
        log("stage3: tap %d/%d (%s, %d stages) starting" % (k + 1, n_taps, item, stages))

        # bracket sanity: confirm lo passes and hi fails; otherwise the tap
        # is off-scale in one direction and we record that instead of
        # bisecting nonsense.
        ach_lo, fail_lo, _ = _fmax_arm_and_test(hal, regs, lo_req, window_ms)
        lo_pass = not (fail_lo & bit)
        ach_hi, fail_hi, _ = _fmax_arm_and_test(hal, regs, hi_req, window_ms)
        hi_pass = not (fail_hi & bit)

        if lo_pass and hi_pass:
            csv.row(hal.now_s(), 3, "fmax", item, 0, None, ach_hi, "Hz",
                    aux_join(f_fail="", f_pass=ach_hi, note="OFFSCALE_HIGH"),
                    hal.temp_c(), "")
            continue
        if (not lo_pass) and (not hi_pass):
            csv.row(hal.now_s(), 3, "fmax", item, 0, None, ach_lo, "Hz",
                    aux_join(f_fail=ach_lo, f_pass="", note="OFFSCALE_LOW"),
                    hal.temp_c(), "SUSPECT")
            continue

        for it in range(bisect_iters):
            mid_req = (lo_req + hi_req) / 2.0
            fails = 0
            not_armed = 0
            achieved = mid_req
            for tr in range(trials):
                achieved, fail, armed_seen = _fmax_arm_and_test(hal, regs, mid_req, window_ms)
                if fail & bit:
                    fails += 1
                if not armed_seen:
                    not_armed += 1
            frac = fails / float(trials)
            # docs/SPEC.md section 6: uo_out[7] (FMAX_ARMED) should confirm
            # the checker was actually active during the test window: a
            # trial where it read back 0 means the pass/fail result for
            # that trial isn't trustworthy (never armed, so FFAIL couldn't
            # have set even at a frequency that should fail).
            csv.row(hal.now_s(), 3, "fmax_pt", item, it, achieved, frac,
                    "frac", aux_join(trials=trials, not_armed=not_armed),
                    hal.temp_c(), "SUSPECT" if not_armed else "")
            log("stage3: %s bisect %d/%d @ %.3gMHz frac_fail=%.2f" %
                (item, it + 1, bisect_iters, mid_req / 1.0e6, frac))
            if frac >= 0.5:
                hi_req = mid_req
            else:
                lo_req = mid_req

        ach_lo_final, _, _ = _fmax_arm_and_test(hal, regs, lo_req, window_ms)
        ach_hi_final, _, _ = _fmax_arm_and_test(hal, regs, hi_req, window_ms)
        csv.row(hal.now_s(), 3, "fmax", item, 0, None, ach_lo_final, "Hz",
                aux_join(f_fail=ach_hi_final, f_pass=ach_lo_final), hal.temp_c(), "")

    # FMAX_INV polarity self-test per tap: every tap must fail.
    for k, stages in enumerate(FMAX_TAP_STAGES):
        item = "T%d" % k
        bit = 1 << k
        achieved, fail, _ = _fmax_arm_and_test(hal, regs, 20000000, window_ms, inv=True)
        ok = bool(fail & bit)
        csv.row(hal.now_s(), 3, "fmax_inv", item, 0, achieved, 1 if ok else 0,
                "bool", "", hal.temp_c(), "" if ok else "SUSPECT")

    hal.set_clock(FMAX_SAFE_CLK)
    regs.write(REG_CTRL, RESET_CTRL)


# ---------------------------------------------------------------------------
# Stage 4: PUF -- repeated simultaneous paired measurements, majority vote.
# ---------------------------------------------------------------------------
def _puf_pairs():
    pairs = [(2 * n, 2 * n + 1) for n in range(8)]
    pairs += [(i, i + 8) for i in range(8)]
    return pairs


def _fold_hash48(values):
    """Deterministic, MicroPython-safe (no external libs) fold of the raw
    ratio history into 48 bits, used for the CSV_SCHEMA "12 hex digits of
    CRC-free raw ratio sign bits from all 120 pairs, compressed" tail.
    NOTE (documented judgement call, see bringup/README.md): the schema text
    references all C(16,2)=120 ring-pair combinations, but stage 4 only
    measures the 16 canonical pairs defined in CSV_SCHEMA.md (bit b00..b15)
    -- measuring all 120 pairs x 11 reps would add >7x runtime for stage 4
    with no defined use in docs/VARIATION_MODEL.md's recovery targets. This
    hash instead folds every raw ratio actually measured in stage 4, so it
    is still a full, deterministic function of the PUF data, and is stable
    enough for inter-chip Hamming-distance comparison by the (future)
    analysis pipeline. Flagged as an underspecified area in the final
    bring-up report.
    """
    h = 0xCBF29CE484222325 & 0xFFFFFFFFFFFF
    for v in values:
        iv = int(round(v * 1.0e6)) & 0xFFFFFFFF
        h ^= iv
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFF
    return h


def stage4_puf(hal, regs, csv, log, repeats=11, f_clk=10000000):
    hal.set_clock(f_clk)
    achieved_clk = hal.clock_hz()
    pairs = _puf_pairs()
    pindiv = 5
    # per-pair GEXP chosen once (reused across repeats for a stable window)
    gexps = []
    for (ia, ib) in pairs:
        gexp, _ = auto_gexp(regs, ia, ib, 0, pindiv)
        gexps.append(gexp)

    votes = [0] * 16
    all_ratios = []
    for rep in range(repeats):
        log("stage4: repeat %d/%d (16 pairs)" % (rep + 1, repeats))
        for nn, (ia, ib) in enumerate(pairs):
            gexp = gexps[nn]
            m = configure_and_measure(regs, ia, ib, 0, gexp, pindiv)
            temp = hal.temp_c()
            t_s = hal.now_s()
            item_a = "R%02d" % ia
            item_b = "R%02d" % ib
            if m is None:
                csv.row(t_s, 4, "puf_pair", "%s-%s" % (item_a, item_b), rep,
                        None, None, "ratio", "", temp, "TIMEOUT")
                continue
            ca, cb = m["ca"], m["cb"]
            ratio = (ca / float(cb) - 1.0) if cb else None
            bit = 1 if (ratio is not None and ratio > 0) else 0
            if ratio is not None:
                votes[nn] += bit
                all_ratios.append(ratio)
            csv.row(t_s, 4, "puf_pair", "%s-%s" % (item_a, item_b), rep,
                    None, ratio, "ratio", aux_join(ca=ca, cb=cb), temp, "")
            csv.row(t_s, 4, "puf_bit", "b%02d" % nn, rep, None, bit, "bit",
                    "", temp, "")

    majority_word = 0
    for nn in range(16):
        maj_bit = 1 if votes[nn] * 2 >= repeats else 0
        majority_word = (majority_word << 1) | maj_bit
    tail48 = _fold_hash48(all_ratios)
    fingerprint = "%04X%012X" % (majority_word, tail48)
    csv.fingerprint = fingerprint
    log("stage4: fingerprint = %s" % fingerprint)
    regs.write(REG_CTRL, RESET_CTRL)
    return fingerprint


# ---------------------------------------------------------------------------
# Stage 5 (optional): temperature vs. R00 frequency over time.
# ---------------------------------------------------------------------------
def stage5_temp(hal, regs, csv, log, n_samples=5, interval_ms=200, f_clk=10000000):
    hal.set_clock(f_clk)
    achieved_clk = hal.clock_hz()
    pindiv = 5
    gexp, _ = auto_gexp(regs, 0, SRC_CLK2, 0, pindiv)
    for i in range(n_samples):
        m = configure_and_measure(regs, 0, SRC_CLK2, 0, gexp, pindiv)
        temp = hal.temp_c()
        t_s = hal.now_s()
        if m is not None:
            f_r00 = m["ca"] * achieved_clk / float(1 << gexp)
            csv.row(t_s, 5, "ring", "R00", i, achieved_clk, f_r00, "Hz",
                    aux_join(cnt=m["ca"], gate=1 << gexp), temp, "")
        csv.row(t_s, 5, "temp", "CORE", i, None, temp, "C", "", temp, "")
        log("stage5: sample %d/%d temp=%.2fC" % (i + 1, n_samples, temp if temp is not None else -999.0))
        hal.sleep_ms(interval_ms)
    regs.write(REG_CTRL, RESET_CTRL)


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------
def _default_chip_id():
    try:
        return "chip%06x" % (time.ticks_us() & 0xFFFFFF)
    except Exception:
        return "chip000000"


def main(chip_id=None, config_path="config.ini", out_dir=None, reduced=False,
         run_stage5=True, log_fn=None):
    """Run the full bring-up sequence and write exactly one CSV file.

    reduced=True shrinks repeat counts / Fmax bisection depth / Fmax test
    windows (used by the virtual-board population runner to keep an N=20
    sweep tractable in wall-clock time; it is a *quantity* knob only -- the
    measurement code path is identical either way).
    """
    log = log_fn if log_fn is not None else (lambda s: print(s))

    cfg = load_config(config_path)
    if chip_id is None:
        chip_id = cfg.get("chip_id", None) or _default_chip_id()
    if out_dir is None:
        out_dir = cfg.get("out_dir", ".")
    f_clk_default = int(cfg.get("f_clk_default", "10000000"))

    log("BINNER bring-up %s starting for chip_id=%s" % (SCRIPT_VERSION, chip_id))

    hal = TTBoardHAL(cfg)
    log("shuttle selection: %s (sim=%s)" % (hal.selection_note, hal.is_sim))
    hal.set_clock(f_clk_default)
    spi = SpiBitBang(hal)
    regs = Regs(spi)

    run_id = "%s-%d" % (chip_id, time.ticks_ms())
    csv_path = "%s/binner_%s.csv" % (out_dir.rstrip("/"), chip_id)
    meta = {
        "schema_version": CSV_SCHEMA_VERSION,
        "script_version": SCRIPT_VERSION,
        "firmware": "ttboard(sim=%s)" % hal.is_sim,
        "board": "vboard" if hal.is_sim else "tt_demoboard",
        "f_clk_default": f_clk_default,
        "start_time": run_id,
    }
    csv = CsvWriter(csv_path, meta)
    csv.chip_id = chip_id
    csv.run_id = run_id

    try:
        log("stage1: sanity starting")
        ok = stage1_sanity(hal, regs, csv, log)
        if not ok:
            log("stage1 sanity FAILED for %s -- see rows with flags=SUSPECT; "
                "skipping stages 2-5." % chip_id)
            return csv_path
        log("stage1: sanity OK")

        ring_repeats = 2 if reduced else 5
        log("stage2: ring characterisation starting (%d repeats/pair)" % ring_repeats)
        stage2_rings(hal, regs, csv, log, f_clk=f_clk_default, repeats=ring_repeats)
        log("stage2: done")

        fmax_trials = 2 if reduced else 3
        fmax_iters = 4 if reduced else 7
        fmax_window = 2 if reduced else 10
        log("stage3: Fmax binary search starting (%d taps, %d iters, %d trials)" %
            (len(FMAX_TAP_STAGES), fmax_iters, fmax_trials))
        stage3_fmax(hal, regs, csv, log, trials=fmax_trials,
                    bisect_iters=fmax_iters, window_ms=fmax_window)
        log("stage3: done")

        puf_repeats = 5 if reduced else 11
        log("stage4: PUF starting (%d repeats x 16 pairs)" % puf_repeats)
        stage4_puf(hal, regs, csv, log, repeats=puf_repeats, f_clk=f_clk_default)

        if run_stage5:
            n5 = 2 if reduced else 5
            log("stage5: temperature log starting (%d samples)" % n5)
            stage5_temp(hal, regs, csv, log, n_samples=n5, f_clk=f_clk_default)

        log("bring-up complete for %s -> %s" % (chip_id, csv_path))
    finally:
        csv.close()
        hal.clock_stop()

    return csv_path


if __name__ == "__main__":
    main()
