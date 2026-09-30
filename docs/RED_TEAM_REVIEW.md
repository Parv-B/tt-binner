# BINNER red-team review

Independent adversarial review of `Parv-B/tt-binner`, branch `feat/must` @
`dc0ebf4ee3ef17311f467ab8b45bc14a76d2bdaa`. Every finding below was produced by
directly reading `src/*.v`, running the test suites myself, independently
re-deriving the LFSR math, re-running `tools/netlist_audit.py` /
`tools/metrics_summary.py` against freshly-fetched CI artifacts, and diffing
`.github/workflows/*.yaml` + `src/config.json` byte-for-byte against the live
`TinyTapeout/ttgf-verilog-template` — not by trusting the repo's own prose.

## Top-line summary

**0 blocking, 5 should-fix, 4 nice-to-have, plus a large set of
false-alarms-I-checked** (documented below for traceability, since the
instructions asked for independent verification, not just new bugs).

One important **process caveat, not a design defect**: at the time of this
review, the `feat/must` HEAD commit's own `gds` workflow run (id
`36665848962`) had `gds`, `precheck` and `viewer` jobs green but **`gl_test`
still running** (not yet complete). The task brief's premise of "latest
commit, fully green CI" was therefore not itself independently confirmed for
the true HEAD at review time — see Finding S1. Everything else in this report
(RTL reading, the 48/48 behavioural regression, `make struct`, the netlist
audit/metrics re-run) is independent of that pending job and was verified
directly.

| # | Severity | Area | One-line |
|---|---|---|---|
| S1 | should-fix | CI process | `gl_test` job not yet complete for HEAD at review time; confirm green before freeze |
| S2 | should-fix | docs/SPEC.md | TIMEOUT documented as "255 cycles"; RTL/tests consistently use 63 |
| S3 | should-fix | src/binner_meas.v | unseen-channel wait gate (`wcnt[4]`) is non-monotonic, can delay (never corrupt) DONE |
| S4 | should-fix | docs/VARIATION_MODEL.md | stale/unresolved ±0.01 s_n−s_p target despite a known, reported ~0.025 RMSE miss |
| S5 | should-fix | docs/CSV_SCHEMA.md | fingerprint-tail description ("120 pairs") doesn't match the actual implementation (16 pairs) |
| N1 | nice-to-have | project.v / SPEC.md | FREE-mode CNTA/CNTB multi-bit reads are unsynchronized (documented debug-only; low risk) |
| N2 | nice-to-have | docs/SPEC.md §4 | STATUS bit 7 (FMAX_ARMED) implemented but absent from the STATUS bit table |
| N3 | nice-to-have | docs/SPEC.md §5/§6 | no documented interlock against selecting source 19 while an Fmax sweep is armed |
| N4 | nice-to-have | src/binner_dchain.v | `ring_mode`/`ring_en` are always tied to the same net in this design; the module's `ring_en=0` static-force path is structurally unreachable in the current instantiation |

---

## S1 — `gl_test` job not confirmed complete for HEAD at review time (should-fix, process)

**What I found.** `python tools/ci.py jobs 36665848962` (the `gds` workflow run
at `feat/must` HEAD `dc0ebf4e`) showed `gds`/`precheck`/`viewer` = `success`
but `gl_test` still in progress (`step 3: GL test -> None`), repeatedly, over
several minutes of polling. `python tools/ci.py fetch --branch feat/must`
successfully pulled `GDS_logs`, `gds_render`, `tt_submission`,
`precheck_reports`, `github-pages` and `test-results` artifacts, but **no**
`gatelevel_test_results` artifact (the one `gl_test` uploads) — confirming the
job genuinely hadn't finished, not just a stale API cache.

**Why it matters.** The review brief's framing ("latest commit, fully green
CI: docs/test/gds/precheck/gl_test/viewer all pass") was not yet true at
inspection time for the actual HEAD commit. `gl_test` runs the same cocotb
regression against the real post-route powered netlist (`GATES=yes`
semantics) — it's the one CI job that could catch a synthesis/PnR-introduced
functional regression the behavioural suite can't see. Everything else in
this report is unaffected (RTL unchanged since commit `9692913`, confirmed by
`git log --oneline 9692913..HEAD -- src/` returning empty, so the physical
netlist `gl_test` is simulating is identical to the one already `gl_test`-passed
at `9692913`), so this is very unlikely to fail — but it must be confirmed
green, not assumed, before treating the design as frozen/submission-ready.

