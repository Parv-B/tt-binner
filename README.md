![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg) ![](../../workflows/fpga/badge.svg)

# BINNER: process monitor and speed-binning tile

An on-die process monitor for the [Tiny Tapeout](https://tinytapeout.com) **TTGF26d** shuttle
(GF180MCU, `gf180mcu_fd_sc_mcu7t5v0`, 3.3 V, one 1x1 tile). Top module: `tt_um_parv_b_binner`.

BINNER has no application function. It is built to answer the questions a process/yield
engineer asks about a fabricated die: how fast it runs, how far NMOS and PMOS drifted
relative to each other, how uniform the die is across the tile, and whether its own
transistor mismatch gives a usable physical fingerprint. All measurements are digital
(ring-oscillator counting against the chip's own clock, an at-speed delay-chain Fmax sweep,
and an LFSR self-test), and everything is reachable over SPI or a no-SPI pin-strap mode.

- **Short datasheet (TT submission):** [docs/info.md](docs/info.md)
- **Full datasheet (architecture, decisions, verification, silicon predictions):** [docs/DATASHEET.md](docs/DATASHEET.md)
- **Bit-exact register/protocol spec:** [docs/SPEC.md](docs/SPEC.md)

## What's on the tile

| Block | Contents | Source |
|---|---|---|
| Ring bank | 16 identical 25-stage INV rings (RO-PUF and variation statistics), one 25-stage NAND2 ring, one 25-stage NOR2 ring, one 13-stage FO4-loaded INV ring. Hand-instantiated and `dont_touch`-protected; a post-route netlist audit confirms they match `src/`. | `binner_ring.v` |
| Delay chain + Fmax checker | 14x `DLYD_1` chain tapped at 3, 4, 5, 6, 8, 10, 12 and 14 stages. LFSR-driven launch flop, 8 capture flops compared against a reference, sticky per-tap fail flags, polarity self-test. The chain can also be looped into a ring (source 19) as a cross-check. | `binner_dchain.v`, `binner_fmax.v` |
| Paired counters | Two 16-bit ripple counters in their own ring domains, gated for `2^GEXP` clock cycles, with 2-flop CDC in each direction and `SEEN`/`OVF`/`TIMEOUT` fault flags. | `binner_rcnt.v`, `binner_sync.v`, `binner_meas.v` |
| LFSR self-test | 16-bit maximal-length Fibonacci LFSR with de Bruijn zero insertion (period 65536). Exhaustively proven free of lock-up states. | `binner_lfsr.v` |
| Control | Mode-0 SPI slave and a 19-register file with address auto-increment, plus a pin-strap fallback that needs no SPI. | `binner_spi.v`, `project.v` |

### Pinout

| Pin | Input `ui` | Output `uo` | Bidir `uio` |
|---|---|---|---|
| 0 | SPI CS_N | LFSR_OUT | DBG0 |
| 1 | SPI SCK | CHA_DIV | DBG1 |
| 2 | SPI MOSI | CHB_DIV | DBG2 |
| 3 | PINMODE | SPI MISO | DBG3 |
| 4 | PM_SEL0 | BUSY | DBG4 |
| 5 | PM_SEL1 | FMAX_FAIL | DBG5 |
| 6 | PM_SEL2 | DONE | DBG6 |
| 7 | FMAX_RUN / PM_BANK | DBG_BIT | DBG7 |

Clock: 20 MHz nominal. The Fmax sweep varies the clock frequency on purpose.

## Status

- **Design frozen on `feat/must`.** All CI workflows (`docs`, `test`, `gds` including
  `precheck`, `gl_test` and `viewer`) pass at `45b80b8`. Check
  `python tools/ci.py status --branch feat/must` for the current HEAD.
- **Hardening is CI-only**, using the unmodified Tiny Tapeout GitHub Actions.
- **Silicon:** shuttle deadline 2026-12-07 20:00 UTC; chips expected around 2027-05.
- The tile is not yet switched over from the original Wokwi registration. The switch
  procedure and the pre-submission checklist are in [FINAL_REPORT.md](FINAL_REPORT.md) §4–6.

## Verification at a glance

| Check | Result | Details |
|---|---|---|
| RTL regression (cocotb + Icarus) | 48/48 pass | [test/COVERAGE.md](test/COVERAGE.md) |
| Gate-level regression (post-route netlist) | 34/34 pass, 14 skipped (RTL-only by design) | [test/README.md](test/README.md), `DECISIONS.md` D-GLTEST-PINMODE-HANG |
| STA, 9 corners (tt/ss/ff x min/nom/max) | Setup and hold WNS/TNS = 0 at every corner | [docs/reports/9692913/metrics_summary.md](docs/reports/9692913/metrics_summary.md) |
| DRC / LVS / antenna | 0 / clean / 0 | same |
| Netlist structural audit | PASS, 0 FAIL, 0 WARN | [docs/reports/908c9e1/netlist_audit.md](docs/reports/908c9e1/netlist_audit.md) |
| Virtual demo board populations | N=20 and N=8 end-to-end runs; 0 schema issues | [data/vboard/](data/vboard/), [bringup/README.md](bringup/README.md) |
| Statistical estimator validation | 6 of 7 targets met (per-die N/P skew is limited by measurement noise) | [analysis/VALIDATION.md](analysis/VALIDATION.md) |
| Independent red-team review | 0 blocking findings | [docs/RED_TEAM_REVIEW.md](docs/RED_TEAM_REVIEW.md) |

Utilization is ~82% (42,604 µm² of standard cells in a 51,967 µm² core). This is above the
original 60% target; the owner accepted it with evidence (`DECISIONS.md` D-UTILIZATION).
Three max-fanout violations appear at every corner and are still open but non-blocking
(see [FINAL_REPORT.md](FINAL_REPORT.md) §3, R2).

### Silicon predictions (nominal corner, from post-route SDF)

| Structure | Predicted |
|---|---|
| INV/PUF rings | ~0.144 GHz |
| NAND / NOR ring | 0.090 / 0.075 GHz (NAND/INV ≈ 0.67, NOR/INV ≈ 0.56) |
| FO4 ring | 0.106 GHz |
| Fmax, tap T0 (3 stages) to T7 (14 stages) | 77.5 MHz to 18.5 MHz |

These numbers are falsifiable: real chips will confirm or refute them. Per-corner tables and
uncertainty bands are in [docs/DATASHEET.md](docs/DATASHEET.md) §6.

## How to test a chip

Run [bringup/binner_bringup.py](bringup/binner_bringup.py) on a TT ETR demo board (RP2350).
It runs five stages: ID/register/LFSR sanity, paired ring measurements, a per-tap Fmax binary
search, a PUF fingerprint, and an optional temperature re-test. The output is one CSV per chip
in the format given by [docs/CSV_SCHEMA.md](docs/CSV_SCHEMA.md). Manual SPI and pin-strap
procedures are in [docs/info.md](docs/info.md). Troubleshooting is in
[bringup/README.md](bringup/README.md).

Other shuttle participants who want to contribute measurements should start with
[cohort/README.md](cohort/README.md).

## Running things locally

The toolchain is Icarus Verilog, cocotb, and Python 3.11. [DEV_ENVIRONMENT.md](DEV_ENVIRONMENT.md)
covers setup.

```sh
# RTL regression (same as CI test.yaml)
cd test && make clean && make
! grep -E '<(failure|error)' results.xml

# Bring-up script against the virtual demo board (one nominal chip)
cd test/vboard && BINNER_CHIP_ID=smoke01 BINNER_OUT_DIR=/tmp make

# Simulated population (slow: N=20 took ~3 h with 4 jobs)
python3 test/vboard/run_population.py --n 20 --seed 20260929 --jobs 4

# Population analysis on a directory of bring-up CSVs
python analysis/run_analysis.py data/vboard/pop20_seed20260929 --out /tmp/report \
    --truth data/vboard/pop20_seed20260929

# CI helpers: workflow status, artifact fetch, netlist audit
python tools/ci.py status --branch feat/must
python tools/ci.py fetch --sha <sha> --out ci_artifacts/<shortsha>
python tools/netlist_audit.py --ci-dir ci_artifacts/<shortsha>
```

## Repository layout

| Path | What's there |
|---|---|
| [src/](src/) | RTL (listed in `info.yaml`) |
| [test/](test/) | cocotb testbench, coverage map, and the virtual demo board (`test/vboard/`) |
| [bringup/](bringup/) | MicroPython bring-up script and its config for the ETR demo board |
| [analysis/](analysis/) | Population analysis pipeline, estimator tests, and Monte-Carlo validation |
| [tools/](tools/) | CI wrapper, netlist audit, metrics summary, SDF frequency prediction, placement extraction |
| [docs/](docs/) | Datasheets, spec, CSV schema, variation model, red-team review, per-commit hardening reports |
| [data/vboard/](data/vboard/) | Committed virtual demo board runs (N=20, N=8, smoke) with ground-truth files |
| [cohort/](cohort/) | Kit for other shuttle participants who want to contribute measurements |

## Project records

- [FINAL_REPORT.md](FINAL_REPORT.md): hand-off report with what was built or cut, unverified assumptions, ranked residual risks, and the submission procedure
- [DECISIONS.md](DECISIONS.md): every design decision, with alternatives and evidence
- [GROUND_TRUTH.md](GROUND_TRUTH.md) and [SOURCES.md](SOURCES.md): shuttle and tooling facts, each with a confidence level and source

## License

See [LICENSE](LICENSE).
