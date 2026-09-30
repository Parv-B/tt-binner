# BINNER bring-up

One script, `binner_bringup.py`, runs the entire bring-up sequence (Stage 1
sanity through Stage 5 optional temperature logging) and writes exactly one
CSV per chip, per `docs/CSV_SCHEMA.md`. The same file runs unmodified on a
real TT demo board (RP2350 + tt-micropython-firmware v3.1.1) and against the
virtual demo board in `test/vboard/` (cocotb + Icarus Verilog simulating
`src/`). This README covers both.

If anything here disagrees with `docs/SPEC.md`, the spec wins -- file a bug.

## 1. Running on real hardware

1. Copy `bringup/binner_bringup.py` and `bringup/config.ini` onto the demo
   board's flash filesystem (or run from a PC over USB with `mpremote`,
   which doesn't require copying anything first).
2. Edit `config.ini` if needed -- in particular `tile_address` and
   `force_shuttle` (see section 3 below), and `chip_id` if you want it fixed
   rather than auto-generated.
3. Run it:
   ```
   mpremote run binner_bringup.py
   ```
   or from a REPL / another script:
   ```python
   import binner_bringup
   binner_bringup.main(chip_id="parv01")
   ```
4. Watch the log lines it prints. On success the last line is
   `bring-up complete for <chip_id> -> <path>`. Pull the CSV off flash:
   ```
   mpremote fs cp :binner_parv01.csv .
   ```

A full run (all 5 stages, default repeat counts) takes on the order of a
few minutes on real hardware, dominated by Stage 3's Fmax binary search
(8 taps x ~7 bisection steps x 3 trials x a clock switch + settle time +
10ms test window each).

### Fast path for a first bring-up

If you just want to know "does the chip talk at all" before committing to a
full run, call the stages directly instead of `main()`:
```python
import binner_bringup as bb
cfg = bb.load_config("config.ini")
hal = bb.TTBoardHAL(cfg)
hal.set_clock(10_000_000)
regs = bb.Regs(bb.SpiBitBang(hal))
ids = regs.read(bb.REG_ID0, 3)
print([hex(x) for x in ids])   # expect [0x42, 0x4e, 0x2]
```

## 2. Troubleshooting

**`ids` don't read back `[0x42, 0x4e, 0x2]` at all (all zeros, all 0xFF, or
garbage):**
- Wrong tile selected, or the tile was never `.enable()`d -- see section 3.
- SPI wiring: `ui_in[0]`=CS_N, `ui_in[1]`=SCK, `ui_in[2]`=MOSI,
  `uo_out[3]`=MISO. If you're using hardware SPI0 the mapping is
  `ui_in[0]=GPIO17 (CSn)`, `ui_in[1]=GPIO18 (SCK)`, `ui_in[2]=GPIO19 (MOSI)`,
  `uo_out[3]=GPIO36 (MISO)`.
- The tile is power-gated by the TT mux: state is lost every time it's
  deselected. `TTBoardHAL.__init__` always calls `reset_project(True)` then
  `reset_project(False)` right after selecting the tile -- if you're driving
  the board manually outside this script and skip that step, registers will
  read back stale/undefined values.
- `f_SCK` too fast: the RTL requires `f_SCK <= f_clk/8` (recommended
  `f_clk/16`). `SpiBitBang._half_period_us()` sizes itself off whatever
  `f_clk` `HAL.set_clock()` last reported as *achieved* -- if you bypass the
  HAL and drive the clock yourself, match that constraint by hand.

**`ids` are correct but every register readback in Stage 1 fails
(`readback` rows have `y=0`):** almost always a CS_N/CDC timing issue --
`ui_in`/`uo_out` are asynchronous pads, double-flopped inside the DUT before
use; if you're bypassing the HAL's bit-bang timing and going faster, back
off.

**Stage 1 `clk2_kat` fails (measured count far from `GATE/2`):** channel A
or B never selected source 20, or `CTRL.RUN` didn't get set before
`CMD.START`. `configure_and_measure()` always sets `CTRL.RUN` -- if you're
poking registers by hand, don't forget it (source ring *enables* gate on
`ctl_run`, even though source 20's `clk/2` toggles unconditionally and would
still count -- the *ring bank* selection logic still needs `run=1` for every
other source, so get in the habit).

