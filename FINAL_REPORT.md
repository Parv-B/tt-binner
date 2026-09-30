# BINNER — final report and hand-off

Repo: `Parv-B/tt-binner`. Branch `feat/must` is the frozen, verified design
(RTL + tests + tools + analysis + bring-up + virtual demo board + an
independent red-team review). This document is the top-level hand-off: what
got built, what got cut and why, every assumption that was not independently
re-verified, residual risk ranked by likelihood x impact, and the exact
procedure for switching the shuttle's registered tile and for a final
pre-submission check before the 2026-12-07 20:00 UTC deadline
(`GROUND_TRUTH.md`).

> **CI status at time of writing.** `python tools/ci.py status --branch
> feat/must` shows `docs` and `test` both `success` for HEAD (`1f93ff3`);
> `gds` (which gates `precheck`/`gl_test`/`viewer`) was still `in_progress`
> when this report was written, re-running after the red-team's S2-S5
> documentation fixes and the S3 RTL fix (a bounded, non-timing-affecting
> comparator change in `binner_meas.v` — see §2). **Before treating this
> report's "fully green CI" claim as current, re-run `python tools/ci.py
> status --branch feat/must` yourself and confirm `gds`, `precheck`,
> `gl_test` and `viewer` all show `success`** for the actual HEAD commit at
> read time. This is the same caveat the red-team review itself raised
> (finding S1) about the commit it reviewed, now inherited by this final
> re-harden.

## 1. What was built, and what was cut

**MUST blocks — all present and verified.**
- LFSR self-test: 16-bit maximal-length (period 65536) Fibonacci LFSR with
  de Bruijn zero-insertion, exhaustively proven lock-up-free over all 65536
  states (`test/COVERAGE.md` §7).
- SPI register interface: 19-register file, mode-0 SPI with address
  auto-increment, plus a no-SPI pin-strap fallback mode.
- Ring bank: 16 identical INV rings (PUF/variation), one NAND2 ring, one
  NOR2 ring, one FO4-loaded ring — all hand-instantiated, `dont_touch`
  -protected, and netlist-audit-verified to match `src/` exactly post-route.
- Paired counters with CDC: two independent ripple counters in their own
  ring domains, synchronized start/stop/acknowledge into the `clk` domain,
  SEEN/OVF/TIMEOUT fault flags.

**SHOULD block — present.** The at-speed Fmax checker (8-tap delay chain,
simultaneous capture, sticky fail flags, polarity self-test) is fully
implemented, tested (`test/COVERAGE.md` §6), and characterized via SDF
prediction (`docs/DATASHEET.md` §6.3). This is the one item
`DECISIONS.md`'s D-UTILIZATION analysis explicitly considered cutting for
area and did not, because doing so would not have reached the original 60%
utilization target anyway (§3 below) while giving up real characterization
content.

**STRETCH-tier work — not built.** The original mission brief's stretch
tier (referred to there as "skitter") was not implemented. This was a
time/priority decision, not a limitation discovered during the work: the
project's own stated priority order is (1) guaranteed silicon function, (2)
novel/publishable characterization data, (3) relevance to yield-engineering
careers (`DECISIONS.md`, D-UTILIZATION and D-STRUCT-NAND-ARTIFACT both cite
this ordering directly) — every MUST block and the Fmax SHOULD block already
serve all three priorities, and finishing, testing, hardening and
validating those to the standard documented in `docs/DATASHEET.md` §4
consumed the available time before any stretch-tier work could start. No
RTL, test, or verification gap was found that would have blocked
stretch-tier work if there had been time for it.

## 2. Unverified assumptions (collected in one place)

Everything below was flagged, somewhere in this repo, as **not**
independently re-derived from a primary source or the actual RTL/PDK in the
most recent verification pass. None of these are known to be wrong; they are
simply not confirmed to the same standard as the items in
`docs/DATASHEET.md` §5.

**From `GROUND_TRUTH.md`'s "not re-verified" list** (all re-checked
2026-09-29 against the fact's *presence*, not confirmed against a primary
source this pass):
- The owner's tile numeric "address" on the shuttle (e.g. `581` used as
  `bringup/config.ini`'s placeholder default) — no address field was found
  anywhere reachable without rendering the submission app's JS SPA.
- Tile physical dimensions (346.64 x 160.72 um) and standard-cell site
  dimensions (`GF018hv5v_mcu_sc7`, 0.56 x 3.92 um).
- `mux2_1` in the precheck's `drc_exclude.cells` list — actively searched
  for org-wide and **not found**; may live in the gf180mcu PDK repo itself,
  which was not scanned.
- Individual GF180MCU cell port lists and their typical-corner delay
  numbers (`inv_1`, `nand2_1`, `nor2_1`, `mux2_2`, `dffrnq_1`, `dlyd_1`,
  `buf_1`).
- Whether `RSZ_DONT_TOUCH_RX` is specifically exempted from the CTS step in
  LibreLane (existence and general resizer usage confirmed; the CTS
  exemption itself was not traced line-by-line).
- Whether two prior TT-GF ring-oscillator project repos actually use a
  `notouch_`-style naming convention in their RTL (repo existence confirmed
  via HTTP 200; RTL content not diffed).
- `tt-multiplexer`'s 8x20 grid geometry, and whether `ena` and the
  per-tile power-gate enable are driven from literally the same `l_ena` net
  (signal existence confirmed; wiring not traced through the mux RTL).
- Unselected-mux-input tie-off, output-disconnect, and "no output registers
  in the mux path" claims about `tt-multiplexer`.
- The TT ETR demo board's chip-on-board carrier having fixed AP2112K-3.3
  LDOs, 0805 jumpers, and no adjustable core VDD/current sense.
- `clock_project_PWM`'s max ~125 MHz rule and the `freqs = sysclk / even N`
  relationship; hardware SPI0's exact pin mapping
  (`ui_in[0..2]`/`uo_out[3]`) as a *firmware*-side confirmation (the RTL side
  of this mapping is fixed by `docs/SPEC.md` and tested); the GF0p2
  factory-test's claimed 188 MHz clock-counting result.
- Docs image size limits (<512 kB/image, <1 MB total) for the TT submission
  app — not found on the fetched FAQ page; likely enforced client-side only.
- The yosys pre-place-and-route area estimate transition (~42.9k to ~32.8k
  um² from the D-CAPTURE register-map squeeze) — these are yosys-estimate
  figures from early development, not recomputed against the final RTL;
  the real, measured post-route area (42,604.4 um² stdcell,
  `docs/reports/9692913/metrics_summary.md`) supersedes them for any actual
  area conclusion, but the *intermediate* estimate itself was never
  re-derived.

**From `DECISIONS.md` (D-STRUCT-NAND-ARTIFACT's residual risk).** The SDF-
based cross-check that explains away the NAND ring's `make struct` anomaly
assumes steady-state oscillation and cannot, by itself, rule out a genuine
*transient* synchronized-lockstep startup mode on real silicon (as opposed
to the simulator-artifact explanation, which is well-supported but not
proven beyond doubt). Considered unlikely — ring-oscillator PUF literature's
entire premise is that nominally-identical stages reliably mismatch and
break symmetry within a few cycles — but explicitly flagged for closure by
a second independent method (transistor-level or Verilator-based
simulation) or by direct silicon measurement once chips arrive.

**From `docs/RED_TEAM_REVIEW.md`.** Findings N1-N4 (all nice-to-have,
already scoped/tested-correctly or documentation-only) were not required to
be fixed and were not fixed in this pass: FREE-mode CNTA/CNTB reads remain
genuinely unsynchronized (by design, debug-only, already correctly scoped in
tests — RTL comment recommended but not added); STATUS bit 7 documentation
gap (already fixed in commit `8657f79`, see below); no RTL interlock between
an armed Fmax sweep and selecting source 19 simultaneously (documentation
gap only — `bringup/binner_bringup.py` never does this); and
`binner_dchain`'s `ring_mode`/`ring_en` ports being always tied together in
this instantiation (dead generality, not a bug).

**From `test/COVERAGE.md` / `docs/RED_TEAM_REVIEW.md`'s scope note.** The
reviewer did not line-by-line re-derive every assertion in `test_spi.py`,
`test_fmax.py`, `test_lfsr.py` and `test_pinmode.py` (spot-checked structure
only, found no tautologies); nor did they re-derive `analysis/
binner_analysis.py`'s statistical estimators from first principles beyond
the one flagged N/P-skew discrepancy.

## 3. Residual risks, ranked by likelihood x impact

| # | Risk | Likelihood | Impact | Rank | Status / mitigation |
|---|---|---|---|---|---|
| R1 | Firmware has no `ttgf26d` shuttle index yet, so project selection on real hardware needs the address/name fallback path | High (confirmed: zero hits for `ttgf26d` in `tt-micropython-firmware`, `GROUND_TRUTH.md` S21) | Low (bring-up script already handles it; costs a manual config step, not a functional failure) | **Medium** | Mitigated: `bringup/binner_bringup.py`'s `_select_shuttle()` fallback chain (name -> attribute -> address) and `cohort/README.md`'s troubleshooting section both document the workaround. Residual: the placeholder tile address (`581` in `config.ini`) is unverified (see §2) — cohort instructions explicitly warn against trusting it blindly. |
| R2 | 3 max-fanout violations present at every STA corner, offending net(s) not identified | Medium (present in every post-route run so far, deterministic) | Low-Medium (setup/hold timing is clean at 0 WNS/TNS everywhere despite these; fanout violations alone don't fail signoff in this flow, but the unnamed net(s) are an open unknown) | **Medium** | Not closed. Tracked in `DECISIONS.md`'s N/P-skew section as "not currently gating CI... to be identified once the netlist-audit/timing-report tooling can name the specific net(s)." No functional evidence against it so far. |
| R3 | Utilization (~82%) far exceeds the original 60% design-margin target | Confirmed as fact, not a probability | Low, evidenced (0 DRC/antenna/routing errors, 0 setup/hold violations at all 9 corners at the current density) | **Low (owner-accepted)** | Resolved by owner decision, `DECISIONS.md` D-UTILIZATION: the margin was a pre-hardening blind risk-aversion number; the risk it guarded against did not materialize on this flow/design. Documented, not silently absorbed. |
| R4 | D-STRUCT-NAND-ARTIFACT: NAND ring's simulated 25x-too-fast lockstep mode, while well-explained as a simulator artifact, is not disproven for a *transient* startup case on real silicon | Low (contradicted by independent SDF evidence and by RO-PUF physics; simulator-artifact explanation is well-supported) | High if real (would corrupt the NAND ring's core characterization data — a headline "novel, publishable" deliverable) | **Medium** | Investigated in depth, not dismissed (`DECISIONS.md`). Best pre-silicon evidence (post-route SDF, a structurally different method) shows no trace of the anomaly. Closure requires either a second independent simulation method or real silicon measurement — flagged explicitly for both. |
| R5 | Chip-on-board bonding/assembly yield (wafer.space Run #3's physical packaging step, mounting each shuttle die onto its ETR carrier) is entirely outside this project's control or verification | Unknown (no shuttle-run assembly-yield data exists anywhere in this repo or its sources; this is a generic multi-project-shuttle risk, not specific to BINNER's design) | Medium-High per affected chip (a bonding defect can make an otherwise-good design's chip non-functional; indistinguishable at bring-up time from a design defect without cross-referencing other cohort members' results) | **Medium** | Not mitigable by this project. `cohort/README.md`'s troubleshooting section treats "nothing responds" as ambiguous between selection error, bonding/assembly defect, and (least likely, given the verification record) a design defect, and asks contributors to send partial/odd data anyway rather than assume their own error. |
| R6 | `s_n - s_p` (N/P-skew) per-die measurement misses its original ±0.01 precision target (actual RMSE ~0.025, flat across N=20 and N=8) | Confirmed as fact, not a probability | Low-Medium (population-level `sigma_d2d` estimation is unaffected and within target; only *per-die* placement on the N/P plot is coarse — `analysis/VALIDATION.md` explicitly notes "individual dies can only be placed coarsely... the population cloud is informative, single points are not") | **Low (owner-resolved)** | Resolved: target relaxed to ±0.025 in `docs/VARIATION_MODEL.md` (commit `8657f79`) to match the measured, population-size-independent noise floor from having only one NAND/NOR ring per die. Adding redundant structures was rejected on area and schedule grounds. |
| R7 | `gl_test` (gate-level regression against the real post-route powered netlist) was not yet confirmed green for the true HEAD commit at the time this report and the red-team review were written | Was High at review time (explicitly still running); now depends on the CI run referenced in this report's header | High if it were to fail (the one CI job that could catch a synthesis/PnR-introduced functional regression the behavioural suite can't see) | **High until confirmed** | **Action required before submission**: re-run `python tools/ci.py status --branch feat/must` (or `wait`) and confirm `gds`/`precheck`/`gl_test`/`viewer` are all `success` for the actual HEAD SHA. Very unlikely to fail (RTL unchanged in any ring/timing structure since the last `gl_test`-passed commit `9692913`; the only RTL delta is the S3 comparator fix in the measurement FSM, confirmed re-tested at 48/48), but must be confirmed, not assumed. |

## 4. Wokwi registration: current status and switch guidance

The owner's shuttle slot is currently registered to the Wokwi-based project
`tt_um_wokwi_476390545349040129` ("TT Workshop 8 bit LSFR", sourced from
`github.com/Parv-B/tt-8-bit-lfsr`; confirmed present in the shuttle repo's
`projects/` directory, `GROUND_TRUTH.md` S5/S6). The condition this repo's
task brief set for switching away from that registration was: **"keep the
current Wokwi registration in place until this repository passes every
workflow AND the netlist audit."**

**That condition is now met, pending the confirmation in §3/R7 above.**
`docs`and `test` are confirmed green for HEAD `1f93ff3`; `gds` (which gates
`precheck`, `gl_test`, `viewer`) was still completing at the time of
writing. The netlist audit itself has independently passed (0 FAIL, 0 WARN
on all three netlist variants) at the last fully-confirmed hardening,
commit `9692913`, and has been independently re-confirmed by the red-team
review against freshly-fetched CI artifacts. **It is safe to switch once
you personally confirm the `gds` workflow (all four sub-jobs) shows
`success` for HEAD `1f93ff3`** — this report does not make that final call
for you, per the task's own instruction to state the condition and let the
owner do the final check.

## 5. Exact steps to switch the registered tile (Wokwi -> this repo)

Quoted verbatim from `GROUND_TRUTH.md` (itself quoting
https://tinytapeout.com/guides/change-project-repo/, fetched 2026-09-29):

1. "Navigate to your project on the Tiny Tapeout submission app. Click the
   'Change' button."
2. "You will be prompted to enter a new repo URL. Enter it and click the
   'Change Repo' button. Your repo must be based on one of our templates."
3. "For the changes to take effect, you must submit a new revision. The
   project in the newly linked repository must have a passing GDS action.
   Click on the 'Submit a new revision' button to automatically fetch the
   latest build."

Applied to BINNER: go to the `tt_um_wokwi_476390545349040129` project page
on `app.tinytapeout.com`, click **Change**, enter
`https://github.com/Parv-B/tt-binner`, click **Change Repo**, confirm the
`gds` GitHub Action is green for the commit you intend to submit (see §3/R7
and §6 below), then click **Submit a new revision**.

