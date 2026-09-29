#!/usr/bin/env python3
"""BINNER physical-verification helper library (pure Python 3, stdlib only).

Shared by tools/netlist_audit.py, tools/sdf_predict.py, tools/place_extract.py
and tools/metrics_summary.py:

  * parse_verilog()  - flat gate-level Verilog (yosys nl.v, OpenROAD nl.v/pnl.v),
                       escaped identifiers, power pins, assign aliases.
  * parse_sdf()      - SDF 3.0 as written by OpenSTA (IOPATH, COND, INTERCONNECT,
                       TIMINGCHECK), hierarchical names with backslash escapes.
  * parse_def()      - DEF COMPONENTS / PINS / NETS / DIEAREA.
  * parse_liberty_cells() - NLDM subset (pin caps, timing tables) of selected cells.
  * parse_spef_caps()- total capacitance per net from SPEF (*D_NET lines).
  * BINNER structure spec: expected ring / delay-chain / Fmax instances.

Every format detail here was checked against real LibreLane 3 / OpenROAD output
from this repository's CI:
  * commit 4673f5b (GDS_logs artifact) -- the FAILING first harden (RSZ-3006 on
    the NAND ring enable net; fixed by adding an explicit enbuf_notouch_ BUF_1
    stage, see src/binner_ring.v).
  * commit 908c9e1 (feat/must @ b39a875b17a9abd0fa73d2f7f59533e681f4e61b) -- the
    GREEN re-harden this module's spec is written against: FO4 ring is 13
    stages (N_FO4 in project.v, was 25), the NAND ring enable is buffered
    through a hand-instantiated enbuf_notouch_ BUF_1, and the Fmax launch/
    capture flops are named "*_keep_*" (kept-not-optimized-away, but NOT
    RSZ_DONT_TOUCH_RX-matched: their CLK/RN pins sit on high-fanout nets the
    resizer and CTS are free to buffer; only the chain nets they sample are
    notouch_). See DECISIONS.md D-DONTTOUCH.
"""
import os
import re
import math
import glob

LIB = "gf180mcu_fd_sc_mcu7t5v0__"
POWER_PINS = {"VDD", "VSS", "VNW", "VPW", "VPWR", "VGND"}

# ----------------------------------------------------------------------------
# BINNER expected structure (mirrors src/binner_ring.v, binner_dchain.v,
# binner_fmax.v, project.v). Kept here so every tool uses one definition.
# ----------------------------------------------------------------------------
N_STG = 25    # stages: PUF/INV, NAND, NOR rings (project.v localparam N_STG)
N_FO4 = 13    # stages: FO4 ring only (project.v localparam N_FO4; was 25 pre-908c9e1)
N_STAGES = N_STG   # back-compat alias; DO NOT use for the FO4 ring -- see RINGS
TAPPOS = [3, 4, 5, 6, 8, 10, 12, 14]   # DLYD_1 stages before each Fmax tap
N_DLY = 14
KIND_NAMES = {0: "INV", 1: "NAND", 2: "NOR", 3: "FO4"}
# (instance-path prefix, KIND, src index, stage count N for *this* ring)
RINGS = ([("g_puf[%d].u_ring" % i, 0, i, N_STG) for i in range(16)] +
         [("u_ring_nand", 1, 16, N_STG), ("u_ring_nor", 2, 17, N_STG),
          ("u_ring_fo4", 3, 18, N_FO4)])
RING_N = {prefix: n for prefix, _, _, n in RINGS}
DCHAIN = "u_dchain"
FMAX = "u_fmax"
NOTOUCH = "notouch_"
KEEP = "keep_"   # Fmax launch/capture flops: kept, but deliberately not notouch_

INV1 = LIB + "inv_1"
BUF1 = LIB + "buf_1"
NAND2 = LIB + "nand2_1"
NOR2 = LIB + "nor2_1"
MUX2 = LIB + "mux2_2"
DLY = LIB + "dlyd_1"
DFFRN = LIB + "dffrnq_1"

MID = r"(?:[^.]+\.)*"   # any generate-block path (genblk1.g_inv.g_plain. ...)


def ring_label(prefix):
    return prefix.replace(".u_ring", "").replace("u_ring_", "ring_")


def ring_stage_cell(kind, i):
    if kind == 1:
        return NAND2
    if kind == 2:
        return NOR2
    return NAND2 if i == 0 else INV1


def loop_pin(cell):
    return "I" if cell.endswith("inv_1") or "__inv_" in cell else "A1"


