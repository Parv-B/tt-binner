#!/usr/bin/env python3
"""BINNER silicon art: author name as a dot-matrix macro on GF180MCU Metal4.

Writes macros/binner_art.{gds,lef,svg}, following the Tiny Tapeout silicon-art
guide (https://tinytapeout.com/guides/creating-silicon-art/), which covers only
IHP and SKY130. GF180MCU specifics used here, from the PDK tech LEF
(gf180mcu_fd_sc_mcu7t5v0__nom.tlef) and the GF180MCU layer table:

  Metal4   GDS 46/0   min width 0.28 um (Mn.1), min spacing 0.28 um (Mn.2a),
                      min area 0.1444 um^2 (Mn.3)
  PR_bndry GDS 0/0    placement boundary (macro footprint)

Each lit pixel is its own square, PIXEL um wide on a PITCH um grid, so shapes
never merge or touch at corners: the only rules that matter are width
(PIXEL >= 0.28), spacing (PITCH - PIXEL >= 0.28) and area (PIXEL^2 >= 0.1444),
and all three are checked below before anything is written.

Unlike the guide's minimal LEF, ours carries an OBS on Metal4 over the whole
footprint: here the art shares Metal4 with signal routing and PDN stripes, and
without the obstruction the router would happily route straight through it.
See DECISIONS.md D-ART.

Usage:
  python tools/make_art.py [--text "PARV/BHADRA"] [--pixel 0.5] [--pitch 0.9]
"""
import argparse
import math
import os

import gdstk

CELL_NAME = "binner_art"
ART_LAYER, ART_DATATYPE = 46, 0         # Metal4
BOUNDARY_LAYER, BOUNDARY_DATATYPE = 0, 0  # PR_bndry
LEF_ART_LAYER = "Metal4"

MIN_WIDTH, MIN_SPACE, MIN_AREA = 0.28, 0.28, 0.1444
GRID = 0.005  # manufacturing grid
# Footprint is rounded up to whole placement sites x rows (GF018hv5v_mcu_sc7,
# from the final DEF ROW statements) so the macro sits flush on the row grid;
# the art is centred in it.
SITE_W, ROW_H = 0.56, 3.92

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


def check_rules(pixel, pitch):
    errs = []
    if pixel < MIN_WIDTH:
        errs.append(f"pixel {pixel} < min width {MIN_WIDTH}")
    if pitch - pixel < MIN_SPACE:
        errs.append(f"gap {pitch - pixel:.3f} < min spacing {MIN_SPACE}")
    if pixel * pixel < MIN_AREA:
        errs.append(f"pixel area {pixel * pixel:.4f} < min area {MIN_AREA}")
    for v in (pixel, pitch):
        if abs(v / GRID - round(v / GRID)) > 1e-9:
            errs.append(f"{v} is off the {GRID} um grid")
    if errs:
        raise SystemExit("DRC: " + "; ".join(errs))


def pixels(lines):
    """Yield (col, row) of lit pixels, row 0 at the bottom, lines centred."""
    width = max(len(l) for l in lines) * ADVANCE_X - 1
    for li, line in enumerate(lines):
        x0 = (width - (len(line) * ADVANCE_X - 1)) // 2
        y0 = (len(lines) - 1 - li) * ADVANCE_Y
        for ci, ch in enumerate(line):
            glyph = FONT.get(ch.upper())
            if glyph is None:
                raise SystemExit(f"no glyph for {ch!r}; add it to FONT")
            for gr, row in enumerate(glyph):
                for gc, bit in enumerate(row):
                    if bit == "#":
                        yield x0 + ci * ADVANCE_X + gc, y0 + GLYPH_H - 1 - gr


def write_lef(path, w, h):
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
        f.write("   OBS\n")
        f.write(f"      LAYER {LEF_ART_LAYER} ;\n")
        f.write(f"         RECT 0.000 0.000 {w:.3f} {h:.3f} ;\n")
        f.write("   END\n")
        f.write(f"END {CELL_NAME}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", default="PARV/BHADRA", help="'/' separates lines")
    ap.add_argument("--pixel", type=float, default=0.5, help="pixel side, um")
    ap.add_argument("--pitch", type=float, default=0.9, help="pixel pitch, um")
    ap.add_argument("--margin", type=float, default=0.5, help="min art-to-boundary, um")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "macros"))
    a = ap.parse_args()
    check_rules(a.pixel, a.pitch)

    lines = a.text.split("/")
    lit = sorted(set(pixels(lines)))
    cols = max(len(l) for l in lines) * ADVANCE_X - 1
    rows = len(lines) * ADVANCE_Y - 2
    art_w = (cols - 1) * a.pitch + a.pixel
    art_h = (rows - 1) * a.pitch + a.pixel
    w = snap(math.ceil(round((art_w + 2 * a.margin) / SITE_W, 6)) * SITE_W)
    h = snap(math.ceil(round((art_h + 2 * a.margin) / ROW_H, 6)) * ROW_H)
    ox, oy = snap((w - art_w) / 2), snap((h - art_h) / 2)

    lib = gdstk.Library(unit=1e-6, precision=1e-9)
    cell = lib.new_cell(CELL_NAME)
    cell.add(gdstk.rectangle((0, 0), (w, h), layer=BOUNDARY_LAYER, datatype=BOUNDARY_DATATYPE))
    for c, r in lit:
        x, y = snap(ox + c * a.pitch), snap(oy + r * a.pitch)
        cell.add(gdstk.rectangle((x, y), (snap(x + a.pixel), snap(y + a.pixel)),
                                 layer=ART_LAYER, datatype=ART_DATATYPE))

    os.makedirs(a.out, exist_ok=True)
    base = os.path.join(a.out, CELL_NAME)
    lib.write_gds(base + ".gds")
    cell.write_svg(base + ".svg", background="#ffffff")
    write_lef(base + ".lef", w, h)
    print(f"{CELL_NAME}: {a.text!r}, {len(lit)} pixels, {w} x {h} um "
          f"({w * h:.0f} um^2), pixel {a.pixel} / pitch {a.pitch} um -> {base}.{{gds,lef,svg}}")


if __name__ == "__main__":
    main()
