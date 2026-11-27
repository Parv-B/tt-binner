#!/usr/bin/env python3
"""BINNER silicon art: author name as a GF180MCU Metal4 macro.

Writes macros/binner_art.{gds,lef,svg} (and .lib in wire mode), following the
Tiny Tapeout silicon-art guide (https://tinytapeout.com/guides/creating-silicon-art/),
which covers only IHP and SKY130. GF180MCU specifics used here, from the PDK
tech LEF (gf180mcu_fd_sc_mcu7t5v0__nom.tlef), the GF180MCU layer table and the
pin labels of a hardened BINNER tile:

  Metal4   GDS 46/0   min width 0.28 um (Mn.1), min spacing 0.28 um (Mn.2a),
                      min area 0.1444 um^2 (Mn.3)
  Metal4   GDS 46/10  pin shape and label (same as the tile's own pins)
  PR_bndry GDS 0/0    placement boundary (macro footprint)

Two modes:

  dots  Decorative. Each lit pixel is its own PIXEL um square on a PITCH um grid,
        so shapes never touch; no pins. (What main shipped first, 6e098f2.)

  wire  Functional (default). The name is ONE connected Metal4 shape: solid
        pixels (PIXEL == PITCH), every diagonal-only pixel contact filled in so
        each glyph is a single polygon with no corner-touch, each text line
        underlined, the underlines joined by a spine, and a pin "A" at the
        bottom-left corner. In BINNER it is the capacitive load on one stage of
        the art ring (source 21), so the name is a per-die Metal4 capacitance
        monitor. See DECISIONS.md D-ART-RO.

In both modes the LEF carries an OBS over the footprint (Metal4, plus Metal3 in
wire mode so the load's surroundings are fixed rather than whatever the router
puts over it), leaving a window around the pin for access.

Wire-mode capacitance estimate (for the .lib only; the silicon measures the
real value). LibreLane's Metal4 RC (dumprcvalues: 7.756e-5 pF/um for a 0.28 um
wire) is CPERSQDIST x min width, i.e. it lumps fringe into area and would
overestimate a wide shape. We split it as C = CA*area + CF*perimeter with
CA ~ 0.009 fF/um^2 (Metal4 roughly 4 um of oxide above substrate) and CF the
remainder, (0.0776 - 0.28*CA)/2 fF/um per edge. Treat it as +/-50%.

Usage:
  python tools/make_art.py [--mode wire|dots] [--text "PARV/BHADRA"]
"""
import argparse
import math
import os

import gdstk

CELL_NAME = "binner_art"
PIN_NAME = "A"
ART_LAYER, ART_DATATYPE = 46, 0          # Metal4 drawing
PIN_LAYER, PIN_DATATYPE = 46, 10         # Metal4 pin/label
BOUNDARY_LAYER, BOUNDARY_DATATYPE = 0, 0  # PR_bndry
M4_THICKNESS = 0.54                       # um, tech LEF THICKNESS

MIN_WIDTH, MIN_SPACE, MIN_AREA = 0.28, 0.28, 0.1444
GRID = 0.005  # manufacturing grid
# Footprint is rounded up to whole placement sites x rows (GF018hv5v_mcu_sc7,
# from the final DEF ROW statements) so the macro sits flush on the row grid;
# the art is centred in it.
SITE_W, ROW_H = 0.56, 3.92
# Capacitance model (fF), see module docstring.
CA = 0.009
CF = (0.0776 - 0.28 * CA) / 2
OBS_CLEAR = 0.5  # um of OBS-free clearance around the pin