def classify_notouch(name):
    """Map a (unescaped) instance name to a structural role, or None.

    Covers only RSZ_DONT_TOUCH_RX-matched ("notouch_") instances. The Fmax
    launch/capture flops ("*_keep_*") are intentionally NOT notouch_ (their
    CLK/RN may be buffered/CTS'd) and are classified separately by
    classify_keep().
    """
    for prefix, kind, src, n in RINGS:
        p = re.escape(prefix)
        m = re.match(r"^%s\.g_stg\[(\d+)\]\.%sstg_notouch_$" % (p, MID), name)
        if m:
            return ("ring_stage", prefix, int(m.group(1)))
        m = re.match(r"^%s\.g_stg\[(\d+)\]\.%sld([012])_notouch_$" % (p, MID), name)
        if m and kind == 3:
            return ("ring_load", prefix, (int(m.group(1)), int(m.group(2))))
        if re.match(r"^%s\.%stap_notouch_$" % (p, MID), name):
            return ("ring_tap", prefix, None)
        if kind == 2 and re.match(r"^%s\.%senb_notouch_$" % (p, MID), name):
            return ("ring_enb", prefix, None)
        if kind == 1 and re.match(r"^%s\.%senbuf_notouch_$" % (p, MID), name):
            return ("ring_enbuf", prefix, None)
    d = re.escape(DCHAIN)
    if re.match(r"^%s\.%sdmx_notouch_$" % (d, MID), name):
        return ("dc_inmux", DCHAIN, None)
    m = re.match(r"^%s\.g_stg\[(\d+)\]\.%sdly_notouch_$" % (d, MID), name)
    if m:
        return ("dc_dly", DCHAIN, int(m.group(1)))
    m = re.match(r"^%s\.%stm([0-6])_notouch_$" % (d, MID), name)
    if m:
        return ("dc_tapmux", DCHAIN, int(m.group(1)))
    if re.match(r"^%s\.%sdfbg_notouch_$" % (d, MID), name):
        return ("dc_fbnand", DCHAIN, None)
    if re.match(r"^%s\.%sdtap_notouch_$" % (d, MID), name):
        return ("dc_tap", DCHAIN, None)
    return None


def classify_keep(name):
    """Map a (unescaped) instance name to an Fmax "*_keep_*" role, or None."""
    f = re.escape(FMAX)
    if re.match(r"^%s\.%sflaunch_keep_$" % (f, MID), name):
        return ("fm_launch", FMAX, None)
    m = re.match(r"^%s\.g_cap\[(\d+)\]\.%sfcap_keep_$" % (f, MID), name)
    if m:
        return ("fm_cap", FMAX, int(m.group(1)))
    return None


def expected_notouch_counts():
    """Expected number of notouch_ instances per (role, cell type)."""
    c = {}

    def add(role, cell, n=1):
        c[(role, cell)] = c.get((role, cell), 0) + n
    for prefix, kind, _, n in RINGS:
        for i in range(n):
            add("ring_stage", ring_stage_cell(kind, i))
        add("ring_tap", INV1)
        if kind == 2:
            add("ring_enb", INV1)
        if kind == 1:
            add("ring_enbuf", BUF1)
        if kind == 3:
            add("ring_load", INV1, 3 * n)
    add("dc_inmux", MUX2)
    add("dc_dly", DLY, N_DLY)
    add("dc_tapmux", MUX2, 7)
    add("dc_fbnand", NAND2)
    add("dc_tap", INV1)
    return c


def expected_keep_counts():
    """Expected number of "*_keep_*" Fmax flop instances per (role, cell type)."""
    return {("fm_launch", DFFRN): 1, ("fm_cap", DFFRN): 8}


def cell_base(cell):
    """gf180mcu_fd_sc_mcu7t5v0__inv_2 -> ('inv', '2')."""
    s = cell[len(LIB):] if cell.startswith(LIB) else cell
    m = re.match(r"^(.*?)_(\d+)$", s)
    return (m.group(1), m.group(2)) if m else (s, "")


def is_output_pin(cell, pin):
    """Output pins of gf180mcu_fd_sc_mcu7t5v0 cells (checked against the PDK LEF):
    Z, ZN, Q, QN, CO; S only on the adders (addf/addh); S on muxes is an input."""
    if pin in ("Z", "ZN", "Q", "QN", "CO"):
        return True
    if pin == "S" and re.search(r"__add[fh]_", cell):
        return True
    return False


def is_buf_or_inv(cell):
    b, _ = cell_base(cell)
    return b in ("buf", "clkbuf", "inv", "clkinv", "dlya", "dlyb", "dlyc", "dlyd", "hold")


def is_inverting_1in(cell):
    b, _ = cell_base(cell)
    return b in ("inv", "clkinv")


