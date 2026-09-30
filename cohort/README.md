# BINNER cohort kit -- for everyone else on this shuttle

You're getting this because you have (or will have) a chip from the same
TTGF26d shuttle run as **BINNER** (`Parv-B/tt-binner`). Every Tiny Tapeout
chip on a shuttle carries *every* project submitted to it, tiled together on
one die -- so your chip physically contains this design too, whether or not
you ever planned to use it. This page is a from-scratch guide for running it,
aimed at "I have a Tiny Tapeout demo board and fifteen minutes," not at
anyone who has read the rest of this repository.

## Why this matters (and why your data is worth sending back)

BINNER measures how *your specific, physical die* behaves: ring-oscillator
frequencies, an NMOS-vs-PMOS speed skew signature, an at-speed Fmax sweep,
and a physically-unclonable-function (PUF) fingerprint derived from
transistor mismatch. None of that is simulated or estimated -- it only
exists once real chips exist. One chip's data is a data point; twenty
chips' data (this shuttle's real, physical process spread) is a
publishable characterization of an entire wafer run. If you run the
15-minute script below and send back the one CSV file it produces, you're
directly contributing to that -- there's no other way to get this data
short of everyone with a chip doing exactly this.

## What you need

- A **Tiny Tapeout ETR demo board** (the one with an RP2350 controller and a
  socket/carrier for the shuttle ASIC). If you don't have one yet, see
  [tinytapeout.com's demo board guide](https://tinytapeout.com/guides/get-started-demoboard-etr/).
- Your chip mounted on/connected to that board, powered on.
- A computer with USB, Python, and [`mpremote`](https://docs.micropython.org/en/latest/reference/mpremote.html)
  installed (`pip install mpremote`).
- This repository (`Parv-B/tt-binner`) cloned or downloaded -- you only need
  the `bringup/` folder.

## Step 1: get the two files onto the board

Copy `bringup/binner_bringup.py` and `bringup/config.ini` onto the demo
board's flash filesystem, or just run directly from your PC over USB (no
copying needed):

```bash
cd tt-binner/bringup
mpremote run binner_bringup.py
```

## Step 2: select the BINNER project on the board

The demo board's firmware (`tt-micropython-firmware`) may not yet have a
built-in shuttle index for `ttgf26d` (this shuttle is still new as of
writing). If the script's very first log lines complain about not finding
the project by name, open `config.ini` and try, in order:

1. Leave it as-is first -- `binner_bringup.py` already tries several
   fallbacks automatically (by project name, then by a numeric tile
   address).
2. If that fails, set `force_shuttle` in `config.ini` to the project's exact
   name string, `tt_um_parv_b_binner`.
3. If *that* fails, you'll need the chip's actual numeric address on this
   shuttle (not yet published anywhere central as of this writing -- check
   the [Tiny Tapeout shuttle page](https://tinytapeout.com/chips/) or ask in
   the [Tiny Tapeout Discord](https://tinytapeout.com/discord) if you can't
   find it) and set `force_shuttle` to that number instead.

You do not need to know anything else about the register map or protocol --
the script handles all of it.

## Step 3: run it

```bash
mpremote run binner_bringup.py
```

or, from a REPL or your own script:

```python
import binner_bringup
binner_bringup.main(chip_id="yourname01")
```

Use something that identifies *you*, not just "chip01" -- e.g. your GitHub
handle or first name plus a number, since the owner will be collecting CSVs
from many different people.

It takes a few minutes on real hardware. You'll see progress lines as it
works through five stages (basic sanity checks, ring-frequency
measurements, an at-speed Fmax sweep, the PUF fingerprint, and an optional
temperature re-test). On success, the last line is:

```
bring-up complete for <chip_id> -> <path>
```

## Step 4: send the CSV back

Pull the file off the board:

```bash
mpremote fs cp :binner_<yourname01>.csv .
```

Then **email the CSV to the project owner: parv.bhadra@gmail.com** (subject
line "BINNER cohort data" is helpful but not required). That's it -- no
account, no upload portal, no special formatting. One file, one email.

If you're comfortable with GitHub and want to do it that way instead,
opening a PR against `Parv-B/tt-binner` adding your CSV under
`data/cohort/` works too, but email is the lower-friction default and is
completely fine.

## Troubleshooting

**The script can't find the project / immediately errors out selecting a
shuttle.** See "Step 2" above -- this is almost always the missing
shuttle-index issue, not a real fault. Try the `force_shuttle` overrides in
order.

**Nothing responds at all -- Stage 1 prints an ABORT about register
0x00-0x02 not reading back as expected.** This usually means either the
wrong project/tile is selected (double-check Step 2), the chip isn't
actually powered/seated correctly on the board, or you're pointed at a
neighboring project's tile by mistake. The CSV will still have partial
Stage 1 rows even after an abort -- send it anyway if you're stuck, it's
useful for debugging even if incomplete.

**It runs but a lot of rows look wrong (all zeros, obviously constant
values, or the `flags` column full of `NOSEEN`/`TIMEOUT`).** A few
`NOSEEN`/`OVF` flags here and there are normal and expected (the script
records them as data, not failures) -- but if *every* ring measurement is
flagged, double check you're not driving the board's clock unusually fast
or slow, and that nothing else is talking to the board's pins at the same
time. Send the CSV regardless; "this chip's data looks strange" is itself a
useful, honest result and the analysis pipeline is built to flag and
exclude bad rows automatically rather than need clean data going in.

**It's just slow / seems stuck.** A full run legitimately takes a few
minutes on real hardware (the Fmax sweep in particular does a binary search
per tap). If you genuinely see no new output for 10+ minutes, it's likely
stuck -- power-cycle the board and try again; if it happens twice, send
whatever partial CSV exists along with a note about where it stalled.

**Any other error.** Don't debug it for hours on your own -- send the
partial CSV (if any) plus a copy of whatever the script printed to
parv.bhadra@gmail.com, or open an issue on `Parv-B/tt-binner`. Partial or
odd data is still useful; silence is the only truly wasted result.

## If you want more detail

Everything above is deliberately the minimum you need. If you want to
understand what the chip is actually doing, what the register map means, or
how the measurements work, see `docs/DATASHEET.md` and `docs/SPEC.md` in
this repository -- but you don't need any of that just to run the script and
send back a CSV.
