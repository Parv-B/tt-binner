# BINNER cocotb testbench

Verification for `tt_um_parv_b_binner` (Tiny Tapeout TTGF26d, GF180MCU) against
`docs/SPEC.md` v0.2. Uses [cocotb](https://docs.cocotb.org/en/stable/) +
Icarus Verilog. See `test/COVERAGE.md` for the full spec-item-to-test map,
including two known structural findings (`make struct` only — see below).

## Layout

- `binner_tb.py` — shared driver (`TB` class: clock/reset/SPI-master/
  measurement helpers), an independent Python model of the LFSR (SPEC §7),
  the register map / bit definitions (mirrors SPEC §4, not `src/`), and the
  behavioural-model frequency helpers (SPEC §8). Not a cocotb test module
  itself; every `test_*.py` imports from it.
- `test.py` — original smoke test (register readback + one clk/2 measurement).
  Runs first in every regression.
- `test_reset.py` — reset values (every register, every output pin), async
  assert / sync de-assert, reset mid-measurement, reset mid-SPI-transaction.
- `test_spi.py` — SPI slave and register file: RW/RO/unmapped behaviour,
  burst auto-increment, CS_N mid-byte/mid-burst abort, MISO idle level, no
  read side effects, SCK rate sweep.
- `test_lfsr.py` — independent model proof (period 65536, no lock-up; plain
  polynomial is primitive with one lock-up state) plus RTL known-answer tests
  driven through real gated measurements.
- `test_meas.py` — measurement controller / counters / STATUS: known-answer
  counts, BUSY/DONE timing, static-after-DONE, CLEAR, START-while-busy,
  overflow, timeout, FREE mode.
- `test_ring.py` — ring gating (`ren[gi]` hierarchical probe), oscillation
  frequency per source (behavioural model), delay-chain tap frequencies.
- `test_pinmode.py` — pin-strap mode: source select, free-running counters,
  uio stays input, SPI still works.
- `test_fmax.py` — Fmax (at-speed) checker: polarity self-test, sticky
  FFAIL/clear, arming logic, per-tap threshold sweep.
- `test_struct.py` — structural-only target (`make struct`), see below.
- `tb.v` — DUT instantiation + named single-bit output wires (so cocotb can
  wait on edges of individual `uo_out` bits under Icarus).

## How to run

### `make` — RTL regression (default; CI `test.yaml`)

```sh
cd test
make clean && make
```

Compiles `src/*.v` with `-DBINNER_BEHAV` (rings and the delay chain are
plusarg-controlled behavioural models, SPEC §8 — real timing without waiting
on real GF180MCU cell delays). Runs `test`, `test_reset`, `test_spi`,
`test_lfsr`, `test_meas`, `test_ring`, `test_pinmode`, `test_fmax` (48 tests).
~60-90s wall time. `make` returns success even on a cocotb test failure —
CI checks `test/results.xml` for `<failure>`/`<error>` elements; do the same
locally: `! grep -E '<(failure|error)' results.xml`.

### `make GATES=yes` — gate-level regression (CI `gl_test.yaml`)

```sh
cd test
cp ../runs/wokwi/results/final/verilog/gl/tt_um_parv_b_binner.v gate_level_netlist.v
make clean && make GATES=yes
```

Same test modules, against the post-route powered netlist (`-DFUNCTIONAL
-DUSE_POWER_PINS`, zero-delay). Every test is written to be GL-safe or
`@rtl_only`: `@gl_safe` tests (in `binner_tb.py`) never enable a ring (a
running ring would spin forever in a zero-delay simulation); `@rtl_only`
tests are skipped automatically (`GL` flag in `binner_tb.py`, true when
`GATES=yes` or the `GL_TEST` plusarg is present). `gate_level_netlist.v` is
not checked in — it's produced by hardening and copied in by the GDS CI job,
so this target cannot run standalone in a fresh checkout without that file.

### `make struct` — structural regression (developer-only, not run by CI)

```sh
cd test
make struct
```

Recompiles `project.v` (+ `binner_ring.v`/`binner_dchain.v`/`binner_fmax.v`)
**without** `-DBINNER_BEHAV` (hand-instantiated GF180MCU cells instead of the
behavioural stand-ins) and **without** `-DFUNCTIONAL`, against the real PDK
cell models from `$PDK_ROOT`, with Icarus's `-gspecify` so every comb/seq arc
carries its real specify-block timing (1.0/1.0 ns for every cell used here).
This is the only target that exercises BINNER's actual hand-instantiated
netlist structure (ring topology, tap-select mux tree, the NAND-ring enable
buffer added for RSZ-3006) rather than a behavioural stand-in. Requires
`$PDK_ROOT` (see `DEV_ENVIRONMENT.md`); not run in CI because it needs the
real PDK checked out. **Currently 2 of 4 tests fail** — see "Known findings"
below and `test/COVERAGE.md` §9 for the full description; these are kept
failing on purpose (real, reproducible discrepancies between the intended
and actual structural behaviour of two specific sources), not test bugs to
be papered over.

### `pytest` — pure-Python model checks (no simulator)

```sh
cd test
python3 -m pytest test_lfsr.py -v
```

Runs `test_lfsr.py::test_lfsr_model_pytest`, the standalone proof that the
independent LFSR model (SPEC §7 polynomial + de Bruijn zero insertion) has
period 65536 with no lock-up state. The same proof also runs inside the
cocotb regression (`test_lfsr_model_period`), so `make` alone already covers
it; this is a fast way to check just the model without a simulator.

### Waveforms

`make` (any target) dumps `tb.fst` (disable with `+NODUMP`, or edit `tb.v` to
use `.vcd` and run `make FST=`). View with `gtkwave tb.fst tb.gtkw` or
`surfer tb.fst`.

### Reproducibility

`BINNER_SEED` (default `20260929`) seeds `TB.rng` per test (each test's seed
is derived from the base seed + a hash of the test name, logged at the start
of every test — see `binner_tb.py::TB.__init__`). Override with
`BINNER_SEED=<int> make` to rerun with different randomised register values
while keeping results reproducible for a given seed.

## What's covered

See `test/COVERAGE.md` for the full spec-item / register-field / FSM-state to
test mapping. Summary: reset values for every register and pin, the full SPI
protocol (auto-increment, abort, no-side-effect reads, SCK rate limits),
every measurement source (0-31) including known-answer sources, counter
overflow/timeout/FREE-mode edge cases, ring gating (`en` hierarchically
probed, at-most-two-at-a-time), pin-strap mode, the Fmax checker (threshold
sweep, polarity self-test, arm/disarm), an independent from-scratch LFSR
model plus RTL known-answer cross-checks, and a GL-safe subset that runs
identically under `GATES=yes`.

## Known findings (structural mode)

`make struct` deterministically fails two tests, both pointing at real
discrepancies in the hand-instantiated netlist's *at-speed* behaviour (not
present in the behavioural/RTL model, which is why `make`/`make GATES=yes`
are clean):