def is_sequential(cell):
    b, _ = cell_base(cell)
    return b.startswith(("dff", "sdff", "lat", "icg"))


def is_antenna(cell):
    return cell_base(cell)[0] == "antenna"


def is_physical_only(cell):
    b = cell_base(cell)[0]
    return b in ("endcap", "filltie", "fill", "fillcap") or b.startswith("fill")


# ----------------------------------------------------------------------------
# Gate-level Verilog
# ----------------------------------------------------------------------------
_VTOK = re.compile(r"""
    (?P<ws>\s+)
  | (?P<lc>//[^\n]*)
  | (?P<bc>/\*.*?\*/)
  | (?P<attr>\(\*.*?\*\))
  | (?P<esc>\\\S+)
  | (?P<const>\d*\s*'[sS]?[bBoOdDhH]\s*[0-9a-fA-FxXzZ_?]+)
  | (?P<id>[A-Za-z_$][\w$]*)
  | (?P<num>\d+)
  | (?P<str>"[^"]*")
  | (?P<p>[()\[\]{},;.#=:])
  | (?P<other>.)
""", re.S | re.X)


def _vtokens(text):
    out = []
    for m in _VTOK.finditer(text):
        k = m.lastgroup
        if k in ("ws", "lc", "bc", "attr"):
            continue
        v = m.group()
        if k == "esc":
            out.append(("id", v[1:]))
        elif k == "const":
            out.append(("const", re.sub(r"\s", "", v)))
        else:
            out.append((k, v))
    return out


class Inst:
    __slots__ = ("name", "cell", "pins")

    def __init__(self, name, cell):
        self.name, self.cell, self.pins = name, cell, {}

    def __repr__(self):
        return "Inst(%s:%s)" % (self.name, self.cell)


class Netlist:
    """Flat netlist. nets[name] = {'drivers': [(inst|'<port>', pin)], 'loads': [...]}.
    Pins of instances map pin -> canonical net name (or None / constant string)."""

    def __init__(self):
        self.module = None
        self.ports = {}         # name -> direction
        self.insts = {}         # name -> Inst
        self.nets = {}
        self.alias = {}         # union-find parent for assign aliases
        self.consts = set()

    def canon(self, n):
        while n in self.alias and self.alias[n] != n:
            n = self.alias[n]
        return n

    def net(self, n):
        n = self.canon(n)
        return self.nets.setdefault(n, {"drivers": [], "loads": []})

    def build(self):
        self.nets = {}
        for pn, d in self.ports.items():
            if pn in POWER_PINS:
                continue
            (self.net(pn)["drivers"] if d == "input" else self.net(pn)["loads"]).append(("<port>", pn))
        for inst in self.insts.values():
            for pin, n in list(inst.pins.items()):
                if n is None or pin in POWER_PINS:
                    continue
                if n in self.consts:
                    continue
                n = self.canon(n)
                inst.pins[pin] = n
                e = self.net(n)
                (e["drivers"] if is_output_pin(inst.cell, pin) else e["loads"]).append((inst.name, pin))

    def driver(self, n):
        e = self.nets.get(self.canon(n)) if n is not None else None
        return e["drivers"] if e else []

    def loads(self, n):
        e = self.nets.get(self.canon(n)) if n is not None else None
        return e["loads"] if e else []


def _read_netexpr(toks, i):
    """Parse a net expression starting at toks[i]. Returns (names_list, next_i)."""
    k, v = toks[i]
    if k == "p" and v == "{":
        names = []
        i += 1
        while not (toks[i][0] == "p" and toks[i][1] == "}"):
            if toks[i][1] == ",":
                i += 1
                continue
            sub, i = _read_netexpr(toks, i)
            names.extend(sub)
        return names, i + 1
    if k == "const":
        return ["#const:" + v], i + 1
    if k in ("id", "num"):
        name = v
        i += 1
        if i < len(toks) and toks[i] == ("p", "["):
            j = i + 1
            sel = ""
            while toks[j] != ("p", "]"):
                sel += toks[j][1]
                j += 1
            name += "[" + sel + "]"
            i = j + 1
        return [name], i
    raise ValueError("unexpected token in net expression: %r" % (toks[i],))