# 5x7 glyphs, top row first.
FONT = {
    "A": [".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "B": ["####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."],
    "C": [".###.", "#...#", "#....", "#....", "#....", "#...#", ".###."],
    "D": ["####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."],
    "E": ["#####", "#....", "#....", "####.", "#....", "#....", "#####"],
    "F": ["#####", "#....", "#....", "####.", "#....", "#....", "#...."],
    "G": [".###.", "#...#", "#....", "#.###", "#...#", "#...#", ".####"],
    "H": ["#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "I": [".###.", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."],
    "J": ["..###", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##.."],
    "K": ["#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"],
    "L": ["#....", "#....", "#....", "#....", "#....", "#....", "#####"],
    "M": ["#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"],
    "N": ["#...#", "#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#"],
    "O": [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "P": ["####.", "#...#", "#...#", "####.", "#....", "#....", "#...."],
    "Q": [".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"],
    "R": ["####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"],
    "S": [".####", "#....", "#....", ".###.", "....#", "....#", "####."],
    "T": ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."],
    "U": ["#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "V": ["#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."],
    "W": ["#...#", "#...#", "#...#", "#.#.#", "#.#.#", "#.#.#", ".#.#."],
    "X": ["#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"],
    "Y": ["#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."],
    "Z": ["#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"],
    ".": [".....", ".....", ".....", ".....", ".....", ".....", "..#.."],
    "-": [".....", ".....", ".....", ".###.", ".....", ".....", "....."],
    " ": [".....", ".....", ".....", ".....", ".....", ".....", "....."],
}
GLYPH_W, GLYPH_H = 5, 7
ADVANCE_X, ADVANCE_Y = GLYPH_W + 1, GLYPH_H + 2  # in pixels


def snap(v):
    return round(round(v / GRID) * GRID, 3)


def check_rules(pixel, pitch, solid):
    errs = []
    if pixel < MIN_WIDTH:
        errs.append(f"pixel {pixel} < min width {MIN_WIDTH}")
    if solid:
        if abs(pitch - pixel) > 1e-9:
            errs.append("wire mode needs pixel == pitch (solid strokes)")
    elif pitch - pixel < MIN_SPACE:
        errs.append(f"gap {pitch - pixel:.3f} < min spacing {MIN_SPACE}")
    if pixel * pixel < MIN_AREA:
        errs.append(f"pixel area {pixel * pixel:.4f} < min area {MIN_AREA}")
    for v in (pixel, pitch):
        if abs(v / GRID - round(v / GRID)) > 1e-9:
            errs.append(f"{v} is off the {GRID} um grid")
    if errs:
        raise SystemExit("DRC: " + "; ".join(errs))


def glyph_pixels(lines, col0, row0):
    """Lit (col, row) of the text, row 0 at the bottom, lines centred.

    Each line occupies ADVANCE_Y rows starting at row0 + line_base; glyph rows
    start one row above the line base (the base row is the underline in wire
    mode, blank in dots mode).
    """
    width = max(len(l) for l in lines) * ADVANCE_X - 1
    for li, line in enumerate(lines):
        x0 = col0 + (width - (len(line) * ADVANCE_X - 1)) // 2
        base = row0 + (len(lines) - 1 - li) * ADVANCE_Y
        for ci, ch in enumerate(line):
            glyph = FONT.get(ch.upper())
            if glyph is None:
                raise SystemExit(f"no glyph for {ch!r}; add it to FONT")
            for gr, row in enumerate(glyph):
                for gc, bit in enumerate(row):
                    if bit == "#":
                        yield x0 + ci * ADVANCE_X + gc, base + GLYPH_H - gr


def fill_diagonals(lit):
    """Light one orthogonal neighbour of every diagonal-only contact, so solid
    pixels never meet at a single corner (a DRC notch/spacing violation)."""
    lit = set(lit)
    changed = True
    while changed:
        changed = False
        for c, r in sorted(lit):
            for dc, dr in ((1, 1), (1, -1)):
                if (c + dc, r + dr) in lit and (c + dc, r) not in lit and (c, r + dr) not in lit:
                    lit.add((c, r + dr))
                    changed = True
    return lit


def wire_pixels(lines):
    """Text + underline per line + left spine joining the underlines."""
    width = max(len(l) for l in lines) * ADVANCE_X - 1
    lit = set(glyph_pixels(lines, col0=2, row0=0))
    top_base = (len(lines) - 1) * ADVANCE_Y
    for li in range(len(lines)):
        base = li * ADVANCE_Y
        lit.update((c, base) for c in range(0, width + 2))
    lit.update((0, r) for r in range(0, top_base + 1))
    return fill_diagonals(lit), width + 2, top_base + GLYPH_H + 1


def write_lef(path, w, h, pin=None, obs_layers=("Metal4",), antenna=None):
    def rects_around(px1, py1):
        if pin is None:
            return [(0, 0, w, h)]
        cx, cy = px1 + OBS_CLEAR, py1 + OBS_CLEAR
        return [(0, cy, w, h), (cx, 0, w, cy)]

    with open(path, "w") as f:
        f.write(f"# {CELL_NAME}: generated by tools/make_art.py -- do not edit\n")
        f.write("VERSION 5.8 ;\n")
        f.write("NAMESCASESENSITIVE ON ;\n")
        f.write('DIVIDERCHAR "/" ;\n')
        f.write('BUSBITCHARS "[]" ;\n')
        f.write("UNITS\n   DATABASE MICRONS 1000 ;\nEND UNITS\n\n")
        f.write(f"MACRO {CELL_NAME}\n")
        f.write("   CLASS BLOCK ;\n")
        f.write(f"   FOREIGN {CELL_NAME} 0 0 ;\n")
        f.write("   ORIGIN 0 0 ;\n")
        f.write(f"   SIZE {w:.3f} BY {h:.3f} ;\n")
        f.write("   SYMMETRY X Y ;\n")
        if pin is not None:
            x0, y0, x1, y1 = pin
            f.write(f"   PIN {PIN_NAME}\n")
            f.write("      DIRECTION INPUT ;\n")
            f.write("      USE SIGNAL ;\n")
            if antenna:
                f.write(f"      ANTENNAPARTIALMETALAREA {antenna[0]:.3f} LAYER Metal4 ;\n")
                f.write(f"      ANTENNAPARTIALMETALSIDEAREA {antenna[1]:.3f} LAYER Metal4 ;\n")
            f.write("      PORT\n")
            f.write("         LAYER Metal4 ;\n")
            f.write(f"            RECT {x0:.3f} {y0:.3f} {x1:.3f} {y1:.3f} ;\n")
            f.write("      END\n")
            f.write(f"   END {PIN_NAME}\n")
        f.write("   OBS\n")
        for layer in obs_layers:
            f.write(f"      LAYER {layer} ;\n")
            for r in rects_around(*(pin[2:] if pin else (0, 0))):
                f.write("         RECT {:.3f} {:.3f} {:.3f} {:.3f} ;\n".format(*r))
        f.write("   END\n")
        f.write(f"END {CELL_NAME}\n")


def write_lib(path, area, cap_pf):
    with open(path, "w") as f:
        f.write(f"/* {CELL_NAME}: generated by tools/make_art.py -- do not edit.\n")
        f.write(" * Pin A capacitance is an estimate of the Metal4 art's own capacitance\n")
        f.write(" * (see make_art.py); it lets STA/SDF see the load. +/-50%. */\n")
        f.write(f"library ({CELL_NAME}) {{\n")
        f.write("  delay_model : table_lookup ;\n")
        f.write('  time_unit : "1ns" ;\n  voltage_unit : "1V" ;\n  current_unit : "1mA" ;\n')
        f.write('  pulling_resistance_unit : "1kohm" ;\n  leakage_power_unit : "1nW" ;\n')
        f.write("  capacitive_load_unit (1, pf) ;\n")
        f.write("  nom_process : 1 ;\n  nom_temperature : 25 ;\n  nom_voltage : 3.3 ;\n")
        # OpenSTA rejects a library without these; values match the PDK's
        # gf180mcu_fd_sc_mcu7t5v0 liberty.
        for edge in ("rise", "fall"):
            f.write(f"  input_threshold_pct_{edge} : 50 ;\n  output_threshold_pct_{edge} : 50 ;\n")
            f.write(f"  slew_lower_threshold_pct_{edge} : 30 ;\n"
                    f"  slew_upper_threshold_pct_{edge} : 70 ;\n")
        f.write(f"  cell ({CELL_NAME}) {{\n")
        f.write(f"    area : {area:.3f} ;\n")
        f.write("    dont_touch : true ;\n    dont_use : true ;\n")
        f.write(f"    pin ({PIN_NAME}) {{\n")
        f.write("      direction : input ;\n")
        f.write(f"      capacitance : {cap_pf:.6f} ;\n")
        f.write("    }\n  }\n}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("wire", "dots"), default="wire")
    ap.add_argument("--text", default="PARV/BHADRA", help="'/' separates lines")
    ap.add_argument("--pixel", type=float, help="pixel side, um (wire 0.85, dots 0.5)")
    ap.add_argument("--pitch", type=float, help="pixel pitch, um (wire 0.85, dots 0.9)")
    ap.add_argument("--margin", type=float, default=0.5, help="min art-to-boundary, um")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "macros"))
    a = ap.parse_args()
    wire = a.mode == "wire"
    pixel = a.pixel or (0.85 if wire else 0.5)
    pitch = a.pitch or (0.85 if wire else 0.9)
    check_rules(pixel, pitch, solid=wire)

    lines = a.text.split("/")
    if wire:
        lit, cols, rows = wire_pixels(lines)
    else:
        lit = set(glyph_pixels(lines, col0=0, row0=-1))
        cols = max(len(l) for l in lines) * ADVANCE_X - 1
        rows = len(lines) * ADVANCE_Y - 2
    art_w = (cols - 1) * pitch + pixel
    art_h = (rows - 1) * pitch + pixel
    w = snap(math.ceil(round((art_w + 2 * a.margin) / SITE_W, 6)) * SITE_W)
    h = snap(math.ceil(round((art_h + 2 * a.margin) / ROW_H, 6)) * ROW_H)
    ox, oy = snap((w - art_w) / 2), snap((h - art_h) / 2)

    rects = [gdstk.rectangle((snap(ox + c * pitch), snap(oy + r * pitch)),
                             (snap(ox + c * pitch + pixel), snap(oy + r * pitch + pixel)))
             for c, r in sorted(lit)]
    pin = None
    if wire:
        # Pin: from the spine's bottom pixel (0, 0) out to the macro corner.
        pin = (0.0, 0.0, snap(ox + pixel), snap(oy + pixel))
        rects.append(gdstk.rectangle(pin[:2], pin[2:]))
        merged = gdstk.boolean(rects, [], "or", layer=ART_LAYER, datatype=ART_DATATYPE)
        if len(merged) != 1:
            raise SystemExit(f"wire mode: art is {len(merged)} polygons, expected 1")
        diag = [(c, r) for c, r in lit for dc, dr in ((1, 1), (1, -1))
                if (c + dc, r + dr) in lit and (c + dc, r) not in lit and (c, r + dr) not in lit]
        if diag:
            raise SystemExit(f"wire mode: diagonal-only contacts left at {diag[:5]}")
        shapes = merged
    else:
        shapes = [gdstk.rectangle(r.bounding_box()[0], r.bounding_box()[1],
                                  layer=ART_LAYER, datatype=ART_DATATYPE) for r in rects]

    lib = gdstk.Library(unit=1e-6, precision=1e-9)
    cell = lib.new_cell(CELL_NAME)
    cell.add(gdstk.rectangle((0, 0), (w, h), layer=BOUNDARY_LAYER, datatype=BOUNDARY_DATATYPE))
    cell.add(*shapes)
    os.makedirs(a.out, exist_ok=True)
    base = os.path.join(a.out, CELL_NAME)

    summary = (f"{CELL_NAME} [{a.mode}]: {a.text!r}, {w} x {h} um, "
               f"pixel {pixel} / pitch {pitch} um")
    if wire:
        cell.add(gdstk.rectangle(pin[:2], pin[2:], layer=PIN_LAYER, datatype=PIN_DATATYPE))
        cell.add(gdstk.Label(PIN_NAME, ((pin[0] + pin[2]) / 2, (pin[1] + pin[3]) / 2),
                             layer=PIN_LAYER, texttype=PIN_DATATYPE))
        area = sum(p.area() for p in shapes)
        perim = sum(p.perimeter() for p in shapes)
        cap_ff = CA * area + CF * perim
        write_lef(base + ".lef", w, h, pin=pin, obs_layers=("Metal4", "Metal3"),
                  antenna=(area, perim * M4_THICKNESS))
        write_lib(base + ".lib", w * h, cap_ff / 1000)
        summary += (f", Metal4 area {area:.1f} um^2, perimeter {perim:.1f} um, "
                    f"est. C = {cap_ff:.1f} fF")
    else:
        write_lef(base + ".lef", w, h)
        for stale in (base + ".lib",):
            if os.path.exists(stale):
                os.remove(stale)
        summary += f", {len(shapes)} pixels"
    lib.write_gds(base + ".gds")
    cell.write_svg(base + ".svg", background="#ffffff")
    print(summary)


if __name__ == "__main__":
    main()
