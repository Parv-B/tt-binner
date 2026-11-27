# BINNER design decisions

Every significant decision, the alternatives considered, the evidence, and the rationale.
Entries are added as decisions are made; none are edited retroactively except to correct
a factual error (noted inline if so).

## D-CLOCK-PERIOD — signoff clock relaxed from 50 MHz to 20 MHz (2026-09-29)

**Finding.** The first real hardening run of the full RTL (commit 908c9e1, all sub-jobs
green: gds/precheck/gl_test/viewer) closed timing perfectly at the tt and ff corners
(WNS/TNS = 0/0 everywhere) but had real setup violations at the ss corner only, at the
template's inherited default `CLOCK_PERIOD` of 20 ns (50 MHz):

| corner | setup WNS (ns) | setup TNS (ns) | slew violations |
|---|---|---|---|
| nom_ss_125C_3v00 | -2.193 | -32.895 | 246 |
| min_ss_125C_3v00 | -1.658 | -21.173 | 181 |
| max_ss_125C_3v00 | -2.848 | -48.290 | 317 |

(Source: `tools/metrics_summary.py` on the CI artifacts of 908c9e1; see
`docs/reports/908c9e1/metrics_summary.md`.) Hold timing was clean (0/0) at every corner
in every run — unaffected by this change either way. Antenna, DRC and LVS were all clean
(0 everywhere); the violation is purely a setup-timing/slew margin problem at the
worst-case slow-process corner, driven by the design's real logic (register file, source
mux, measurement FSM) — the netlist audit (`tools/netlist_audit.py`) confirmed the ring
oscillators, delay chain and Fmax capture flops were built exactly as designed with no
inserted buffers or resized cells, so the hand-instantiated structures are not the cause.

**Alternatives considered.**
1. **Relax `CLOCK_PERIOD`** (this decision). Zero RTL risk; a pure synthesis-target
   change. The template's own comment in `src/config.json` names this as the sanctioned
   fix for setup violations. Cost: the design's verified/promised operating clock range
   drops from "up to 50 MHz" to "up to 20 MHz" for normal (non-Fmax-sweep) operation.
2. **Pipeline the register read path** (add a cycle of latency between the address
   decode and the SPI shift register) to keep 50 MHz closure honestly. More invasive to
   already-tested RTL, more schedule/verification risk, and not obviously necessary:
   nothing in the design's actual use (SPI at `f_clk`/16, ring measurement, Fmax sweep)
   requires the control plane to run at 50 MHz. Rejected for now; revisit only if 20 MHz
   later proves insufficient for some measurement need.
3. **Accept the ss-corner violation and ship at 50 MHz anyway.** Rejected outright:
   priority #1 of this project is "guaranteed to function on silicon," and knowingly
   signing off with a -2.85 ns worst-case setup violation on real logic paths is exactly
   the kind of risk the project explicitly says to avoid ("prefer boring, proven
   solutions wherever silicon risk is involved").

**Decision.** `CLOCK_PERIOD` raised from 20 ns to 50 ns (50 MHz -> 20 MHz) in
`src/config.json`. `info.yaml` `clock_hz` updated from 10 MHz to 20 MHz to match.
`docs/SPEC.md` §2 updated to state the verified 1 Hz - 20 MHz range for normal operation,
with the Fmax sweep's much higher clock explicitly carved out (no SPI transaction happens
while clk is swept high; the Fmax capture flops are false-pathed on purpose). This is not
a MUST-block trade-away: every MUST block (LFSR self-test, SPI/register interface, ring
bank, paired counters with CDC) is still fully present and, after this change, verified
to close cleanly across all nine STA corners.

**Follow-up required.** Re-harden with this change and confirm setup WNS/TNS = 0/0 at ss
too. If a second iteration is needed, lower further before considering RTL changes.

## D-CAPTURE — ring-domain counters double as capture registers (2026-09-29, folded in from RTL v0.2)

The first hardening attempt (v0.1, commit 4673f5b) failed with OpenROAD `RSZ-3006`
("failed to insert buffer before loads for net u_ring_nand.en" — every load was
dont-touch, leaving the resizer no legal insertion point). While fixing that, a
duplicate set of clk-domain "capture registers" (CAPA/CAPB, 32 flops) was found to be
unnecessary: the synchronised handshake in `binner_meas.v` already guarantees the
ring-domain counters (`binner_rcnt.v`) are static from `DONE` until the next
`START`/`CLEAR`, so they can be read directly through the register mux instead of being
copied. Removing them, alongside collapsing the SPI module's two shift registers into
one and deriving `CMD` pulses combinationally from the write strobe instead of
registering them, cut local (yosys, pre-place-and-route) area estimate from ~42.9k to
~32.8k um^2. Register map bumped to v0.2 (`docs/SPEC.md` §4).

## D-FO4-STAGES — FO4 characterization ring shortened to 13 stages (2026-09-29)

The FO4 (fan-out-4-loaded) characterization ring was specified at 25 stages like the
other rings, but each stage there also drives 3 dummy INV_1 loads (52 extra cells vs.
25 for a plain ring at the same length). 13 stages is still comfortably odd (required
for oscillation) and long enough to show the FO4 loading effect on frequency relative to
the plain INV ring; the extra 12 stages (and their 36 dummy loads) were not needed to
demonstrate the effect and only cost area. `N_FO4` parameter in `src/project.v`.