**A ring's `SEEN_x` bit is always 0 / `flags` column has `NOSEEN`:** the
selected source never oscillated. Check you didn't select `SRCA=19` (the
delay chain) with `DTAP` pointing past the built chain, or that two
different DCH taps weren't accidentally requested on A and B simultaneously
-- **the delay-chain tap selector (`SRCA[7:5]`) is shared by both
channels**; there is no way to measure two different DCH taps
simultaneously (see "hard parts" below). `stage2_rings()`'s pairing plan
already accounts for this by always pairing a DCH item with `CLK2`, never
with another DCH item.

**Stage 3 (Fmax) never seems to find a failing frequency, even at
125MHz:** some taps may simply not be reachable within the demo board's PWM
range at your process corner -- `binner_bringup.py` records this as
`OFFSCALE_HIGH`/`OFFSCALE_LOW` in the `fmax` row's `aux` field rather than
looping forever.

**Nothing responds at all, not even ID0/ID1:** clear abort. Stage 1 prints
```
ABORT: BINNER did not respond as expected on register 0x00-0x02 ...
```
and every later stage is skipped (the CSV still has the Stage 1 rows, useful
for a post-mortem). Check power, `ena`, and that you're actually talking to
tile address matching `tt_um_parv_b_binner` and not a neighbouring project.

## 3. Shuttle / tile selection

`tt-micropython-firmware` v3.1.1 does not ship a `ttgf26d` shuttle index yet
(`tt.shuttle.find(...)` / the named attribute both currently 404 for this
shuttle). `_select_shuttle()` in `binner_bringup.py` therefore tries, in
order:

1. `config.ini`'s `force_shuttle` (a project name string, or a numeric
   shuttle index) -- set this once you know your board's real tile address
   for this shuttle, to skip the fallback probing entirely.
2. `tt.shuttle.find('binner')`.
3. `tt.shuttle.tt_um_parv_b_binner` (the `project_name` in `config.ini`).
4. `tt.shuttle[tile_address]` (`config.ini`'s `tile_address`, default `581`
   -- **this default is a placeholder from the task brief, not a verified
   real shuttle address; confirm it against the actual TTGF26d shuttle
   layout before relying on it**, and set `force_shuttle` if it's wrong).

Whichever path succeeds, the script always resets the project right
afterwards (`TTBoardHAL.reset()`), because the tile's state doesn't survive
being deselected.

## 4. Virtual demo board (`test/vboard/`)

The virtual demo board runs the exact same `binner_bringup.py` against RTL
simulation (Icarus Verilog via cocotb), with a fake `ttboard` package
(`test/vboard/fakemp/ttboard/`) standing in for the real firmware, plus fake
`machine`/`rp2` modules and a small in-place augmentation of the real
`time` module (`ticks_ms`/`sleep_ms`/... -- see
`test/vboard/fakemp/_install.py` for exactly what it does and, importantly,
what it deliberately does *not* touch).

### Why this needs cocotb's bridge/resume, and what that API actually is

`binner_bringup.py` is a synchronous, blocking script (by design -- it has
to run on MicroPython, which has no meaningful `asyncio` for this use case).
cocotb's simulation, on the other hand, only advances simulated time when an
`async` coroutine `await`s a trigger. Those two execution models don't mix
directly.

cocotb 2.x's answer is a pair of decorators that used to be documented (per
the task brief) as `cocotb.bridge` / `cocotb.resume`. **Those names do not
exist at the top level in the installed cocotb 2.1.0** (verified with
`python3 -c "import cocotb; print(hasattr(cocotb,'bridge'))"` -> `False`,
under `~/tools/venv` per `~/tools/binner_env.sh`). The real, working names
in this build are private but fully functional:
```python
from cocotb._bridge import bridge, resume
```
- `@bridge` turns a **blocking** function into a coroutine function the
  cocotb test can `await`. `test/vboard/sim_tb.py` wraps
  `binner_bringup.main()` in exactly one such function
  (`_run_bringup`) and awaits it once, from `@cocotb.test()`.