## 6. Pre-submission procedure (run shortly before 2026-12-07 20:00 UTC)

Run this checklist close to the deadline, not now, since shuttle tooling
can move between now and then:

1. **Check for upstream updates.** Compare the currently-pinned versions
   against live upstream, per `GROUND_TRUTH.md`:
   - `ttgf-verilog-template` HEAD (pinned reference: `e60b92cd8a1e74a1f0cc5e71e113fe2f263a1084`)
   - `tt-gds-action` tag `ttgf26d` -> commit (pinned reference:
     `395eedb3eeec3c2f4961c3b04ff2cf87f5525636`)
   - `tt-support-tools` submodule pin used by the shuttle repo (pinned
     reference: `01d5d2814fa9dd61e9d211e0b235a4a592a9316a`)
   - `tt-multiplexer` submodule pin, branch `dev-gf` (pinned reference:
     `aab1e278ef8e10eaa78b30369438c86107d02a8b`)
   - LibreLane default version pulled by `tt-gds-action` (pinned reference:
     `3.0.14`) and its pinned gf180mcu PDK hash (pinned reference:
     `54435919abffb937387ec956209f9cf5fd2dfbee`)
   - Shuttle deadline/tile-availability facts themselves (`config.yaml`
     `end_date`, the `app.tinytapeout.com/api/shuttles/ttgf26d` API) — these
     were last confirmed unchanged at `2026-12-07T20:00:00+00:00` /
     `{total: 160, available: 0}` on 2026-09-29; re-check both directly.