## D-NAND-ENABLE-BUFFER — dedicated buffer on the NAND ring's enable net (2026-09-29)

Direct cause of the RSZ-3006 failure above: the NAND ring's enable signal fanned out to
25 NAND2 stage inputs, all of them `notouch_`-protected (dont-touch), leaving OpenROAD's
resizer with a net it was required to buffer (per drive-strength/fanout rules) but
forbidden to touch anywhere along its path. Fix: a single hand-instantiated, `notouch_`
-named `BUF_1` cell was added between the raw enable and the 25 stage inputs
(`enbuf_notouch_` in `src/binner_ring.v`). This gives the flow a legal, but still
protected (and therefore audit-verified, `tools/netlist_audit.py`), point to drive the
fan-out from, without introducing a resizer-inserted buffer into a structure the audit
is supposed to prove is untouched. The NOR ring's existing `enb_notouch_` inverter
already served this role incidentally (it exists for polarity, not fan-out, but happened
to break up the enable net the same way) — the INV/PUF rings' enable is the shared
`run`/`ren[i]` gating signal that also drives the measurement-controller side and was
not the failing net.

## D-UTILIZATION — 60% target relaxed; ~82% utilization accepted (2026-09-29, resolved 2026-09-30)

**Resolved.** Owner approved relaxing the 60% target after reviewing the evidence below.
Decision: accept the current ~82% utilization as-is. No area cut applied. Rationale
(owner-confirmed): the 60% figure was set in the original brief before any real
hardening data existed, as a standard blind risk-aversion margin against an unproven
flow choking on a dense design. That risk did not materialize: real post-route data at
~82% shows 0 DRC errors, 0 antenna violations, 0 routing errors, and (after
D-CLOCK-PERIOD) 0 setup/hold timing violations at all 9 STA corners. The thing the
margin was meant to protect against empirically did not happen on this design/flow, so
enforcing the original number would mean cutting real characterization content (Fmax,
ring population) to satisfy a target chosen before the flow was proven, not to fix an
actual problem. Superseded by the analysis below (kept for the record).

**Re-checked after D-CLOCK-PERIOD** (commit 9692913, `tools/metrics_summary.py` on the
green re-harden, `docs/reports/9692913/metrics_summary.md`): utilization is **81.98%**,
essentially unchanged from the pre-fix 81.68% (908c9e1). The clock-period relaxation
fixed timing (setup WNS/TNS now 0.000 at all 9 corners) but, as hoped, did **not**
meaningfully reduce area — `timing_repair_buffer` actually grew slightly (156->162
cells).

**Where the area actually goes** (from the cell-class breakdown, stdcell area = total
placed area minus filler, 42,604 um^2 of a 51,967 um^2 core):

| category | area (um^2) | share of stdcell area |
|---|---|---|
| real logic (combinational + sequential + inverter classes) | 34,438 | 80.8% |
| CTS/buffering (clock buffers, timing-repair buffers, plain buffers) | 6,270 | 14.7% |
| structural (endcap/tap/tie cells, fixed by floorplan geometry) | 1,897 | 4.5% |