- `resume(coro_fn)` turns an `async def` that awaits cocotb triggers into an
  ordinary **blocking** function, callable from inside that bridge thread.
  Every single thing the fake `ttboard` does that touches the DUT or
  simulated time -- pin reads, pin writes, `sleep_ms`, `ticks_ms`, changing
  the clock -- is one of these (see
  `test/vboard/fakemp/ttboard/_sim_bridge.py`).

The one rule that matters for correctness: **a bridge thread must hit a
`resume`-wrapped call on every iteration of any wait loop**, or cocotb's
scheduler never gets control back and simulated time never advances -- the
thread just spins forever reading a stale/frozen DUT snapshot. This is why
`TTBoardHAL.count_edges()`'s polling loop and `Regs.poll_done()`'s polling
loop both call `hal.read_uo()` / `regs.read()` on every pass: those calls
are `resume`-wrapped in the fake board, so every iteration hands control
back to the simulator, whether or not any new time actually needs to elapse.

### Running a single chip

```bash
source ~/tools/binner_env.sh
cd test/vboard
BINNER_CHIP_ID=smoke01 BINNER_OUT_DIR=/tmp make
```
Add `PLUSARGS="+RING0_HP_FS=... +DSTG1_FS=... ..."` to inject a specific
chip's variation draw by hand (see `test/vboard/variation.py`); without it,
every ring uses `src/binner_ring.v`'s built-in nominal default
(`2.5ns + IDX*1ps` half-period), i.e. no injected variation -- fine for a
smoke test, not representative of a population.

### Running a population