**Recommendation.** Before submitting: re-run `python tools/ci.py status
--branch feat/must` (or `wait`) and confirm `gl_test`'s conclusion is
`success`. If it fails, treat as blocking and escalate immediately (would be
surprising given the unchanged RTL, but must not be assumed).

---

## S2 — docs/SPEC.md's TIMEOUT cycle count contradicts the RTL and the test suite (should-fix)

**Where.** `docs/SPEC.md:79`: *"TIMEOUT = 1 means the acknowledge did not fall
within 255 cycles."*

**What the RTL actually does.** `src/binner_meas.v:62`: `wire [5:0] wcnt =
gcnt[5:0];` — a **6-bit** wait counter, checked against `6'h3F` (63) at
`src/binner_meas.v:121-123`. The module's own header comment
(`src/binner_meas.v:29-30`) says *"If any channel's ack is still high 63
cycles after the gate ... the controller finishes anyway and sets TIMEOUT."*
The test suite agrees with the RTL, not the spec:
`test/test_meas.py:230` — *"controller must capture anyway after 63 cycles
and flag TIMEOUT (SPEC 5)"* — and the test that exercises it
(`test_timeout_free_mode`) is written and passes against 63, not 255.

**Why it matters.** This is a genuine contract/RTL mismatch in the one
document `GROUND_TRUTH.md` explicitly designates as the source of truth ("If
this document and the RTL disagree, that is a bug; report it" —
`docs/SPEC.md:4`). A firmware engineer or the bring-up script's author reading
only the spec would size a polling/retry budget around the wrong number (4x
too generous, so not itself dangerous, but wrong).

**Fix.** Change `docs/SPEC.md:79` to say 63 cycles (matching the RTL/tests),
or — if 255 was actually the originally *intended* value and 63 is the bug —
widen `wcnt` to 8 bits and the compare to `8'hFF` in `binner_meas.v` instead.
Given the RTL, comments, and tests are unanimous at 63, the doc is almost
certainly the stale side; I did not find any code path that depends on 255.

---

## S3 — `binner_meas.v`'s "unseen channel" ready gate is non-monotonic (should-fix, bounded)

**Where.** `src/binner_meas.v:68-69`:
```verilog
wire ok_a = seen_a ? ~ack_a : wcnt[4];   // unseen channel: wait 16 cycles
wire ok_b = seen_b ? ~ack_b : wcnt[4];
```

**What I found.** `wcnt` free-runs 0→63 in `S_WAIT` (frozen at 63). `wcnt[4]`
(bit 4, value 16) is **true for wcnt∈[16,31] and [48,63], but false for
wcnt∈[0,15] and [32,47]** — it is not a monotonic "becomes 1 at 16 and stays
1" signal as the adjacent comment and `docs/SPEC.md`'s "waits a fixed 16
cycles" language both describe. I verified this is not just a documentation
nit by tracing the actual completion condition
(`src/binner_meas.v:122`: `if ((ok_a && ok_b) || wcnt == 6'h3F)`):

- If **both** channels are unseen, `ok_a == ok_b == wcnt[4]` always (same
  signal), so they always agree and the FSM completes correctly and exactly
  at `wcnt==16`. No bug in the common "both dead" case.
- If one channel is seen (real ack, monotonic — becomes 1 once and stays 1)
  and the other is unseen, completion happens at the first instant `wcnt[4]`
  is 1 *after* the seen channel's ack has fallen. If the seen channel's ack
  happens to fall unusually late (a legitimately very slow but non-dead
  source, e.g. a long delay-chain tap), specifically during `wcnt∈[32,47]`,
  `ok_b` is transiently 0 again in that window (bit 4 having dropped back to
  0 at `wcnt==32`), and completion is pushed out to `wcnt==48` instead of
  firing the instant the seen channel became ready. This never produces wrong
  *data* (CNTA/CNTB values are unaffected either way) and is unconditionally
  bounded by the existing `wcnt==6'h3F` forced-completion backstop, so it is
  not a hang or a correctness bug — just up to 16 extra idle clk cycles and a
  documentation mismatch ("wait a fixed 16 cycles" is not literally what the
  hardware does).