def parse_verilog(path_or_text, top=None):
    text = path_or_text
    if "\n" not in path_or_text and os.path.exists(path_or_text):
        with open(path_or_text, encoding="utf-8", errors="replace") as f:
            text = f.read()
    toks = _vtokens(text)
    mods = {}
    i = 0
    n = len(toks)
    while i < n:
        if toks[i] == ("id", "module"):
            nl = Netlist()
            nl.module = toks[i + 1][1]
            i += 2
            # skip header port list
            depth = 0
            while True:
                t = toks[i]
                if t == ("p", "("):
                    depth += 1
                elif t == ("p", ")"):
                    depth -= 1
                elif t == ("p", ";") and depth == 0:
                    i += 1
                    break
                i += 1
            while toks[i] != ("id", "endmodule"):
                k, v = toks[i]
                if k == "id" and v in ("input", "output", "inout", "wire", "reg", "tri",
                                       "supply0", "supply1", "wand", "wor"):
                    direction = v
                    i += 1
                    rng = None
                    while toks[i][1] in ("signed", "wire", "reg"):
                        i += 1
                    if toks[i] == ("p", "["):
                        j = i + 1
                        s = ""
                        while toks[j] != ("p", "]"):
                            s += toks[j][1]
                            j += 1
                        rng = s
                        i = j + 1
                    while toks[i] != ("p", ";"):
                        if toks[i][0] == "id":
                            nm = toks[i][1]
                            if direction in ("input", "output", "inout"):
                                if rng and ":" in rng:
                                    a, b = [int(x) for x in rng.split(":")]
                                    for bit in range(min(a, b), max(a, b) + 1):
                                        nl.ports["%s[%d]" % (nm, bit)] = direction
                                else:
                                    nl.ports[nm] = direction
                        i += 1
                    i += 1
                    continue
                if k == "id" and v == "assign":
                    i += 1
                    lhs, i = _read_netexpr(toks, i)
                    assert toks[i] == ("p", "="), toks[i]
                    rhs, i = _read_netexpr(toks, i + 1)
                    for a, b in zip(lhs, rhs):
                        if b.startswith("#const:"):
                            nl.consts.add(a)
                        else:
                            ra, rb = nl.canon(a), nl.canon(b)
                            if ra != rb:
                                # keep port names as canonical representatives
                                if ra in nl.ports:
                                    nl.alias[rb] = ra
                                else:
                                    nl.alias[ra] = rb
                    while toks[i] != ("p", ";"):
                        i += 1
                    i += 1
                    continue
                if k == "id":
                    # cell instance: TYPE [#(...)] NAME ( .PIN(expr), ... ) ;
                    cell = v
                    i += 1
                    if toks[i] == ("p", "#"):
                        depth = 0
                        i += 1
                        while True:
                            if toks[i] == ("p", "("):
                                depth += 1
                            elif toks[i] == ("p", ")"):
                                depth -= 1
                                if depth == 0:
                                    i += 1
                                    break
                            i += 1
                    iname = toks[i][1]
                    i += 1
                    if toks[i] == ("p", "["):   # instance array bit (unlikely)
                        j = i
                        while toks[j] != ("p", "]"):
                            j += 1
                        iname += "".join(t[1] for t in toks[i:j + 1])
                        i = j + 1
                    inst = Inst(iname, cell)
                    assert toks[i] == ("p", "("), (iname, toks[i])
                    i += 1
                    while toks[i] != ("p", ")"):
                        if toks[i] == ("p", ","):
                            i += 1
                            continue
                        assert toks[i] == ("p", "."), (iname, toks[i:i + 4])
                        pin = toks[i + 1][1]
                        assert toks[i + 2] == ("p", "("), (iname, pin)
                        i += 3
                        if toks[i] == ("p", ")"):
                            inst.pins[pin] = None
                            i += 1
                            continue
                        names, i = _read_netexpr(toks, i)
                        assert toks[i] == ("p", ")"), (iname, pin, toks[i])
                        i += 1
                        nm = names[0] if len(names) == 1 else "{" + ",".join(names) + "}"
                        if nm.startswith("#const:"):
                            nl.consts.add(nm)
                        inst.pins[pin] = nm
                    i += 1
                    assert toks[i] == ("p", ";"), (iname, toks[i])
                    i += 1
                    nl.insts[iname] = inst
                    continue
                i += 1
            mods[nl.module] = nl
        i += 1
    if not mods:
        raise ValueError("no module found")
    if top is None:
        used = {inst.cell for m in mods.values() for inst in m.insts.values()}
        tops = [m for m in mods if m not in used]
        top = tops[-1] if tops else list(mods)[-1]
    nl = mods[top]
    nl.build()
    return nl


# ----------------------------------------------------------------------------
# SDF (OpenSTA writer): generic s-expression parser + extraction.
# ----------------------------------------------------------------------------
_STOK = re.compile(r'\s+|(\()|(\))|("(?:[^"\\]|\\.)*")|((?:[^\s()"\\]|\\.)+)', re.S)


