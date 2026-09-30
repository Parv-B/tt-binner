# BINNER per-chip CSV schema (v1)

One file per chip, written by `bringup/binner_bringup.py`. The file name is `binner_<chip_id>.csv`.
The file is tidy (long) format: one measurement per row, UTF-8, comma-separated, with a header row. The first lines are `#`-prefixed metadata comments (key=value): schema version, script version, firmware version, board, clocks, and the start time.

## Columns

| column | type | meaning |
|---|---|---|
| chip_id | str | Label given by the operator (e.g. `parv01`), or `sim07` on the virtual board |
| fingerprint | str | 16-hex-digit PUF fingerprint (Stage 4 majority vote), repeated on every row; empty until Stage 4 runs |
| run_id | str | Unique per script run: `<chip_id>-<unix time>` |
| t_s | float | Seconds since the script started (time.ticks_ms based) |
| stage | int | 1..5 |
| test | str | See the test table below |
| item | str | What was measured (ring name, tap, bit, register) |
| rep | int | Repeat index, from 0 |
| x | float | Independent variable (usually f_clk in Hz, or a gate length); empty if none |
| y | float | Result value |
| unit | str | Unit of y |
| aux | str | Raw data: counts, register bytes, flags. `;`-separated key=value |
| temp_c | float | RP2350 core temperature at the time of the row (board temperature proxy); empty if unavailable |
| flags | str | `;`-separated flags: `OVF`, `NOSEEN`, `TIMEOUT`, `SIM`, `PINMODE`, `SUSPECT` |

## Items
Rings: `R00`..`R15` (identical INV rings, sources 0-15), `NAND` (16), `NOR` (17), `FO4` (18), `DCH0`..`DCH7` (source 19 with DTAP = 0..7), `CLK2` (source 20).
Fmax taps: `T0`..`T7` (stage counts 3,4,5,6,8,10,12,14).

## Tests

| stage | test | item | x | y | unit |
|---|---|---|---|---|---|
| 1 | `id` | `ID` | – | 1 = ID0/ID1/VER correct | bool |
| 1 | `readback` | register name | – | 1 = write/read-back correct | bool |
| 1 | `lfsr_kat` | `N=<steps>` | N | 1 = signature matches model; aux `sig=0x....;exp=0x....` | bool |
| 1 | `clk2_kat` | `CLK2` | GATE | measured count; aux `exp=<GATE/2>` | count |
| 1 | `pinmode` | `R00`.. | f_clk | uo_out[1] toggle rate × 2^(PINDIV+1) (Hz), measured by MCU edge counting | Hz |
| 2 | `ring` | ring item | f_clk | ring frequency; aux `cnt=..;gate=..;ch=A|B;pair=<other item>` | Hz |
| 3 | `fmax_pt` | `T<k>` | f_clk tested (actual achieved Hz) | fraction of trials failed at x (0..1); aux `trials=..` | frac |
| 3 | `fmax` | `T<k>` | – | Fmax estimate = highest passing f from the binary search; aux `f_fail=..;f_pass=..` | Hz |
| 3 | `fmax_inv` | `T<k>` | f_clk | 1 = the tap failed with FMAX_INV=1 (polarity self-test passed) | bool |
| 4 | `puf_pair` | `R<i>-R<j>` | – | f_i/f_j − 1 from simultaneous paired counts; aux `ca=..;cb=..` | ratio |
| 4 | `puf_bit` | `b<nn>` | – | bit value (0/1) for this repeat | bit |
| 5 | `temp` | `CORE` | – | RP2350 core temperature | C |

The Stage 4 PUF bit definition is `b<nn>` for nn = 0..15, one bit per pair from the 16 fixed pairs `_puf_pairs()` defines (bringup/binner_bringup.py); bit = 1 if f_a > f_b for that pair (majority vote across all repeats). `fingerprint` is that 16-bit majority word in 4 hex digits, followed by 12 hex digits (48 bits) of a folded hash of every measured ratio across all pairs and repeats (`_fold_hash48`, bringup/binner_bringup.py) — a compact tamper-evident tail, not a second independent set of bits from 120 pairs.

## Simulation truth (virtual board only)
For every simulated chip the population runner also writes `truth_<chip_id>.json` with all injected parameters (docs/VARIATION_MODEL.md). The analysis must never read truth files except in validation mode.