**Fix.** Replace `wcnt[4]` with a monotonic comparison, e.g. `wcnt >= 6'd16`
(one extra 6-bit comparator, negligible area) for both the "becomes ready"
semantics the comment/spec describe and to remove the latent (bounded, benign
today) timing wrinkle.

---

## S4 — docs/VARIATION_MODEL.md still states an unmet precision target with no in-file pointer to the known miss (should-fix)

**Where.** `docs/VARIATION_MODEL.md:39`: *"Stated error targets for N = 20: ...
per-chip s_n − s_p within ±0.01..."*, with no caveat in that file.

**What I found.** This target is not met, and the project already knows it in
detail: `analysis/VALIDATION.md:77` — *"s_n - s_p (per die) | +/-0.01 | 0.02523
| 0.01 | MISSED"* — and `analysis/VALIDATION.md:71` explicitly says *"This
script does not edit docs/VARIATION_MODEL.md ... flagged here ... for a human
to decide whether to relax the target."* `DECISIONS.md`'s D-UTILIZATION entry
also lists this exact item as *"Decision deferred to the docs/freeze pass."*

**Why it matters.** This review is happening at what DECISIONS.md itself
calls the deferred "docs/freeze pass" — i.e. now is when this was supposed to
get resolved, and it hasn't been. As written, `docs/VARIATION_MODEL.md` on
its own (without cross-referencing `DECISIONS.md` or
`analysis/VALIDATION.md`) presents the ±0.01 target as the current
spec, misleading a reader who only opens that one file.

**Fix (owner decision, not mine to make per the task boundaries):** either
relax the stated target to reflect the measured ~0.025 RMSE floor (the
project's own recommended resolution, attributed to having only one NAND ring
and one NOR ring per die), or add a one-line pointer in
`docs/VARIATION_MODEL.md` itself to `DECISIONS.md`'s entry so the file is
self-consistent even in isolation.

---

## S5 — docs/CSV_SCHEMA.md's fingerprint description doesn't match what `binner_bringup.py` actually computes (should-fix)

**Where.** `docs/CSV_SCHEMA.md:46`: *"...followed by 12 hex digits of
CRC-free raw ratio sign bits from **all 120 pairs**, compressed..."*

**What actually happens.** `bringup/binner_bringup.py`'s `_fold_hash48`
docstring (lines 909-923) says outright: *"the schema text references all
C(16,2)=120 ring-pair combinations, but stage 4 only measures the 16
canonical pairs... measuring all 120 pairs x 11 reps would add >7x runtime...
This hash instead folds every raw ratio actually measured in stage 4...
Flagged as an underspecified area in the final bring-up report."* i.e. the
implementer already knows the schema doc is wrong and said so in a code
comment, but `docs/CSV_SCHEMA.md` itself was never corrected.

**Why it matters.** Anyone implementing an independent CSV reader/validator
against the schema doc alone (the stated purpose of `docs/CSV_SCHEMA.md`)
would build the wrong mental model of what the fingerprint tail encodes.

**Fix.** Update `docs/CSV_SCHEMA.md:46` to describe the actual fold (16
canonical pairs × `repeats` ratios, not 120 pairs), or note explicitly that
120-pair coverage was descoped and why, matching the bring-up script's own
comment.

---

## N1 — FREE-mode CNTA/CNTB reads are genuine unsynchronized multi-bit CDC (nice-to-have, already scoped/tested correctly)