def _sexpr(text):
    stack = [[]]
    for m in _STOK.finditer(text):
        if m.group(1):
            stack.append([])
        elif m.group(2):
            top = stack.pop()
            stack[-1].append(top)
        elif m.group(3):
            stack[-1].append(m.group(3)[1:-1])
        elif m.group(4):
            stack[-1].append(m.group(4))
    return stack[0]


def sdf_unescape(s):
    return re.sub(r"\\(.)", r"\1", s)


def _split_pin(s, divider="."):
    """'u_ring\\.g_stg\\[0\\]\\.x.A2' -> ('u_ring.g_stg[0].x', 'A2'); 'ui_in[7]' -> ('', 'ui_in[7]')."""
    # last unescaped divider
    idx = -1
    i = 0
    while i < len(s):
        if s[i] == "\\":
            i += 2
            continue
        if s[i] == divider:
            idx = i
        i += 1
    if idx < 0:
        return "", sdf_unescape(s)
    return sdf_unescape(s[:idx]), sdf_unescape(s[idx + 1:])


def _triple(x):
    """['0.1:0.2:0.3'] or [] -> (min, typ, max) floats or None."""
    if isinstance(x, list):
        if not x:
            return None
        x = x[0]
    parts = x.split(":")
    if len(parts) == 1:
        v = float(parts[0])
        return (v, v, v)
    vals = [float(p) if p != "" else None for p in parts]
    # fill missing typ with mean of available
    have = [v for v in vals if v is not None]
    vals = [v if v is not None else sum(have) / len(have) for v in vals]
    return tuple(vals)


class Sdf:
    def __init__(self):
        self.header = {}
        self.celltype = {}      # inst -> celltype
        self.iopath = {}        # inst -> list of dict(i, o, cond, rise, fall)
        self.ic = {}            # (from 'inst/pin' or 'port', to) -> (rise, fall)
        self.ic_from = {}       # from -> list of to
        self.ic_to = {}         # to -> list of from
        self.checks = {}        # inst -> list of dict(type, data_edge, data_pin, clk_edge, clk_pin, value)

    @staticmethod
    def pinkey(inst, pin):
        return pin if not inst else inst + "/" + pin