The "real logic" category is dominated by the register file, source-select muxes and
measurement FSM (MUST block #2, "Readout and control interface") — not by the ring
oscillators, delay chain or Fmax logic, which the netlist audit already confirmed are
built exactly as specified and cost comparatively little area.

**Applying the plan's full prescribed cut order does not reach the target.** Estimated
savings from doing all of the following: drop the Fmax/at-speed block entirely (~1,900
um^2), drop the FO4 characterization ring (~430 um^2), halve the 16 identical PUF rings
to the stated floor of 8 (~1,700 um^2) — about 4,050 um^2 total, or under 10% of the
overage needed. Resulting utilization would still be about **74%**, not 60%, while
having sacrificed the at-speed Fmax regression (a SHOULD block) and half the PUF/RO
population (directly hurting priority #2, "produces novel, publishable... data," and
priority #3, "maximizes relevance to... yield engineering careers" — the whole point of
having 16 rings is statistical power for the within-die/PUF analysis).

**What is NOT at risk.** Antenna, DRC and LVS are all clean (0 everywhere) at the
current 82% packing, and setup/hold timing now close with 0 WNS/TNS at every corner
(after D-CLOCK-PERIOD). Nothing measured so far ties this utilization number to an
actual silicon-functionality risk (priority #1) — 60% was this project's own
self-imposed design margin/aesthetic target, set before any real hardening data existed
("harden a skeleton early to get real area and flow facts before designing to
estimates" — a step this build effectively skipped by writing the full MUST-block RTL
before the first real harden, which is itself worth noting as a process lesson).

**Not unilaterally resolved.** Because reaching 60% would require cutting well past the
prescribed order into the register/control interface itself (i.e., trading away
richness in a MUST block) or degrading priorities #2/#3 for a target that is not
reachable through the sanctioned cuts anyway, this is flagged here rather than acted on.
Options for the owner to weigh:
1. Accept the current ~82% utilization (no known functional-risk evidence against it;
   DRC/antenna/LVS/timing all clean) and treat 60% as a missed aspirational target,
   documented honestly in the final report.
2. Apply the full prescribed cut order anyway for whatever partial margin it buys
   (~74%), accepting the loss of Fmax and half the PUF population.
3. Accept a smaller, targeted cut (e.g. Fmax taps only, ~1,900 um^2) as a good-faith
   partial application of the order without touching the ring population, landing
   around 78-79%.
Recommendation if a decision is needed before the owner weighs in: option 3, since it
uses the part of the prescribed order least damaging to priorities #2/#3 while still
showing area discipline; but no cut is being applied automatically pending input, since
options 1-3 meaningfully change what silicon ships and what data it can produce.
- **N/P skew measurement precision — RESOLVED (2026-09-30, red-team pass).**
  population-analysis Monte-Carlo validation (`analysis/VALIDATION.md`) found the
  s_n-s_p estimator misses its originally-documented ±0.01 target (actual RMSE
  ~=0.025, at both N=20 and N=8 — a per-die measurement-noise floor from having only
  one NAND ring and one NOR ring per die, not a population sampling-size problem, so
  no amount of additional chips would fix it). Resolved by relaxing the target in
  `docs/VARIATION_MODEL.md` to ±0.025 rather than reopening frozen RTL to add
  redundant N/P-sensitive structures at further area cost (which is now moot anyway
  given D-UTILIZATION's resolution above).
- **3 max-fanout violations present at every corner** (structural, not corner-dependent;
  `metrics.csv` does not name the net(s)). Not currently gating CI. To be identified and
  assessed once the netlist-audit/timing-report tooling can name the specific net(s).

## D-STRUCT-NAND-ARTIFACT — `make struct` NAND-ring anomaly traced to an Icarus `-gspecify` simulation artifact, not a design defect (2026-09-30)

**Finding reported.** The verification engineer's `make struct` target (real GF180MCU PDK
cell models, real specify-block timing, no behavioural shortcut — see
`test/COVERAGE.md` item 9) measured the NAND characterization ring (source 16) at a
2.00 ns period instead of the expected 50.00 ns (25 stages x 2 x 1.0 ns arc), with all 25
`ring_notouch_` stage outputs toggling in perfect lockstep every 1 ns — i.e. behaving as
one stage, not a 25-stage traveling wave. The otherwise-identical INV ring (source 0/1,
same stage count, same cell library, only stage 0 gated by `en` instead of all 25) measured
correctly (50.00 ns) in the same run. The reported repro was deterministic.

**Why this mattered enough to investigate personally, not just log.** The NAND ring is a
MUST-block characterization structure whose entire purpose is the NAND/INV frequency
ratio (N/P-skew signature, a headline "novel, publishable" deliverable). A genuine 25x
oscillation-mode defect would be a real silicon-functionality risk (priority #1) and
would invalidate that data (priority #2).

**Investigation.** Independently reproduced with a standalone diagnostic testbench
(force-based, bypassing cocotb/SPI) against the same PDK models:
1. An isolated 3-cell probe (`buf_1`, `inv_1`, `nand2_1` alone, no ring, no clock) showed
   that **with `-gspecify`**, none of these cells ever resolve their output from `X`, even
   given a stable known-0 input held for 10 ns and then an explicit 0->1->0 transition.
   **Without `-gspecify`**, the identical probe resolves correctly and instantly
   (`y_inv=1`, `y_nand=1` etc., as expected). This isolates the X-stuck behaviour to
   Icarus's `-gspecify` path-delay engine interacting with these cells' `_func`
   submodules (confirmed by reading the PDK source directly: `inv_func` is a plain
   built-in `not` gate -- `not MGM_BG_0(ZN, I);` -- with no dependency on power pins or
   anything else that should block X-resolution under normal 4-value simulation rules).
2. A second probe, using the full design (not isolated cells) and the exact same simple
   force-based enable sequence for **both** source 0 (INV, known-good per the reported
   test) and source 16 (NAND, reported broken): **both** got stuck at permanent `X`,
   never producing any edge at all. This proves the X-stuck failure mode is not specific
   to the NAND ring's topology -- a simplified enable sequence gets the *already-confirmed-
   working* INV ring stuck too. Icarus's `-gspecify` value propagation here is evidently
   sensitive to the exact history of prior signal transitions (plausibly some internal
   notifier/IO-path-enable state that the real cocotb test's much longer SPI-bit-banged
   enable sequence happens to satisfy for the INV ring's specific structure/timing but
   apparently does not correctly satisfy for the NAND ring's, producing a defined but
   wrong answer instead of X). This is a known category of Icarus specify-mode
   limitation, not a documented, precise root cause here.
3. **Independent cross-check via real post-route SDF** (`tools/sdf_predict.py`, computed
   from actual OpenROAD/OpenSTA delay calculation on the hardened layout -- a
   fundamentally different mechanism with no dynamic-simulation X-propagation/notifier
   machinery to glitch): the NAND ring's predicted frequency is well-behaved and
   physically sensible at every corner, e.g. at nom_tt: INV rings ~4.1-4.3 GHz, NAND ring
   6.5 GHz (i.e. NAND/INV ratio 0.65-0.69 at max_ff, consistently well below 1 everywhere
   -- the NAND ring is *slower* than the INV ring, exactly as expected since a NAND2 gate's
   intrinsic delay exceeds an INV1's). There is no trace of a 25x-too-fast or lockstep
   signature anywhere in the SDF-based prediction. SDF-based static delay calculation is
   structurally incapable of producing a "dynamic lockstep artifact" the way an event-
   driven gate-level simulator with fragile X-resolution can -- it just sums real timing
   arcs around the loop.

**Conclusion.** The `make struct` finding is best explained as an Icarus `-gspecify`
simulation artifact specific to this crude, uniform-1.0ns-per-arc placeholder PDK timing
model (confirmed non-representative of real silicon timing; see
`test/COVERAGE.md` item 9 and `tools/sdf_predict.py`'s own header), not a real defect in
the NAND ring's netlist or its expected silicon behaviour. The real post-route SDF --
the best pre-silicon timing evidence this project has for actual device delays -- shows
the ring behaving exactly as designed.

**Residual, appropriately downgraded risk.** SDF-based static analysis assumes steady-
state oscillation and cannot model transient startup behaviour at enable time, so it
does not, by itself, disprove a genuine *transient* synchronized-lockstep start-up mode
(my original hypothesis before finding the simpler X-stuck explanation above). On real
silicon this remains extremely unlikely: ring oscillators with N nominally-identical
stages are well known (this is the entire physical basis of RO-PUFs, including this
project's own PUF rings) to have inherent device-to-device mismatch that reliably breaks
any transient synchronized-switching symmetry within the first few cycles, long before
the measurement window (many GEXP cycles) begins. No RTL change is being made on the
strength of a single crude-model Icarus simulation artifact that direct SDF cross-check
contradicts. Flagged here, not silently dismissed, so a second independent method (e.g.
a transistor-level or Verilator-based check, or direct silicon measurement once chips
arrive) can close it out definitively if anyone wants stronger confirmation later.

## D-DTAP-RETUNE -- delay-chain ring requires disabling before changing DTAP (2026-09-30)

**Finding.** The same `make struct` investigation found the delay-chain ring (source 19)
at DTAP=4 measuring a spurious 9.00 ns period instead of the expected 26.00 ns, but
*only* when reached via a live retune (DTAP 0->1->2->3->4 in sequence without disabling
the ring between changes, mirroring a plausible real characterization sweep). Enabling
directly at DTAP=4 from cold measured a clean, jitter-free 26.0 ns every time; an
isolated single live retune (3->4) also settled cleanly in isolation. The anomaly is
sensitive to the exact accumulated simulation-time phase at which the async tap-select
mux switches relative to the free-running ring.

Unlike D-STRUCT-NAND-ARTIFACT above, this is *not* contradicted by any independent
evidence, and is physically plausible regardless of simulator quirks: `binner_dchain.v`'s
tap-select mux (`tap_sel`) is a purely asynchronous combinational tree in the middle of a
live feedback loop when `ring_mode=1`. Switching it while the loop is actively
oscillating is a textbook async-mux-in-a-loop hazard (a glitch during the mux's own
settling time can, in principle, propagate around the loop and be re-latched by the very
edge it caused, mode-locking to an unintended shorter path through the tree) -- this can
happen on real silicon too, not just in simulation.

**Decision.** Treat "the ring must be disabled while changing DTAP" as a required
operational precondition, not an RTL bug to fix. `docs/SPEC.md` §5/§6 updated: DTAP must
be set (via SRCA[7:5]) *before* selecting source 19 and enabling the ring (CTRL.RUN), not
changed while it is already running; to sweep DTAP, disable (CTRL.RUN=0 or deselect),
change DTAP, then re-enable. This is a cheap, safe documentation-only fix with no RTL or
area cost, consistent with "prefer boring, proven solutions wherever silicon risk is
involved." `bringup/binner_bringup.py`'s Fmax/delay-chain-ring stages should follow this
sequence; flagged for the bring-up engineer to confirm.

## D-GLTEST-PINMODE-HANG -- CI's gl_test job hung for hours (test bugs, not a design defect) (2026-09-30)

**Symptom.** After the S3 fix (D-GLTEST-PINMODE-HANG is documented here rather than as
part of that entry because it was discovered independently, while re-verifying S3's
harden), CI's `gl_test` job ran for over 1.5 hours on two separate commits in a row
(normally a few minutes) before being manually cancelled both times. This burned real
time (CI concurrency contention from stacked pushes made it worse, and was itself
partially misdiagnosed as the cause before the real one was found) and was investigated
to a full, verified root cause rather than being written off as GitHub infrastructure
flakiness.

**Investigation.** Reproduced locally: fetched the actual post-route powered netlist from
the affected CI run's `tt_submission` artifact and ran `GATES=yes make` against it
directly in WSL with a hard timeout. Confirmed a genuine, reproducible hang (not GitHub
infra): one specific test, `test_pinmode.test_pinmode_spi_still_works`, took 111 seconds
of real time to simulate 2150 ns before failing -- a ~50,000x slowdown versus every other
test in the suite (typically millions of ns/s).

**Root cause 1 (the hang): two tests wrongly marked `@gl_safe`.**
`test_pinmode_spi_still_works` (test_pinmode.py) and `test_fmax_arming_pin`
(test_fmax.py) were both marked `@gl_safe` -- meaning "safe to run against the real
gate-level netlist" -- because neither test directly reads a ring frequency. Both call
`tb.set_pinmode(1, ...)` to test something else (SPI still working in pin-strap mode;
Fmax forced disarmed in pin-strap mode) without first forcing `ena=0`. Entering pin-strap
mode unconditionally sets `run=1` (`run = ena & (ctl_run | pinmode)` in project.v),
which enables whichever ring is pin-selected -- a REAL ring in the gate-level netlist.
Under `GATES=yes` (`-DFUNCTIONAL`, zero delay per the PDK's own model), an enabled ring
is a zero-delay combinational loop that Icarus must re-evaluate at the same simulation
timestamp forever -- this project's own `test/Makefile` comment already documents this
exact failure mode for hand-instantiated rings generally; these two tests simply
triggered it via pin-strap mode rather than directly. A third test,
`test_lfsr.test_lfsr_pinmode_steps`, also enters pin-strap mode and is correctly marked
`@gl_safe` -- it deliberately holds `ena=0`, which forces `run=0` unconditionally
regardless of `pinmode`, correctly sidestepping the hazard; verified this one is fine by
running it standalone under `GATES=yes` (fast, no hang) and by an automated scan of every
`@gl_safe` test in the suite for `set_pinmode(1, ...)` calls without a `ena=0` guard,
which found no other instances.

Fix: both tests recategorised `@rtl_only`, with the mechanism documented in their
docstrings and in `test_pinmode.py`'s module docstring (a standing warning against
marking any future pin-strap-mode test `@gl_safe` without the `ena=0` guard).

**Why this had gone undetected until now.** The verification engineer's original
`make struct`/GL-safety review was inspection-only (their own report says so explicitly):
they could not run `GATES=yes make` in their worktree at the time (`gate_level_netlist.v`
only exists once a real hardening run's artifact is copied in, which is what CI's
`gl_test` job itself does) and verified `@gl_safe` categorisation by reading decorators
and reasoning about intent, not by executing it. This is exactly the kind of gap that
only running the real thing catches. `feat/must`'s two prior "gl_test: success" results
(commits 908c9e1, 9692913, and the groundtruth/analysis/tools merge at 2e16f29) all
predate `test_pinmode.py`/`test_fmax.py` existing at all (they were added in the
tests-branch merge, commit `be8ceea`, folded into `dc0ebf4`) -- there was no prior green
`gl_test` run that this bug could have failed, so "RTL is unchanged since the last
green gl_test run" (the reasoning used to wave off the red-team review's S1 finding) was
an incomplete check: it accounted for RTL drift but not test-suite drift, and the test
suite is exactly what changed.

**Root cause 2 (a real, separate finding once the hang was fixed): a second test,
`test_meas.test_done_busy_timing`, failed cleanly (no hang) under `GATES=yes` for two
independent, subtler reasons, both now understood and fixed with no RTL change:**

1. *A benign, physically-real combinational glitch, not a design defect.* `busy_pin`
   (`uo_out[4]`) is a combinational function of the 2-bit `state` register
   (`busy = state != S_IDLE`). RTL simulation updates a multi-bit `reg` atomically (one
   delta cycle, Verilog's native `<=` semantics for a vector) so `state` never
   transiently reads an intermediate value. A real synthesized netlist implements each
   bit as an independently-clocked flip-flop; if their outputs don't settle in perfect
   lockstep (a delta-cycle-ordering artifact of the gate-level model, not a timing model
   -- this happens even under nominally "zero delay"), `state` can pass through a
   transient value for a sub-cycle instant during any transition where both bits change.
   Traced exactly: the `S_CLR(2'b01) -> S_RUN(2'b10)` transition (both bits flip) can
   transiently read `2'b00`, which equals `S_IDLE` -- making `busy_pin` glitch low for an
   instant, right at that transition, confirmed to happen exactly at the expected cycle
   (2, matching "second CLR cycle" in the RTL). The test used a continuously-armed
   `FallingEdge(busy_pin)` VPI callback to time when BUSY falls, which caught this
   transient glitch as if it were the real event -- giving a nonsensical "BUSY lasted 2.0
   cycles" result when the real measurement took ~20. The final `S_WAIT(11) -> S_IDLE(00)`
   transition (also a 2-bit change) was checked and confirmed NOT to have this hazard:
   neither `2'b01` nor `2'b10` (the two possible transients) equals `S_IDLE`, so `busy`
   cannot glitch low at the real completion point. This glitch is real, expected,
   physically-normal combinational-logic behaviour, present on real silicon too on any
   multi-bit-encoded state machine -- and completely invisible to any real downstream
   reader, since RP2350 firmware polls pins at microsecond timescales, many orders of
   magnitude slower than a sub-nanosecond gate-level glitch. Confirmed independently with
   a standalone cycle-by-cycle diagnostic (sampling busy/done only at clock edges, never
   catching transient glitches) against the same netlist: busy and done transitioned
   perfectly simultaneously, every cycle, with no anomaly.
2. *A VPI callback-ordering subtlety*, found while fixing #1: `RisingEdge(done_pin)`'s
   callback can fire in an earlier delta-cycle than when `busy_pin`'s own downstream
   combinational logic (driven off the same register update) has finished propagating,
   even though both are correct by the end of that simulation time step. Sampling
   `busy_pin` immediately after `await t_done` intermittently read a stale (pre-update)
   value. Fixed with cocotb's `ReadOnly()` trigger (the standard "nothing more will
   change this time step" synchronisation point) before the sample, and `NextTimeStep()`
   immediately after to leave the read-only region before driving any more SPI pins
   (attempting to drive a signal during `ReadOnly()` raises `RuntimeError` in cocotb
   2.1.0 -- caught immediately by re-running the RTL suite, which does not have this
   glitch but does share the same test code path).

Fix: `test_done_busy_timing` no longer races a second `FallingEdge(busy_pin)` trigger at
all. It derives `busy_cycles` from `done_pin`'s clean, glitch-free rising edge (the two
are the same event by construction: both set in the same clocked branch of
`binner_meas.v`), and confirms `busy_pin == 0` by sampling (through `ReadOnly()`), never
by racing.

**Verification.** After both fixes, the FULL suite was re-run to completion in both
modes, several times, from a clean `make clean`, with generous (150s) but bounded
timeouts (never blocking indefinitely again, per the DEV_ENVIRONMENT.md lesson from the
bring-up agent's own earlier hang investigation): RTL mode 48/48 PASS, 0 FAIL, ~50s. Gate-
level mode (`GATES=yes`, against the real post-route netlist) 34/34 non-skipped PASS,
0 FAIL, 14 correctly SKIP (every ring/pin-strap-touching test), ~97s -- no hang, on
repeated runs.

**No RTL change.** Every fix in this entry is in `test/`. `src/binner_meas.v` (S3, in the
prior entry above) was the only RTL touched in this pass, and is unrelated to this
finding -- confirmed by reproducing this exact hang and both `test_meas.py` failures
against the artifact of a commit that already included S3, then re-verifying clean after
the test-only fixes with no further RTL edits.

## D-ART -- author-name silicon art as a Metal4 macro (2026-11-27, branch feat/art)

**What.** "PARV / BHADRA" in a 5x7 dot-matrix font, generated by `tools/make_art.py`
into `macros/binner_art.{gds,lef,svg}` and placed through `MACROS` in `src/config.json`
(instance `art`, lower-left (24.64, 78.4) um, 32.48 x 15.68 um = 509 um^2, about 1% of
the 346.64 x 160.72 um tile). Purely decorative: no pins, no logic.

**Why it is safe to merge only if CI says so.** The Tiny Tapeout silicon-art guide
covers IHP and SKY130, not GF180MCU, so the GF180 choices below are ours and are only
proven by a green gds + precheck + gl_test on this branch. Merge to main is conditional
on that, plus the ring/timing reports (`tools/place_extract.py`,
`tools/metrics_summary.py`) staying close to the 0cf263c baseline. Drop the branch if
it is not green by 2026-12-03 (shuttle deadline 2026-12-07).

**GF180 choices.**
- Layer Metal4 (GDS 46/0) with PR_bndry (0/0), mirroring the guide's SKY130 met4
  choice. Metal5 is not used by the tile flow and is left alone.
- Each pixel is a separate 0.5 um square on a 0.9 um pitch: width 0.5 >= 0.28 (Mn.1),
  gap 0.4 >= 0.28 (Mn.2a), area 0.25 >= 0.1444 (Mn.3). No shapes merge or touch at
  corners, so no notch/diagonal rules apply. `make_art.py` checks all three.
- The LEF carries an OBS on Metal4 over the whole footprint (the guide's LEF has
  none): Metal4 is a signal-routing and PDN layer here, so without it the router
  could short a wire to the art.
- Footprint rounded up to whole sites (0.56 um) and rows (3.92 um) and placed on the
  row grid.

**Placement.** The PDN puts 1.6 um VPWR/VGND Metal4 stripe pairs every 38.87 um
(final DEF of 0cf263c). The macro sits in the leftmost gap (x 23.78-57.75 um), so no
stripe crosses it (clearance 0.86 / 0.63 um) and `FP_PDN_VOFFSET` stays at its
default. It is at mid-height because the top edge of that gap holds four Metal4 I/O
pins (x 32.76-54.60 um) that a Metal4 obstruction would block. Every measurement
structure (16 PUF rings, NAND/NOR/FO4 rings, delay chain, Fmax flops) is at y < 47 um
or x > 240 um (`tools/place_extract.py` on 0cf263c), so the macro displaces only
control-plane logic. Re-placement will still move the rings somewhat; that is what
the report comparison above checks.

**Row-cut and PDN halos set to 0.** The first run (9090730) passed every DRC and
antenna check but failed the TT precheck pin check ("4 LEF errors"). VPWR and VGND
each had an extra short Metal4 pin at x ~7.6/10.9 um, y 62.4-110.1 um. Cause: CutRows
leaves `FP_MACRO_HORIZONTAL_HALO`/`FP_MACRO_VERTICAL_HALO` (default 10 um) around
the macro, so rows 16-25 were split and their left pieces ended at x ~14.6 um. That
is short of the first stripe pair (19.68/22.98 um), so those Metal1 rails had no
connection up. OpenROAD pdngen's channel repair (`RepairChannelStraps`: any followpin
with no connection above gets a strap) then added the straps, which the LEF writer
exported as pins. A first fix that zeroed only `PDN_*_HALO` (3ca35af) changed
nothing, which is how the row-cut halo was identified. With all four halos at 0,
the split rows end at the macro edge (24.64 um), past both stripes. The 10 um halo
also explains the art run's jump to 85.7% utilization (vs ~82%): it removed about
1900 um^2 of rows, not just the 509 um^2 macro.

**Gate-level test.** The post-route netlist instantiates `binner_art` without
defining it, so `test/Makefile` adds `test/binner_art_stub.v` (an empty module) to
the `GATES=yes` sources only. RTL builds get the same empty module from `project.v`.

## D-ART-RO -- the name art becomes a Metal4 wire load on a new ring, source 21 (2026-11-27, branch feat/art-ro)

**What.** The decorative art (D-ART, on main at 6e098f2) is redrawn as ONE connected
Metal4 shape and hung as a capacitive load on stage 12 of a new 25-stage INV ring,
source 21 (previously constant 0). The ring is cell-for-cell identical to PUF rings
0-15, so their mean is the built-in unloaded reference: `art_load = f(0-15 mean) /
f(21) - 1` is a per-die index of Metal4 capacitance against transistor drive. No
other BINNER structure measures the back end of line. VER 0x02 -> 0x03 so software
can tell the two versions apart.

**Shape** (`tools/make_art.py --mode wire`, the default on this branch): solid 0.85
um pixels (no gaps), every diagonal-only pixel contact filled in so there is no
corner-touch, each line underlined and the underlines joined by a left spine. The
result is one polygon, 204 um^2, 456 um of perimeter, in the same 32.48 x 15.68 um
footprint and location as D-ART. An independent KLayout check (`klayout.db` width,
space, notch and area at 0.28 um / 0.1444 um^2) is clean. Pin `A` (Metal4, 46/0 +
46/10 label, like the tile's own pins) is at the bottom-left corner. The LEF
obstructs Metal4 and Metal3 over the footprint except a 0.5 um window around the
pin, so the load's surroundings are fixed rather than left to the router.

**Why one pin, not two.** Two pins joined inside the macro (signal routed through
the name) would also give an open-circuit check. But the layout would then show A
and B shorted inside the macro while the netlist has two nets, an LVS risk with no
fix inside this deadline. A one-pin stub keeps LVS trivial and still gives the
capacitance measurement, which is the useful part.

**Load estimate, 19.0 fF** (in `macros/binner_art.lib`, so STA and the SDF see it):
C = 0.009 fF/um^2 x area + 0.0377 fF/um x perimeter. LibreLane's Metal4 RC
(7.756e-5 pF/um at 0.28 um, `dumprcvalues`) is the tech-LEF CPERSQDIST times the
minimum width, i.e. fringe folded into area, so it would badly overestimate a wide
shape. The split assumes about 4 um of oxide under Metal4. Treat the value as
+/-50%; silicon measures the real one. Against an INV_1 input of 4.6 fF (tt
liberty), stage 12 drives about 5x its normal load, so the ring should run on the
order of 10% slower than the PUF rings. That is far above count resolution.

**Integration.** `binner_ring` KIND 4 (= INV ring + `ld` port); RSZ_DONT_TOUCH_RX
covers the load net (`art_ld_notouch_`), so it is never buffered. The
IGNORE_DISCONNECTED_* waivers from D-ART are removed now that the macro is
connected, so a lost connection fails the flow instead of passing silently. Tests:
DEAD_SRCS is now 22..31; the ring-enable probes and the functional
oscillation test cover source 21. Pin-strap mode already reaches it (bank 1,
s = 5). Bring-up measures item `ART` (paired with FO4); the analysis accepts it
and reports `f_art`/`art_load` per chip. Tools: `pvlib` KIND 4, and
`netlist_audit` treats it like an INV ring.

**Local verification before CI.** RTL regression 48/48 PASS; analysis tests 42/42;
netlist-audit self-test PASS; Verilator lint has no new warnings; Yosys keeps
`art.A` on the stage-12 net (one driver; loads: stage 13 and the macro).

**Merge rule.** gds + precheck (incl. LVS and antenna) + gl_test green, the art
ring's SDF-predicted period ~5-20% above the PUF mean (sanity check on the 19 fF
model), and the other rings near the 6e098f2 baseline. Drop the branch if it is not
green by 2026-12-03; main keeps the decorative art either way.

**CI result, 092e95b: fully green.** gds, precheck, gl_test, viewer, docs and test
all pass. LVS: 0 errors, 0 device or net differences. Antenna: 0 violating nets.
Routing DRC: 0. The first try (3d8e75e) stopped at CheckMacroInstances because
`binner_art.lib` lacked the threshold attributes OpenSTA requires; they are now
copied from the PDK liberty.

- **The load is the name plus its feed.** The placer put the art ring about 200
  um from the art. Net `u_ring_art.ring_notouch_[12]` (stage 12 ZN -> stage 13 I
  and art A) carries 252.6 um of route: 206 um Metal3, 22 um Metal2, 24 um Metal4.
  At 0.0776 fF/um that is about 20 fF, comparable to the art's own ~19 fF. So
  `art_load` is a back-end wire-capacitance index (roughly half the Metal4 name,
  half Metal3 feed), not a pure Metal4 one. The route is the same on every die,
  so die-to-die variation in `art_load` is still a real back-end signal. The
  docs and comments say so.
- **SDF prediction:** the art ring is 1.181x the PUF-ring mean period at
  nom_tt (ss 1.173, ff 1.186), i.e. +17-19%, inside the 5-20% sanity window.
- **Other rings vs 6e098f2** (nom_tt): NAND +0.2%, NOR -7.1%, FO4 +0.8%, PUF
  mean +0.6%, PUF spread 17.0% -> 20.9%. That is the same scale of re-placement
  reshuffle seen between earlier runs (18.3% -> 20.3% -> 17.0%), not a trend.
- Utilization 86.2% -> 88.9% (+35 cells). Max-slew violations 470 -> 486 and
  max-cap 1 -> 1 are the pre-existing unbuffered ring structures. Disconnected
  pins 8 -> 9: the extra one is the report line "art has no power pins". It is
  non-critical and left unwaived so the check still covers pin A.

**Feed-shortening attempt 1 (user chose to try this before merging).** The art moves
from (24.64, 78.4) to (218.96, 47.04), into the stripe gap x 218.13-252.10 um where
the art ring sat in 092e95b (centroid 249.7, 55.3). Stripe clearance is 0.83/0.66 um,
the location is on the site/row grid, and the spot is clear of the top-edge pins.
`make_art.py --pin right` (now the default) puts the spine and pin A at the
bottom-right, facing the ring bank. The shape is otherwise identical: 204.3 um^2,
456.2 um perimeter, est. 19.0 fF, KLayout-clean. `--pin left` reproduces the
092e95b art exactly. Note that in 092e95b the delay chain spread across the tile
(bbox x 4.5-272 um, vs the bottom band on main), so the comparison for this run
also covers the delay-chain/Fmax SDF predictions, not just the rings.

**Attempt 1 result, 39f98dc: fully green, and it worked.** gds, precheck, gl_test and
viewer pass; LVS 0, routing DRC 0, antenna 0 nets and 0 diodes. The art landed at
(218.96, 47.04) and the feed fell from 252.6 um to **12.3 um** (8.9 um Metal4,
2.2 um Metal3, 1.1 um Metal2; ~1 fF). The name is now ~95% of the extra load.

- **What the art does, from the SDF directly** (nom_tt): stage 12 of the art ring
  (the stage driving the art) has a 0.356 ns cell delay against a 0.147 ns median
  for the ring's other INV stages, i.e. **+0.21 ns**. That matches an INV_1 driving
  ~20 fF extra (the 19.0 fF model). In 092e95b the same stage was +0.62 ns: art
  plus the 253 um feed. Over a 25-stage ring that is ~5% of the period.
- **The PUF-mean reference has a large layout offset.** `sdf_predict` puts the art
  ring at **0.942x** the PUF-ring mean period (ss 0.945, ff 0.941). It is faster
  than the average PUF ring despite the art, because the 16 PUF rings differ by
  ~20% (sd/mean) from their own routing while the art ring now packs tightly
  beside its load. The 5-20% "sanity window" in the merge rule assumed the PUF
  mean was a clean unloaded reference. It is not, so the window is replaced by
  the per-stage check above, which the run passes. Consequence for silicon:
  `art_load` = f(0-15 mean)/f(21) - 1 = (fixed layout offset) + (art term) +
  (local mismatch). A +/-10% die-to-die change in wire capacitance moves the art
  term by only ~0.5% of period, about the size of ring-to-ring mismatch. So
  `art_load` is a population-level monitor (shuttle-mate data), weak on a
  single die. SPEC, info.md, project.v and the analysis docstring say so.
- **Others vs 6e098f2** (nom_tt): PUF mean +4.2% (7.845 -> 8.171 ns), spread 17.0%
  -> 20.1%; NAND +2.6%; NOR -4.2%; FO4 +2.1%. Delay-chain Fmax T_min per tap is
  +1.1% to +2.5% (tap 0 13.11 -> 13.44 ns, tap 7 54.52 -> 55.10 ns). Utilization
  86.2% -> 88.5%; hold WS 0.142 ns; setup WS +16.96 ns; max-slew 470 -> 508 (the
  pre-existing unbuffered ring structures). The other ring shifts are design-time
  predictions; silicon is read against each run's own SDF.
- **Decision:** merge this layout (the user's choice: shorten the feed, then merge
  the better result). 39f98dc beats 092e95b because the name, not a Metal3 feed,
  is what the art ring measures.
