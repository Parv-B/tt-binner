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

## D-UTILIZATION — 60% area target is not reachable via the prescribed cut order; flagged for owner input (2026-09-29)

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
- **N/P skew measurement precision**: population-analysis Monte-Carlo validation
  (`analysis/VALIDATION.md`) found the s_n-s_p estimator misses its documented
  ±0.01 target (actual RMSE ~=0.025, at both N=20 and N=8 — a per-die measurement-noise
  floor from having only one NAND ring and one NOR ring per die, not a population
  sampling-size problem). Decision deferred to the docs/freeze pass: most likely
  resolution is relaxing the target in `docs/VARIATION_MODEL.md` rather than reopening
  frozen RTL to add redundant N/P-sensitive structures at further area cost.
- **3 max-fanout violations present at every corner** (structural, not corner-dependent;
  `metrics.csv` does not name the net(s)). Not currently gating CI. To be identified and
  assessed once the netlist-audit/timing-report tooling can name the specific net(s).