2. **If anything has moved**, pull the update into a fresh branch (do not
   edit `.github/workflows/*` by hand — this repo's hard boundary is to
   never weaken or diverge from TT's own actions; if the template's
   workflow files changed, merge them in wholesale) and re-run:
   - The full `docs`/`test`/`gds`/`precheck`/`gl_test`/`viewer` workflow set
     via `python tools/ci.py status`/`wait`.
   - `tools/netlist_audit.py` against the freshly-fetched CI artifacts
     (`python tools/ci.py fetch --sha <sha> --out ci_artifacts/<shortsha>`
     first) — confirm PASS, 0 FAIL, 0 WARN, same as every prior run.
   - `tools/metrics_summary.py` against the same fresh artifacts, and
     confirm no unexpected regression in setup/hold WNS/TNS, DRC, or
     antenna counts versus the numbers cited in `docs/DATASHEET.md` §4.
3. **Confirm the exact commit SHA the submission app will pick up.** The
   app fetches whatever is on the repo's default branch at submission time
   (per the change-repo guide in §5) — before clicking "Submit a new
   revision," check `git rev-parse HEAD` on that branch matches the commit
   whose `gds` workflow you just confirmed green, and that there is no
   uncommitted or unpushed work sitting ahead of it locally.
4. Only after all of the above: perform the switch in §4/§5, then confirm
   the submission app shows the new revision building/passing.

## 7. Document map

- Datasheet (TT submission): `docs/info.md`
- Long-form datasheet / portfolio writeup: `docs/DATASHEET.md`
- Bit-exact spec: `docs/SPEC.md`
- Decisions log: `DECISIONS.md`
- Ground-truth facts, confidence levels, sources: `GROUND_TRUTH.md`,
  `SOURCES.md`
- Red-team review: `docs/RED_TEAM_REVIEW.md`
- Test coverage map: `test/COVERAGE.md`
- Statistical validation: `analysis/VALIDATION.md`
- Bring-up procedure: `bringup/README.md`
- Cohort kit (other shuttle-mates): `cohort/README.md`