`docs/SPEC.md`'s own §4 table says CNTA/CNTB are *"live (debug only) in FREE
mode"*, and this is a real exception to the checklist's stated invariant that
"multi-bit counter values [are] read only when statically known-quiescent per
the DONE handshake" — in FREE mode (`ctl_free | pinmode`), `cnt_en` is held
high permanently (`src/binner_meas.v:132`) and the ring-domain ripple counter
is read directly through the clk-domain register mux
(`src/project.v:232-235`) with **no synchronizer** on the multi-bit value,
i.e. genuine bit-tearing/metastability exposure. I checked whether this is
actually treated as untrustworthy everywhere it's used: `test_meas.py`'s
`test_free_mode_clk2` (line 208-217) only asserts the debug byte *changes*
over time (`len(vals) > 1`), never a specific numeric value — correctly
treating it as qualitative. I did not find any place (bring-up script,
firmware, or test) that trusts a FREE-mode CNTA/CNTB *value* as accurate.
**Recommendation:** add a one-line comment at the `project.v` register-read
mux next to the CNTA/CNTB cases making this exception explicit in the RTL
itself (currently it's only in `binner_meas.v`'s comment and the spec table),
so a future maintainer extending the register map doesn't accidentally start
relying on it.

## N2 — STATUS bit 7 (FMAX_ARMED) is real but undocumented in the SPEC's bit table (nice-to-have)

`src/project.v:216`: `wire [7:0] status = {f_armed, mstat};` — bit 7 of the
STATUS register (0x08) is `f_armed`/FMAX_ARMED. `docs/SPEC.md`'s register
table (§4, the STATUS row) only lists bits 0-6. Not a functional bug (the bit
is real, readable, and matches `uo_out[7]`), just a documentation gap in the
one place (§4) that's supposed to be the complete bit-for-bit contract.

## N3 — no documented interlock between Fmax sweep and selecting source 19 (nice-to-have)

`binner_dchain.v` is shared physical hardware for both the Fmax tap chain and
the source-19 ring. Nothing in RTL or `docs/SPEC.md` §5/§6 prevents a caller
from arming an Fmax sweep (`CTRL.FMAX_EN` + `ui_in[7]`) while source 19 is
also selected and running as a ring (`ren[19]=1`, which sets `ring_mode=1`,
diverting the chain into feedback mode). This produces meaningless data for
whichever feature runs second (not X, not a hang, not silicon risk — just
silently wrong/confusing results), and is easy for a bring-up engineer to
trigger by mistake. `bringup/binner_bringup.py` itself never does this (its
stage 2/3 sequencing keeps them separate), so this is a documentation gap,
not an implementation bug. **Recommendation:** one sentence in §5 or §6
warning against selecting source 19 while an Fmax sweep is armed.

## N4 — `binner_dchain`'s `ring_mode`/`ring_en` ports are always tied together in this design (nice-to-have)