1. **`test_ring_periods_all_kinds`** — source 16 (NAND ring, `KIND==1` in
   `binner_ring.v`) oscillates at 2.00 ns instead of the expected 50.00 ns.
   Direct hierarchical probing shows all 25 stages toggling in lockstep
   (one-stage behaviour) instead of a 25-stage traveling wave. The `KIND==0`
   ring (only stage 0 gated) is correct in the same run, so the defect is
   specific to gating *every* stage through the shared `en_buf_notouch_` net.
2. **`test_dchain_ring_tap_periods`** — source 19 (delay-chain ring) at
   DTAP=4 measures 9.00 ns instead of 26.00 ns, but only when DTAP is
   switched live from a previously-running tap (DTAP 0→1→2→3→4 in sequence,
   matching the test's own loop); a cold enable straight at DTAP=4, or an
   isolated 3→4 retune, both measure a clean 26.0 ns. Consistent with an
   asynchronous mode-locking hazard in the combinational tap-select mux when
   retuned at an unlucky phase relative to the free-running ring.

Full detail (including the debug methodology) is in `test/COVERAGE.md`
("RTL findings") and was reported in the verification session's final
summary. `src/` is out of scope for this test-authoring pass — these are
reported, not fixed; the two `assert`s in `test_struct.py` are intentionally
left in their failing state as the reproduction.