```bash
source ~/tools/binner_env.sh
python3 test/vboard/run_population.py --n 20 --seed 20260929 --jobs 4
```
This draws N chips from `docs/VARIATION_MODEL.md` (seeded, reproducible),
writes `truth_<chip>.json` per chip, runs each one through its own `make`
invocation (own `SIM_BUILD` directory so parallel chips don't collide), and
collects `binner_<chip>.csv` + a `run_summary.json` with per-chip pass/fail
and timing. `--reduced` (the default) uses `binner_bringup.main(reduced=True)`
-- fewer repeats, fewer Fmax bisection steps, shorter Fmax test windows --
purely a *quantity* knob; it is the identical measurement code path as a
full run, just fewer of each measurement. Use `--full-effort` to match real
bring-up's default counts (much slower, see timings below).

### A real bug this uncovered: timeouts used to leak orphaned simulators

The first population run attempted here (`--jobs 4`, the then-default
`--timeout 1800`) reported all 8 chips as `FAIL: timeout after 1800s`, but
half of them (`sim00`-`sim03`) had actually written complete, valid,
schema-conformant CSVs with real fingerprints by the time the run finished
-- they just took longer (2400-2660s each under 4-way contention) than the
Python-side subprocess timeout allowed. `subprocess.run(cmd, timeout=...)`'s
default `kill()` only reaches the direct child (`make`); `make`'s own
grandchild (the shell it forks to run `iverilog`/`vvp`) is not in the same
kill scope and, unless something else reaps it, keeps running to completion
as an orphan. That is not just a stale-status cosmetic bug: because
`ProcessPoolExecutor` sees that worker slot as free the instant
`subprocess.run()` raises `TimeoutExpired`, it immediately starts the next
queued chip -- while the orphaned previous one is still actually running,
silently doubling real concurrent load. The other 4 chips in that same run
(`sim04`-`sim07`, the second wave) crashed outright with cocotb's own
`SimFailure` ("the simulation ended prematurely") under that extra,
invisible contention. Fixed in `test/vboard/run_population.py` by running
`make` in its own process group (`preexec_fn=os.setsid`) and, on timeout,
`os.killpg()`-ing the whole group instead of just the one PID -- a timeout
now reliably kills everything it started, so a slow job is cleanly `FAIL`
and does not steal capacity from the next one. `--timeout`'s default also
moved from 1800s to 3600s now that a timeout is trustworthy again.

### Measured runtimes (honest numbers, not projections)

See the results of the smoke test and the N=20 / N=8 population runs
committed under `data/vboard/` -- `run_summary.json` in each population
directory has the actual per-chip elapsed times from this environment
(12 cores / 7.6GB RAM, WSL2, Icarus Verilog `SIM=icarus`).

**A single reduced-effort chip run alone (no other simulation competing for
the machine): 1151.57s (~19.2 minutes) real time**, cocotb's own reported
figure (`sim_tb.test_vboard_bringup PASS ... REAL TIME (s) 1151.57`), for
1.16 *seconds* of simulated time -- a real:sim ratio over 1,000,000:1, all
overhead (see below), not RTL slowness.

**Under 4-way concurrency (`--jobs 4`), the same reduced-effort run took
roughly 2000-2660s per chip (~43-58% parallel efficiency, not the naive 4x
this machine's core count would suggest).** This was measured directly,
three times: once before the orphan-leak fix (2400-2660s/chip, N=8, and
that run's second wave crashed under the extra invisible contention the
bug caused -- see above), once after the fix (N=8: 8/8 chips OK, 2302.9-
2653.5s/chip, 4995.3s = 83.3 min total), and once at full scale (N=20:
20/20 chips OK, 2010.0-2489.6s/chip, 11232.9s = **187.2 minutes (3.12
hours)** total, both committed under `data/vboard/`). WSL2's "12 cores" do
not give 12, or even 4, truly independent Icarus/cocotb processes real
headroom on this machine -- if anything, per-chip time trended *down*
slightly deeper into the N=20 run (the later chips averaging ~2150s vs the
first wave's ~2450s), plausibly host-side caching/warmup rather than any
real improvement in raw parallel capacity. `--jobs` defaults to 4, not
higher, for exactly this reason: it is the largest concurrency actually
exercised end-to-end without the artificial (bug-caused) failures above,
not a value chosen from the nominal core count. Both `run_summary.json`
files under `data/vboard/` have the full per-chip numbers verbatim.

Analysis-pipeline sanity check on both committed populations
(`analysis/binner_analysis.py`'s `load_population()`): **0 ingestion
issues** across all 8 + 20 chips (2316 and 5800 rows respectively) -- the
bring-up script's CSV output is fully schema-conformant end to end, not
just superficially.

The dominant cost is **not** simulated-cycle count or RTL complexity -- it's
the fixed per-call overhead of the `cocotb._bridge` round trip itself (each
`resume()`-wrapped pin read/write blocks the bridge OS thread on a
`threading.Event`, schedules a Task, and waits for the cocotb scheduler to
run it: on the order of a few ms of *real* wall time per call in this
environment, regardless of how little simulated time it advances). A single
paired ring measurement issues on the order of a few hundred such calls
(SPI bit-bang: ~16-18 pin writes/reads per byte, several bytes per register
transaction, several registers per measurement, repeated for every
auto-ranging attempt); Stage 2's ~18 source pairs and Stage 4's 16 PUF pairs
each do this dozens of times over. Stage 3 (Fmax) adds a clock
reconfiguration and settle/window sleep on top of the same per-register
overhead, tap x bisection-step x trial. `--reduced` mode's smaller repeat
counts, shallower bisection, and shorter Fmax windows are a *call-count*
reduction for exactly this reason -- shortening `window_ms` alone would not
have helped much, since each trial's cost is mostly fixed per-call
overhead, not the window's simulated duration. Because a legitimately-
progressing run can otherwise go silent for many minutes at a time between
old stage-boundary-only log lines (indistinguishable from a hang from the
console alone -- this happened once during this project's own bring-up),
`binner_bringup.py` now logs one line per ring pair (stage 2), per
bisection step (stage 3), per repeat (stage 4), and per sample (stage 5),
not just per stage.

A real hardware run does not pay this cost: SPI bit-bang there is limited by
the RP2350's actual GPIO toggle rate (microseconds, not milliseconds per
call), so real bring-up is much faster than the virtual board's `--reduced`
timings suggest, and the virtual board's numbers should not be read as a
prediction of real hardware runtime -- only as this environment's own
sim-parallelism budget.

### Never block on a simulation run

Any `make`/cocotb invocation here can take from ~19 minutes (one reduced
chip, alone) to well over half an hour (under contention). Always launch it
detached/backgrounded and poll its log/output file rather than waiting on a
single foreground call -- a blocking call risks exceeding whatever is
supervising it, which can leave the actual simulator process orphaned and
unsupervised (see the timeout bug above for exactly what that looks like in
practice).

### Placeholder placement data

`docs/VARIATION_MODEL.md`'s `g_x`/`g_y` gradient term needs each ring's
tile location. `tools/place_extract.py`'s real output
(`docs/reports/<sha>/placement.csv`) doesn't exist in this repo snapshot.
`test/vboard/variation.py` checks for it at a configurable path
(`BINNER_PLACEMENT_CSV` env var, default
`docs/reports/PLACEHOLDER_SHA/placement.csv`) and falls back to a
deterministic placeholder 4x4 grid layout for the 16 INV rings plus fixed
spots for NAND/NOR/FO4/the delay chain when it's absent -- clearly logged,
nothing silently wrong. Swap in the real CSV once `place_extract.py` has run
post-route; nothing else needs to change.

## 5. Things in the RTL/spec that make bring-up genuinely hard

These are not bugs to "fix" in bring-up -- they're real properties of the
design that a naive bring-up script would get wrong, and did, in an earlier
draft of this one:

1. **The delay-chain tap selector is shared by both measurement channels.**
   `SRCA[7:5]` (`DTAP`) picks the tap for the *whole* `binner_dchain`
   instance, regardless of whether source 19 is selected on channel A or B
   (`r_dtap = r_srca[7:5]` in `src/project.v`, fed into the one
   `binner_dchain` instance). You cannot measure `DCH2` on channel A and
   `DCH5` on channel B simultaneously -- there is only one physical chain.
   `stage2_rings()`'s pairing plan handles this by construction (every DCH
   item is always the channel-A half of its pair, paired with `CLK2`), but
   it's easy to write a "measure everything in consecutive pairs" loop that
   silently produces channel-B DTAP nonsense otherwise.

2. **`SRCB[7:5]` is *not* a second DTAP -- it's the debug-byte selector
   (`DBG`).** The two source registers look symmetric (`[4:0]` source,
   `[7:5]` something) but the top 3 bits mean completely different things
   on SRCA vs SRCB. Writing what you assume is "channel B's tap" actually
   changes what `uio_out`/the `MISC` debug mux shows.

3. **`docs/VARIATION_MODEL.md`'s structure table still says FO4 has 25
   stages; `src/binner_ring.v` uses `localparam N_FO4 = 13`.** SPEC.md is
   explicit that RTL wins on any disagreement, and as of the D-FO4-STAGES/
   D-DTAP-RETUNE investigation (DECISIONS.md, merged from `feat/must`),
   `docs/SPEC.md` §5's own source table has been corrected to say 13 --
   only `docs/VARIATION_MODEL.md`'s table is still stale. `test/vboard/
   variation.py` uses 13, with a comment at the point of use -- getting
   this wrong makes the injected `+RING18_HP_FS` (and therefore the
   simulated FO4 ring frequency) wrong by roughly 2x relative to what the
   ring the RTL actually built loops through.

4. **`docs/SPEC.md`'s header text says "Version register = 0x01"; the
   register map table two lines below it, and the RTL's `VER` localparam,
   both say `0x02`.** This script trusts the table/RTL (`VER_EXPECT = 0x02`)
   per the spec's own stated tie-break rule ("If this document and the RTL
   disagree, that is a bug; report it" -- but §4's table isn't disagreeing
   with the RTL, only with §1's stale prose one section up). Worth fixing
   in `docs/SPEC.md`, flagged here rather than silently worked around.

5. **The Fmax checker's arming is a *level*, not a command, and the launch
   flops/capture flops are explicitly *not* `notouch_`.** `CTRL.FMAX_EN &
   sync(ui_in[7])` (see `src/binner_fmax.v`'s header comment) means a
   glitch on `ui_in[7]` while `FMAX_EN=1` re-arms the checker; the arm-by-
   pin procedure in `stage3_fmax()` always clears `FFAIL` (`CMD.FMAX_CLEAR`)
   immediately before raising the pin, specifically so a stale sticky fail
   from an earlier frequency point can't leak into the next one.

6. **Only two rings can run at once, full stop** -- `ren[gi] = run &
   ((src_a == gi) | (src_b == gi))`. Every stage in this script measures
   in pairs for that reason; there is no way to characterise more than two
   structures per `CMD.START`.

7. **Software polling edge-counting (`count_edges()` / pin-mode Stage 1
   check) is only accurate when the polling loop runs much faster than the
   signal it's counting.** This is the documented "pure-software polling
   fallback for low rates" -- a PIO-based hardware edge counter would be
   the correct fix for anything beyond a sanity check at moderate
   `PINDIV`/gate settings; not implemented here (see
   `test/vboard/fakemp/rp2.py`'s placeholder), flagged as follow-up work.

8. **The ring-domain counters are their own capture registers**
   (`docs/binner_meas.v`'s header comment: "a separate clk-domain copy cost
   32 flops ... D-CAPTURE"), static only from `DONE` until the *next*
   `START`/`CLEAR`. Reading `CNTA`/`CNTB` after issuing a new `CMD.START`
   (even before `DONE`) can return a mid-measurement value in `FREE` mode,
   or the previous measurement's frozen value otherwise -- this script
   always writes `CMD.START` and *then* polls `STATUS.DONE` before ever
   reading a counter, never the other way around.

9. **The delay-chain ring's tap-select mux must not be changed while the
   ring is running (D-DTAP-RETUNE, DECISIONS.md, merged from `feat/must`).**
   `binner_dchain`'s tap mux is a purely asynchronous combinational tree
   inside the ring's own live feedback loop when `ring_mode=1`; switching it
   while the loop is actively oscillating is a textbook async-mux-in-a-loop
   hazard that can mode-lock the ring onto an unintended, much shorter path
   through the tree (confirmed in a `make struct` real-PDK-timing
   simulation: DTAP swept 0->1->2->3->4 live measured a spurious 9.00ns
   period at DTAP=4 instead of the expected 26.00ns; enabling directly at
   DTAP=4 from cold measured a clean 26.0ns every time). `docs/SPEC.md` §5
   now requires disabling the ring before changing DTAP. This directly
   threatened `stage2_rings()`'s DCH0->DCH1->...->DCH7 sweep (item 1 above),
   which changes `SRCA[7:5]` on every iteration of that loop while the
   previous pair's measurement may have left `CTRL.RUN=1`. Fixed in
   `configure_and_measure()` -- the single shared entry point for every
   paired measurement in stages 1/2/4 -- by unconditionally writing
   `CTRL=0` (every ring off) before writing a new `SRCA`/`SRCB`, then
   re-enabling: simpler and safer than special-casing "only when the
   previous source was also 19," at the cost of one extra cheap register
   write per measurement.

## 6. PUF fingerprint: one documented judgement call

`docs/CSV_SCHEMA.md` describes the fingerprint as a 16-bit majority-vote
word (4 hex digits, from the 16 canonical `(R_2n, R_2n+1)` / `(R_i, R_i+8)`
pairs) followed by "12 hex digits of CRC-free raw ratio sign bits from all
120 pairs, compressed (see bringup docs)" -- deferring the compression's
exact definition to this file, since no other doc defines it and C(16,2) =
120 possible ring-pair combinations is far more than the 16 pairs actually
measured by Stage 4.

Measuring all 120 combinations x 11 repeats (a >7x increase in Stage 4's
measurement count, for pairs that `docs/VARIATION_MODEL.md`'s own recovery
targets never reference) wasn't judged worth the runtime cost. Instead,
`stage4_puf()`'s `_fold_hash48()` folds every raw ratio actually measured
across all 16 canonical pairs and all repeats into a 48-bit (12 hex digit)
FNV-1a-style hash. It is still a full, deterministic function of the PUF
data collected, and stable for inter-chip comparison -- but it is not
literally "120 pairs," and the code says so at the point of definition.
Worth resolving explicitly with whoever owns the analysis pipeline before
that pipeline is built.