`src/project.v:152-155` wires both `ring_mode` and `ring_en` to the same net,
`ren[19]`. The module's own header comment documents a `ring_en=0` static-
force safety path as distinct from `ring_mode` (*"ring_en = 0 forces fb = 1,
so the loop is static whenever the ring is not running"*), but in this
instantiation that state (`ring_mode=1, ring_en=0`) is unreachable — the two
signals are always equal. Not a bug (the two reachable states, `mode=en=0`
Fmax-path and `mode=en=1` ring-path, are both correct and were confirmed
X-free by `test_struct.py::test_ring_disabled_static_no_x`), just dead
generality worth a one-line comment or port simplification for whoever reads
the module in isolation.

---

## False-alarms-I-checked (independently verified, no action needed)

- **CI workflow integrity.** Byte-for-byte diff of all four
  `.github/workflows/*.yaml` against `raw.githubusercontent.com/TinyTapeout/
  ttgf-verilog-template/main/.github/workflows/*.yaml` (fetched fresh, not
  from memory): **identical**, zero bytes of difference. The project's hard
  boundary ("do not weaken/skip/edit TT's actions") is respected.
- **`RUN_KLAYOUT_DRC=0` / `RUN_KLAYOUT_XOR=0` in `src/config.json`.** Diffed
  against the live template's `src/config.json`: these are already `0` in the
  unmodified template ("Disabled for Efficiency" section), not something this
  project turned off. The only diffs from template are the documented,
  justified ones (`CLOCK_PERIOD`, `RSZ_DONT_TOUCH_RX`, `FALLBACK_SDC_FILE`),
  all covered by `DECISIONS.md` entries, and everything below the file's own
  "DO NOT CHANGE ANYTHING BELOW THIS POINT" marker is untouched.
- **LFSR de Bruijn splice (`src/binner_lfsr.v`).** Independently re-derived
  (not just read) the math: with taps q15^q14^q12^q3 (primitive per XAPP052),
  the vanilla LFSR's only lock-up is the all-zero state, and the sole
  predecessor of 0x0001 among nonzero states under the vanilla recurrence is
  0x8000 (solved directly: p[14:0] must be all-zero, so p∈{0x0000,0x8000}).
  The `zero15`-gated feedback correctly reroutes 0x8000→0x0000→0x0001,
  producing a single Hamiltonian cycle over all 2^16 states. Reset/reseed
  value 0xACE1 is on that cycle. Confirmed independently, not just trusting
  `DECISIONS.md`.
- **Reset.** Every flop I read (`binner_sync.v`, `binner_lfsr.v`,
  `binner_meas.v`, `binner_rcnt.v`, `binner_spi.v`, `project.v`'s `r_ctrl`/
  `r_srca`/`r_srcb`/`r_timing`/`clk_div2`) uses `always @(posedge clk or
  negedge rst_n)` with a reset branch that assigns every bit. `rst_sync` is
  correct async-assert/2-flop-sync-deassert. Ring domains are held cleared
  through reset via `rarst_n = rst_sn & ~ring_clr`, and `ring_clr` itself
  resets to 1. `test_reset.py::check_all_reset_values` walks every register
  address 0x00-0x11 against `docs/SPEC.md`'s table via `RW_REGS`/`RO_RESET`/
  `MISC` dictionaries (verified this isn't a partial subset by reading the
  full walk) plus explicit unmapped-address checks; `test_rings_off_after_
  reset` hierarchically probes all 20 ring enables, including from a
  mid-run state and via async assertion (no clock edge).
- **CDC.** `arm_lvl` reaching `binner_fmax` is pre-synchronized at the top
  level (`project.v`'s `u_s_fr` `binner_sync2` on `ui_in[7]`, combined
  combinationally with `ctl_fen`/`~pinmode` — no unsynchronized raw pin
  reaches the module). `ack_a`/`ack_b` are correctly double-synchronized both
  directions (ring→clk via `en_ack`→`binner_sync2` in `binner_meas.v`). No
  ring/chain net is ever passed to `create_clock` (`binner.sdc` only clocks
  the `clk` port) or named in `CLOCK_PORT` (`config.json`). The only
  multi-bit crossing is the intentional, documented, correctly-tested
  FREE-mode exception (N1 above).
- **At-most-two-rings-enabled.** Structurally guaranteed by construction, not
  just tested: `ren[gi] = run & ((src_a==gi)|(src_b==gi))` for `gi` 0..19 —
  since `src_a`/`src_b` are exactly two 5-bit selectors, at most two `gi`
  values can ever match. `test_ring_enable_sweep` additionally sweeps 11
  hand-picked edge cases (both-same-source, dead sources, boundary
  values 20/21/31) plus 12 random combos — a genuinely convincing sweep, not
  a couple of cherry-picked cases.
- **`ena` gating.** Traced `run = ena & (ctl_run | pinmode)` directly back to
  the `ena` port; every ring's `en` derives from `run`, so `ena` cannot be
  bypassed. Outputs (`uo_out`/`uio_out`) are never gated by `ena` (correct per
  TT convention — `ena` need not gate outputs) and are fully, unconditionally
  driven (no missing bit assignments in `project.v`). `uio_oe` defaults to
  `8'h00` after reset (`ctl_uiooe` is bit 6 of `r_ctrl`, which resets to 0).
- **X-propagation, all ring kinds.** Independently re-ran `make struct`
  myself (real GF180MCU PDK cells, real specify-block timing) rather than
  trusting the committed report: `test_ring_disabled_static_no_x` covers all
  five ring kinds individually (INV idx 0, NAND idx 16, NOR idx 17, FO4 idx
  18, delay-chain) and passed, both immediately after disable and 2000 cycles
  later. Confirmed this is not a 1-ring spot check.
- **`make struct`'s two known failures (D-STRUCT-NAND-ARTIFACT,
  D-DTAP-RETUNE).** Independently reproduced both exactly: NAND ring (source
  16) measured 2.00 ns instead of 50.00 ns; delay-chain DTAP=4 measured
  9.00 ns instead of 26.00 ns (identical numbers to `DECISIONS.md`/
  `test/COVERAGE.md`'s claims). `DECISIONS.md`'s investigation is
  independently well-corroborated: the SDF-based (`tools/sdf_predict.py`)
  cross-check is a fundamentally different, non-dynamic-simulation method
  with no X-propagation/notifier machinery to glitch, and it shows the NAND
  ring behaving physically sensibly (slower than INV, as a NAND2's intrinsic
  delay predicts) at every corner — good independent corroboration that this
  is a simulator artifact, not a design defect. D-DTAP-RETUNE's mitigation
  (disable the ring before changing DTAP) is correctly and unconditionally
  implemented in `bringup/binner_bringup.py`'s `configure_and_measure`
  (writes `CTRL=0` before every `SRCA` write, unconditionally, for every
  caller). Both are legitimately `make struct`-only, developer-only, and
  correctly excluded from CI (`test/Makefile`'s default goal is `sim` via
  `GATES` branch selection; `struct` requires explicit `make struct`).
- **Netlist audit / metrics, re-run fresh, not trusted from the repo.**
  `git log --oneline 9692913..HEAD -- src/` is empty — **zero** RTL changes
  since the last real hardening run, so the committed `docs/reports/9692913/`
  artifacts are still current for HEAD's actual logic. I fetched that run's
  real CI artifacts fresh (`tools/ci.py fetch --sha
  9692913f4479e930e3a3e465d0fffe13efd14700`) and re-ran both
  `tools/netlist_audit.py` and `tools/metrics_summary.py` against them myself:
  netlist audit **PASS** (0 FAIL, 0 WARN) on all three netlist variants
  (tt_submission powered, GDS_logs nl.v, GDS_logs pnl.v, 3334 instances each);
  metrics reproduced **exactly** the committed numbers (81.98% utilization,
  0.000/0.000 setup WNS/TNS and 0/0.000 hold WNS/TNS at all 9 corners, 3
  max-fanout violations, 0 antenna/DRC errors) — confirms the committed
  report is not stale and is reproducible byte-for-byte from source
  artifacts, not just copy-pasted.
- **48/48 behavioural regression, re-run myself**, not trusted from a prior
  report: `make clean && make` in `test/` → `TESTS=48 PASS=48 FAIL=0 SKIP=0`.
- **Bring-up register map.** Every `REG_*`/`CTRL_*`/`CMD_*`/`STATUS_*`
  constant in `bringup/binner_bringup.py` (lines 79-121) cross-checked
  bit-for-bit against `docs/SPEC.md` §4's current v0.2 table: exact match,
  including CTRL bit positions, CMD pulse bits, and STATUS flags.
- **CSV data conformance.** Spot-checked `data/vboard/pop20_seed20260929/
  binner_sim00.csv`: metadata header, 14-column header row, and both an `id`
  stage-1 row and a `ring` stage-2 row match `docs/CSV_SCHEMA.md`'s column
  list and `aux`-field conventions exactly.
- **No tautological/placeholder tests found.** Grepped the whole test/
  analysis/tools tree for `assert True`, stray `pass  #`, `TODO`/`FIXME`/`XXX`
  markers: none. Every assertion I sampled compares against an independently
  computed expected value (a Python model of the LFSR, a closed-form ring
  frequency/period formula, or a structural hierarchical probe), not a
  circular re-statement of the RTL.

---

## Notes on scope not fully exhausted

Given the size of this design, I did not line-by-line re-derive every
assertion in `test_spi.py`, `test_fmax.py`, `test_lfsr.py` and
`test_pinmode.py` (I did read `test_reset.py` and `test_ring.py` in full, and
spot-checked the others' structure/naming for tautology, finding none). I
also did not re-derive `analysis/binner_analysis.py`'s statistical estimators
from first principles beyond cross-checking the one flagged discrepancy
(N/P-skew RMSE, S4) against `analysis/VALIDATION.md`'s own numbers. Both are
reasonable places for a follow-up pass if more review time is available, but
I did not find anything in my sampling of them that looked wrong.