def parse_sdf(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    tree = _sexpr(text)
    df = tree[0]
    assert df[0] == "DELAYFILE", "not an SDF file: %s" % path
    s = Sdf()
    divider = "."
    for item in df[1:]:
        if not isinstance(item, list):
            continue
        if item[0] == "DIVIDER":
            divider = item[1]
        if item[0] in ("SDFVERSION", "DESIGN", "VENDOR", "PROGRAM", "VERSION", "DIVIDER",
                       "TIMESCALE", "VOLTAGE", "PROCESS", "TEMPERATURE", "DATE"):
            s.header[item[0]] = " ".join(x for x in item[1:] if isinstance(x, str))
    if s.header.get("TIMESCALE", "1ns").replace(" ", "") not in ("1ns", "1.0ns"):
        raise ValueError("unsupported SDF TIMESCALE %r (tools assume 1ns)" % s.header.get("TIMESCALE"))

    def pin_of(tok):
        inst, pin = _split_pin(tok, divider)
        return Sdf.pinkey(inst, pin)

    for item in df[1:]:
        if not (isinstance(item, list) and item and item[0] == "CELL"):
            continue
        ctype, inst = None, ""
        for sub in item[1:]:
            if sub[0] == "CELLTYPE":
                ctype = sub[1]
            elif sub[0] == "INSTANCE":
                inst = sdf_unescape(sub[1]) if len(sub) > 1 else ""
        if inst:
            s.celltype[inst] = ctype
        for sub in item[1:]:
            if sub[0] == "DELAY":
                for ab in sub[1:]:
                    if ab[0] not in ("ABSOLUTE", "INCREMENT"):
                        continue
                    for d in ab[1:]:
                        _sdf_delay(s, inst, d, None, pin_of)
            elif sub[0] == "TIMINGCHECK":
                for c in sub[1:]:
                    _sdf_check(s, inst, c)
    return s


def _sdf_delay(s, inst, d, cond, pin_of):
    if d[0] == "COND":
        # (COND expr (IOPATH ...)) ; expr tokens until the nested list
        expr = " ".join(x for x in d[1:] if isinstance(x, str))
        for x in d[1:]:
            if isinstance(x, list):
                _sdf_delay(s, inst, x, expr, pin_of)
        return
    if d[0] == "IOPATH":
        ip, op = d[1], d[2]
        if isinstance(ip, list):          # (posedge CLK)
            ip = ip[0] + " " + ip[1]
        vals = [_triple(v) for v in d[3:]]
        rise = vals[0] if vals else None
        fall = vals[1] if len(vals) > 1 else rise
        s.iopath.setdefault(inst, []).append({"i": ip, "o": op, "cond": cond, "rise": rise, "fall": fall})
    elif d[0] == "INTERCONNECT":
        a, b = pin_of(d[1]), pin_of(d[2])
        vals = [_triple(v) for v in d[3:]]
        rise = vals[0] if vals else None
        fall = vals[1] if len(vals) > 1 else rise
        s.ic[(a, b)] = (rise, fall)
        s.ic_from.setdefault(a, []).append(b)
        s.ic_to.setdefault(b, []).append(a)


def _sdf_edge(x):
    """(COND expr (posedge D)) | (posedge D) | D -> (edge, pin, cond)"""
    if isinstance(x, str):
        return (None, x, None)
    if x[0] == "COND":
        cond = " ".join(y for y in x[1:] if isinstance(y, str))
        inner = [y for y in x[1:] if isinstance(y, list)][0]
        e, p, _ = _sdf_edge(inner)
        return (e, p, cond)
    if x[0] in ("posedge", "negedge"):
        return (x[0], x[1], None)
    return (None, x[0], None)


def _sdf_check(s, inst, c):
    t = c[0]
    if t in ("SETUP", "HOLD", "RECOVERY", "REMOVAL"):
        de, dp, dc = _sdf_edge(c[1])
        ce, cp, cc = _sdf_edge(c[2])
        s.checks.setdefault(inst, []).append({"type": t, "data_edge": de, "data_pin": dp,
                                              "clk_edge": ce, "clk_pin": cp, "value": _triple(c[3])})
    elif t == "SETUPHOLD":
        de, dp, dc = _sdf_edge(c[1])
        ce, cp, cc = _sdf_edge(c[2])
        s.checks.setdefault(inst, []).append({"type": "SETUP", "data_edge": de, "data_pin": dp,
                                              "clk_edge": ce, "clk_pin": cp, "value": _triple(c[3])})
        s.checks.setdefault(inst, []).append({"type": "HOLD", "data_edge": de, "data_pin": dp,
                                              "clk_edge": ce, "clk_pin": cp, "value": _triple(c[4])})


def sdf_corner_name(path):
    b = os.path.basename(path)
    m = re.search(r"__([a-z]+_[a-z]+_n?\d+C_\dv\d\d)\.sdf$", b)
    if m:
        return m.group(1)
    return os.path.basename(os.path.dirname(path)) or b


def find_files(roots, pattern):
    out = []
    for r in roots:
        if os.path.isfile(r):
            out.append(r)
        elif os.path.isdir(r):
            out.extend(glob.glob(os.path.join(r, "**", pattern), recursive=True))
    return sorted(set(os.path.normpath(p) for p in out))


# ----------------------------------------------------------------------------
# DEF
# ----------------------------------------------------------------------------
def def_unescape(s):
    return re.sub(r"\\(.)", r"\1", s)


class Def:
    def __init__(self):
        self.units = 1000
        self.die = None           # (x0, y0, x1, y1) in um
        self.comps = {}           # name -> dict(cell, status, x, y, orient) (um)
        self.pins = {}            # pin -> dict(x, y)
        self.nets = {}            # net -> list of (inst|'PIN', pin)


def parse_def(path):
    d = Def()
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    m = re.search(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)\s*;", text)
    if m:
        d.units = int(m.group(1))
    u = float(d.units)
    m = re.search(r"DIEAREA\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)", text)
    if m:
        d.die = tuple(int(v) / u for v in m.groups())

    def section(name):
        mm = re.search(r"^%s\s+\d+\s*;(.*?)^END\s+%s" % (name, name), text, re.S | re.M)
        return mm.group(1) if mm else ""

    for stmt in section("COMPONENTS").split(";"):
        stmt = stmt.strip()
        if not stmt.startswith("-"):
            continue
        toks = stmt.split()
        name, cell = def_unescape(toks[1]), toks[2]
        mm = re.search(r"\+\s+(PLACED|FIXED|COVER)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+(\w+)", stmt)
        if mm:
            d.comps[name] = {"cell": cell, "status": mm.group(1), "x": int(mm.group(2)) / u,
                             "y": int(mm.group(3)) / u, "orient": mm.group(4)}
        else:
            d.comps[name] = {"cell": cell, "status": "UNPLACED", "x": None, "y": None, "orient": None}
    for stmt in section("PINS").split(";\n"):
        stmt = stmt.strip()
        if not stmt.startswith("-"):
            continue
        toks = stmt.split()
        mm = re.search(r"\+\s+(PLACED|FIXED)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)", stmt)
        if mm:
            d.pins[def_unescape(toks[1])] = {"x": int(mm.group(2)) / u, "y": int(mm.group(3)) / u}
    for stmt in re.split(r";\s*\n", section("NETS")):
        stmt = stmt.strip()
        if not stmt.startswith("-"):
            continue
        head = stmt.split("+")[0]
        toks = head.split()
        net = def_unescape(toks[1])
        conns = re.findall(r"\(\s*(\S+)\s+(\S+)\s*\)", head)
        d.nets[net] = [(def_unescape(a), def_unescape(b)) for a, b in conns]
    return d


# ----------------------------------------------------------------------------
# LEF (cell sizes only)
# ----------------------------------------------------------------------------
# Sizes (um) of the cells BINNER hand-instantiates, from the PDK cell LEF
# gf180mcu_fd_sc_mcu7t5v0.lef (MACRO ... SIZE w BY h). Used when --lef is absent.
BUILTIN_SIZES = {
    LIB + "inv_1": (2.24, 3.92), LIB + "inv_2": (3.36, 3.92), LIB + "nand2_1": (2.80, 3.92),
    LIB + "nor2_1": (3.36, 3.92), LIB + "mux2_2": (8.40, 3.92), LIB + "dlyd_1": (19.04, 3.92),
    LIB + "dffrnq_1": (19.04, 3.92), LIB + "buf_1": (3.36, 3.92), LIB + "clkbuf_1": (3.36, 3.92),
    LIB + "antenna": (1.12, 3.92), LIB + "dlyb_1": (8.96, 3.92),
}


def parse_lef_sizes(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        t = f.read()
    return {m.group(1): (float(m.group(2)), float(m.group(3)))
            for m in re.finditer(r"MACRO\s+(\S+).*?SIZE\s+([\d.]+)\s+BY\s+([\d.]+)", t, re.S)}


# ----------------------------------------------------------------------------
# Liberty (NLDM subset)
# ----------------------------------------------------------------------------
def _lib_group_text(text, start):
    """Return text of the {...} group whose '{' is at or after start."""
    i = text.index("{", start)
    depth = 0
    j = i
    while True:
        c = text[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[i + 1:j]
        j += 1


def _lib_parse_groups(body):
    """Very small liberty group parser: returns list of (gtype, arg, attrs, children)."""
    out = []
    i = 0
    n = len(body)
    attrs = {}
    pat = _LIB_STMT
    while i < n:
        # skip comments/whitespace/line continuations
        mc = _LIB_SKIP.match(body, i)
        if mc and mc.end() > i:
            i = mc.end()
            continue
        m = pat.match(body, i)
        if not m:
            i += 1
            continue
        name, arg, tail = m.group(1), m.group(3), m.group(4)
        if tail == "{":
            inner = _lib_group_text(body, m.end() - 1)
            out.append((name, (arg or "").strip().strip('"'), None, inner))
            i = m.end() - 1 + len(inner) + 2
        elif tail.startswith(":"):
            val = m.group(6) if m.group(6) is not None else m.group(5).strip()
            attrs[name] = val
            i = m.end()
        else:   # complex attribute name(args);
            prev = attrs.get(name)
            attrs[name] = (prev if isinstance(prev, list) else []) + [arg]
            i = m.end()
    return out, attrs


_LIB_STMT = re.compile(r'\s*(\w+)\s*(\(([^)]*)\))?\s*(\{|:\s*("([^"]*)"|[^;]*)\s*;|;)', re.S)
_LIB_SKIP = re.compile(r'(?:\s|\\\n|/\*.*?\*/)+', re.S)


def _nums(s):
    return [float(x) for x in re.findall(r"-?[\d.]+(?:[eE][-+]?\d+)?", s)]


class LibTable:
    def __init__(self, i1, i2, vals):
        self.i1, self.i2 = i1, i2
        self.v = vals   # list of rows, len(i1) x len(i2)

    def __call__(self, x1, x2=None):
        def seg(ix, x):
            if len(ix) == 1:
                return 0, 0, 0.0
            k = 0
            while k < len(ix) - 2 and x > ix[k + 1]:
                k += 1
            t = (x - ix[k]) / (ix[k + 1] - ix[k])
            return k, k + 1, t          # linear extrapolation outside the table
        if not self.i2:
            a, b, t = seg(self.i1, x1)
            row = self.v[0] if len(self.v) == 1 else [r[0] for r in self.v]
            return row[a] + (row[b] - row[a]) * t
        a, b, t = seg(self.i1, x1)
        c, d, u = seg(self.i2, x2)
        v = self.v
        return ((1 - t) * (1 - u) * v[a][c] + t * (1 - u) * v[b][c] +
                (1 - t) * u * v[a][d] + t * u * v[b][d])


class LibCell:
    def __init__(self, name):
        self.name = name
        self.pin_cap = {}      # pin -> cap (pF)
        self.pin_dir = {}
        self.arcs = []         # dict(rel, pin, sense, type, when, tables{cell_rise..})


def parse_liberty_cells(path, cells):
    """Parse only the named cells from a (large) liberty file."""
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    res = {}
    for c in cells:
        m = re.search(r"\bcell\s*\(\s*\"?%s\"?\s*\)" % re.escape(c), text)
        if not m:
            continue
        body = _lib_group_text(text, m.end())
        cell = LibCell(c)
        groups, _ = _lib_parse_groups(body)
        for gtype, garg, _, ginner in groups:
            if gtype != "pin":
                continue
            pgroups, pattrs = _lib_parse_groups(ginner)
            pin = garg
            cell.pin_dir[pin] = pattrs.get("direction")
            if "capacitance" in pattrs:
                cell.pin_cap[pin] = float(pattrs["capacitance"])
            for tg, targ, _, tinner in pgroups:
                if tg != "timing":
                    continue
                tgroups, tattrs = _lib_parse_groups(tinner)
                arc = {"rel": tattrs.get("related_pin", "").strip('"'), "pin": pin,
                       "sense": tattrs.get("timing_sense"), "type": tattrs.get("timing_type", "combinational"),
                       "when": tattrs.get("when"), "tables": {}}
                for kg, karg, _, kinner in tgroups:
                    _, kattrs = _lib_parse_groups(kinner)
                    i1 = _nums(kattrs["index_1"][0]) if "index_1" in kattrs else []
                    i2 = _nums(kattrs["index_2"][0]) if "index_2" in kattrs else []
                    vals_raw = kattrs.get("values", [""])[0]
                    rows = re.findall(r'"([^"]*)"', vals_raw)
                    vals = [_nums(r) for r in rows] if rows else [_nums(vals_raw)]
                    if len(vals) == 1 and i2 and len(i1) > 1 and len(vals[0]) == len(i1) * len(i2):
                        flat = vals[0]
                        vals = [flat[k * len(i2):(k + 1) * len(i2)] for k in range(len(i1))]
                    arc["tables"][kg] = LibTable(i1, i2, vals)
                cell.arcs.append(arc)
        res[c] = cell
    return res


def lib_arc(cell, rel, pin, types=("combinational",), when=None):
    cands = [a for a in cell.arcs if a["rel"] == rel and a["pin"] == pin and a["type"] in types]
    if when is not None:
        w = [a for a in cands if a["when"] == when]
        if w:
            return w[0]
    nw = [a for a in cands if not a["when"]]
    return (nw or cands or [None])[0]


# ----------------------------------------------------------------------------
# SPEF (total net capacitance only)
# ----------------------------------------------------------------------------
def parse_spef_caps(path):
    """Return ({net: total_cap_pF}, cap_unit_scale). Uses *NAME_MAP and *D_NET totals."""
    namemap = {}
    caps = {}
    scale = 1.0
    with open(path, encoding="utf-8", errors="replace") as f:
        in_map = False
        for line in f:
            s = line.strip()
            if s.startswith("*C_UNIT"):
                parts = s.split()
                v, unit = float(parts[1]), parts[2].upper()
                scale = v * {"PF": 1.0, "FF": 1e-3, "NF": 1e3}.get(unit, 1.0)
            elif s.startswith("*NAME_MAP"):
                in_map = True
            elif in_map and s.startswith("*") and re.match(r"^\*\d+\s", s):
                k, v = s.split(None, 1)
                namemap[k] = def_unescape(v.strip())
            elif s.startswith("*D_NET"):
                in_map = False
                parts = s.split()
                nm = namemap.get(parts[1], def_unescape(parts[1]))
                caps[nm] = float(parts[2]) * scale
            elif s and not s.startswith("*") and in_map:
                pass
    return caps, scale


# ----------------------------------------------------------------------------
# Small utilities
# ----------------------------------------------------------------------------
def md_table(headers, rows):
    out = ["| " + " | ".join(str(h) for h in headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join("" if v is None else str(v) for v in r) + " |")
    return "\n".join(out)


def fmt(x, nd=3):
    if x is None:
        return "n/a"
    if isinstance(x, float):
        if math.isnan(x):
            return "n/a"
        return ("%%.%df" % nd) % x
    return str(x)
