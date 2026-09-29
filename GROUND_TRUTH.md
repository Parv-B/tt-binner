# GROUND_TRUTH.md — BINNER (Parv-B/tt-binner, TTGF26d)

Re-verification pass run 2026-09-29 against primary sources (GitHub API/raw content, tinytapeout.com, app.tinytapeout.com). Full source log with URLs and commit SHAs: `SOURCES.md`. GitHub API calls used a short-lived token pulled in-process via `git credential fill`; the token was never printed, logged, or committed.

## Discrepancy flags (read this first)

**Shuttle deadline: NO CHANGE.** `end_date` in the shuttle repo's `config.yaml` and the `deadline` field of the live `app.tinytapeout.com/api/shuttles/ttgf26d` API both still read **2026-12-07** (`2026-12-07T20:00:00+00:00`), matching the earlier planning research exactly. Tiles remain `{total: 160, available: 0}` — also unchanged.

**No material discrepancies were found** in any fact that was successfully re-checked against a primary source today (config.yaml contents, both submodule pin SHAs, both `tt-gds-action` tag targets, LibreLane default version, both PDK commit hashes, GF180 corner names, forbidden-layer list, DRC variant string, our own CI run IDs/conclusions, the RSZ-3006 failure text, and the baseline-green claim). Everything checked matched the original planning research value-for-value.

One **informational note, not a discrepancy**: the public `local-hardening` guide's worked example pins `LIBRELANE_TAG=3.0.3` for a **SKY130** walkthrough. This project never runs that flow locally (see the Local Hardening Procedure section below) — the actual LibreLane version used by our CI is the `tt-gds-action` default **3.0.14** (re-verified, see D-CI row), so the guide's example number does not apply to us and is not a version drift on our side.

One **gap worth flagging to the team**: an org-wide GitHub code search for `mux2_1` across `TinyTapeout/tt-support-tools` and `TinyTapeout/tt-gds-action` returned no hit for a `drc_exclude.cells` list containing `mux2_1`. The fact may live in the gf180mcu PDK repo itself (not scanned) rather than in TinyTapeout tooling; see the "not re-verified" note on that row below. Treat that specific claim as unconfirmed until it is re-derived from the actual PDK exclude list.

---

## Ground-truth table

| Item | Value | Confidence | Source (URL + SHA/date) | Used by |
|---|---|---|---|---|
| Shuttle name/ID | TTGF26d, `id: 'ttgf26d'` | high | re-verified 2026-09-29 — raw `config.yaml` @ shuttle repo HEAD `b65dc6b0d52368a66b1d5d9f5d864ff6d92eff84` (SOURCES.md S1, S2) | D-PROCESS, D-SUBMIT |
| Shuttle repo HEAD | `b65dc6b0d52368a66b1d5d9f5d864ff6d92eff84` | high | re-verified 2026-09-29 — `api.github.com/repos/TinyTapeout/tinytapeout-gf-26d/commits/main` (S1) | D-CI, D-SUBMIT |
| PDK | `gf180mcuD` | high | re-verified 2026-09-29 — config.yaml (S2) | D-PROCESS, D-LIB |
| Shuttle deadline (`end_date`) | `2026-12-07` | high | re-verified 2026-09-29 — config.yaml (S2), cross-checked against app API (S3) | D-SUBMIT |
| `top_level_macro` | `tt_gf_wrapper` | high | re-verified 2026-09-29 — config.yaml (S2) | D-PROCESS, D-PINS |
| `no_power_gating` | `false` | high | re-verified 2026-09-29 — config.yaml (S2) | D-POWERGATE |
| `powered_netlists` | `true` | high | re-verified 2026-09-29 — config.yaml (S2) | D-GL |
| App API deadline | `2026-12-07T20:00:00+00:00` | high | re-verified 2026-09-29 — `GET app.tinytapeout.com/api/shuttles/ttgf26d` (S3) | D-SUBMIT |
| Tiles total/available | 160 / 0 | high | re-verified 2026-09-29 — app API (S3) — **unchanged from planning research** | D-SUBMIT |
| tinytapeout.com/chips: closes | 2026-12-07 | high | re-verified 2026-09-29 — WebFetch of tinytapeout.com/chips/ (S4) | D-SUBMIT |
| Fab / run | wafer.space Run #3 | high | re-verified 2026-09-29 — S4 | D-SUBMIT |
| Expected chips | 2027-05-12 | high | re-verified 2026-09-29 — S4 | D-SUBMIT |
| Expected shipping | 2027-06-09 | high | re-verified 2026-09-29 — S4 | D-SUBMIT |
| ArtScience Museum reservation footnote | "Currently reserved for ArtScience Museum Singapore. Unused tiles will be made available two days before the deadline." | high | re-verified 2026-09-29 — S4 (quoted verbatim) | D-SUBMIT |
| Owner's existing registered tile | Address slot at `tt_um_wokwi_476390545349040129`, title "TT Workshop 8 bit LSFR", from `github.com/Parv-B/tt-8-bit-lfsr` | high | re-verified 2026-09-29 — project present in shuttle repo `projects/` dir + `info.yaml` (S5); repo source confirmed via PR #10 (S6) | D-SUBMIT |
| Owner's tile numeric "address" (e.g. 581) | not confirmed | low | **not re-verified** — no address field found in `info.yaml`, PR #10, or the (client-rendered) app project page; the app's project detail page is a JS SPA that WebFetch cannot render (S6) | D-SUBMIT |
| tt-support-tools submodule pin | `01d5d2814fa9dd61e9d211e0b235a4a592a9316a` | high | re-verified 2026-09-29 — contents API gitlink at shuttle HEAD (S7) | D-CI |
| tt-multiplexer submodule pin (branch `dev-gf`) | `aab1e278ef8e10eaa78b30369438c86107d02a8b` | high | re-verified 2026-09-29 — S7 | D-CI, D-POWERGATE |
| tt-gds-action tag `ttgf26c` → commit | `395eedb3eeec3c2f4961c3b04ff2cf87f5525636` | high | re-verified 2026-09-29 — resolved annotated tag object (S8) | D-CI |
| tt-gds-action tag `ttgf26d` → commit | `395eedb3eeec3c2f4961c3b04ff2cf87f5525636` (**same commit as `ttgf26c`**) | high | re-verified 2026-09-29 — S8. Tag *object* SHAs differ from each other (`9af3185e...` vs `5265c7f9...`) because each carries separate tagger metadata, but both point at the identical underlying commit | D-CI |
| ttgf-verilog-template HEAD | `e60b92cd8a1e74a1f0cc5e71e113fe2f263a1084` | high | re-verified 2026-09-29 — S9 | D-CI |
| Template workflow pins `tt-gds-action@ttgf26c` | confirmed (all 4 sub-actions: root, precheck, gl_test, viewer) | high | re-verified 2026-09-29 — S9; our own repo's `.github/workflows/*.yaml` match this pin (S28, read-only) | D-CI |
| LibreLane default version | `3.0.14` | high | re-verified 2026-09-29 — `tt-gds-action/action.yml` input default @ commit 395eedb (S10) | D-PROCESS, D-CI |
| tt-support-tools ref default | `main` | high | re-verified 2026-09-29 — S10 | D-CI |
| PDK gf180mcu volare hash (main flow) | `54435919abffb937387ec956209f9cf5fd2dfbee` | high | re-verified 2026-09-29 — `librelane/pdk_hashes.yaml` at LibreLane release tag `3.0.14` exactly (S11) — traced from tt-gds-action's LibreLane version pin down into LibreLane's own pinned-hash file | D-LIB, D-PROCESS |
| precheck PDK hash | `e8daeda73ca8f5814dbc0b11d1d05802251a3750` | high | re-verified 2026-09-29 — `precheck/action.yml` @ commit 395eedb (S10) | D-PROCESS |
| Tile 1x1 dimensions | 346.64 x 160.72 um | medium | **not re-verified today** — not re-derived from LEF/GDS in this pass; unchanged from planning research, and low risk since it derives from the PDK commit that *was* re-verified unchanged (S11) | D-TILE, D-PACKAGE |
| Library | `gf180mcu_fd_sc_mcu7t5v0` (7-track) | high | re-verified 2026-09-29 — `tech.py` `LIB_SYNTH`/`LIB_FASTEST`/`LIB_SLOWEST` paths @ tt-support-tools commit 01d5d281 (S13) | D-LIB, D-CELLS |
| Site name / dims | `GF018hv5v_mcu_sc7`, 0.56 x 3.92 um | low | **not re-verified today** — not located via code search in the time available; unchanged from planning research | D-LIB, D-TILE |
| TT `VDD_PIN_VOLTAGE` | 3.3 | high | re-verified 2026-09-29 — `tech.py` (S13) | D-LIB, D-SDC |
| Corners | `tt_025C_3v30` (typ/synth), `ss_125C_3v00` (slowest), `ff_n40C_3v60` (fastest) | high | re-verified 2026-09-29 — exact `.lib` filenames in `tech.py` (S13) | D-LIB, D-SDC, D-FMAX-TAPS |
| Precheck forbidden layers (gf180mcuD) | `["Metal5", "Metal5_Label"]` | high | re-verified 2026-09-29 — `precheck/tech_data.py` `forbidden_layers` dict (S15) | D-PACKAGE, D-PROCESS |
| DRC deck / variant | `gf180mcu.drc`, variant `"gf180mcuD"` (comment: metal_top=11K, mim_option=B, metal_level=5LM) | high | re-verified 2026-09-29 — `precheck/precheck.py` lines 134-141 (S14) | D-PACKAGE, D-PROCESS |
| Project/power-pin top metal | `Metal4` (`power_pins_layer["gf180mcuD"]`) | high | re-verified 2026-09-29 — `precheck/tech_data.py` (S15) | D-PACKAGE |
| `mux2_1` in `drc_exclude.cells` | unconfirmed | low | **not re-verified — could not locate**: org-wide GitHub code search for `mux2_1` across TinyTapeout repos returned no `drc_exclude`-style match (S16); likely lives in the gf180mcu PDK repo itself, which was not scanned this pass | D-CELLS |
| Cell ports: `inv_1` I/ZN; `nand2_1` A1,A2/ZN; `nor2_1` A1,A2/ZN; `mux2_2` I0,I1,S/Z; `dffrnq_1` CLK,D,RN/Q; `dlyd_1` I/Z; `buf_1` I/Z | as listed | low | **not re-verified today** — would require parsing the PDK's Liberty/Verilog cell models directly; unchanged from planning research | D-CELLS |
| Typical `tt_025C_3v30` delays: `inv_1` rise 73-107ps / fall 48-66ps; `dlya`≈0.6, `dlyb`≈1.3, `dlyc`≈2.35, `dlyd`≈3.4ns | as listed | low | **not re-verified today** — same reason as above | D-CELLS, D-FO4-STAGES, D-FMAX-TAPS |
| `RSZ_DONT_TOUCH_RX` exists in LibreLane 3.0.14 | confirmed present | high | re-verified 2026-09-29 — GitHub code search hit in `librelane/scripts/openroad/common/resizer.tcl` and `librelane/steps/common_variables.py` (S12) | D-DONTTOUCH |
| `RSZ_DONT_TOUCH_RX` applied in resizer steps except CTS | as claimed | medium | **partially re-verified** — variable's existence and consumption by the resizer script confirmed (S12); the specific claim that CTS is exempted was not traced line-by-line in `common_variables.py`'s per-step wiring this pass | D-DONTTOUCH |
| Prior TT GF ring-osc projects using `notouch_`: `algofoogle/ttgf0p2-vga-ring-osc`, `dlmiles/ttgf0p2-ringosc-5inv` | both repos exist | medium | re-verified 2026-09-29 that both repos exist (HTTP 200, S22); the specific claim that both use a `notouch_` naming convention was **not** re-diffed against their RTL in this pass | D-DONTTOUCH, D-LOOP |
| GL test toolchain | iverilog **13.0** (TinyTapeout custom build, `TinyTapeout/iverilog` release `v13.0`), `-DFUNCTIONAL`, powered netlist | high | re-verified 2026-09-29 — `gl_test/action.yml` installs `iverilog_13.0-1_amd64.deb` (S10); `-DFUNCTIONAL` confirmed present in our own `test/Makefile` line 27 (S28); `powered_netlists: true` confirmed in shuttle config.yaml (S2) | D-GL |
| Multiplexer grid | 8x20 | low | **not re-verified today** — repo/branch pin confirmed current (S17), but grid geometry was not re-derived from `py/tt/layout.py` in this pass | D-TILE, D-PINS |
| Per-tile power gate; `ena` and pg-enable share `l_ena` | `l_ena` signal confirmed to exist and is referenced in `tt_mux.v`, `tt_top.v`, `tt_ctrl.v` | medium | **partially re-verified** — signal existence confirmed via code search (S17); the specific claim that `ena` and the power-gate enable are driven from the *same* `l_ena` net was not traced through the RTL logic this pass | D-POWERGATE |
| Unselected inputs tied 0 / outputs disconnected; no output registers in mux path | as claimed | low | **not re-verified today** — not re-derived from `tt_mux.v` RTL in this pass | D-POWERGATE, D-PINS |
| TT ETR demo board uses RP2350B | confirmed | medium | re-verified 2026-09-29 — WebSearch summary of tinytapeout.com/guides/get-started-demoboard-etr/ confirms RP2350B is the board's management MCU (S27); page was not fully WebFetched for every detail | D-BOARD |
| GF chip-on-board carrier: fixed AP2112K-3.3 LDOs, 0805 jumpers, no adjustable core VDD/current sense | as claimed | low | **not re-verified today** — not located in the ETR guide search summary; unchanged from planning research | D-BOARD |
| tt-micropython-firmware version | `v3.1.1`, published 2026-09-08 21:51 UTC | high | re-verified 2026-09-29 — GitHub releases page (S20); date matches planning research (2026-09-08) exactly | D-FIRMWARE |
| `clock_project_PWM` max ~125MHz (sysclk ≤ 250MHz, `freqs = sysclk / even N`) | as claimed | low | **not re-verified today** — not located in firmware repo search this pass | D-CLOCK, D-FIRMWARE |
| Firmware shuttle bundles: up to `ttgf0p2`, no `ttgf26d` index yet | confirmed — `ttgf0p2` found only in `.github/workflows/release.yml`; `ttgf26d` returns **zero** hits anywhere in the firmware repo | high | re-verified 2026-09-29 — GitHub code search across `TinyTapeout/tt-micropython-firmware` (S21) | D-FIRMWARE, D-BOARD |
| Hardware SPI0 on `ui_in[0..2]` / `uo_out[3]` | as claimed | low | **not re-verified today** — not located in firmware repo search this pass | D-SPI, D-PINS |
| GF0p2 factory test counted clocks correctly to 188MHz | as claimed | low | **not re-verified today** — not checked this pass | D-CLOCK, D-FMAX-TAPS |
| GitHub requirement: enable Actions | "Navigate to the Actions tab, click enable" | high | re-verified 2026-09-29 — tinytapeout.com/faq/ (S26) | D-CI, D-SUBMIT |
| GitHub requirement: Pages source = GitHub Actions | "Change Source from Deploy from a branch to GitHub Actions" | high | re-verified 2026-09-29 — S26 | D-CI, D-SUBMIT |
| `docs/info.md` placeholders rejected | confirmed — build rejects placeholder text in `author`, `title`, `description`, `how_it_works`, `how_to_test`, `language` | high | re-verified 2026-09-29 — S26 | D-CI, D-SUBMIT |
| Images <512kB each / <1MB total | not confirmed | low | **not re-verified today** — not present on the FAQ page fetched (S26); likely enforced client-side in the submission app UI rather than documented in a static guide | D-SUBMIT |

### Facts established during our own execution (this repo, re-verified 2026-09-29 via GitHub Actions API — see SOURCES.md S23-S25, S28-S29)

| Item | Value | Confidence | Source | Used by |
|---|---|---|---|---|
| Unmodified template fails CI by design | Confirmed by design intent (empty title/author/description → gds fails; placeholder docs + empty pinout → docs fails); the actual baseline commit `02a8a...`/`568ef71` in this repo already fills in required fields, so this claim describes the *upstream template's* default state, not a run we re-observed today | medium | re-verified 2026-09-29 that our baseline commit's workflows are green (S24), consistent with the fields being filled; the *unfilled-template-fails* claim itself was not re-run against a fresh unfilled template this pass | D-CI, D-SUBMIT |
| Baseline commit `568ef7147b9f9f80fcb379d3a8f5fa42bd456eac` green on all workflows incl. `fpga` | Confirmed: `fpga` run `36463429421` success, `gds` run `36463428531` success, `test` run `36463428359` success, `docs` run `36463428258` success | high | re-verified 2026-09-29 — Actions API run list (S24) | D-CI |
| First real hardening (RTL v0.1, commit `4673f5b7565ee2cea773823a460ea7f6fe22cce7`) FAILED with RSZ-3006 | Confirmed exact error: `[RSZ-3006] Failed to insert buffer before loads for net u_ring_nand.en`, preceded by `[ODB-1211] InsertBufferBeforeLoads: Load pin 'u_ring_nand.g_stg[10\].g_nand.stg_notouch_/A2' is dont_touch. Cannot insert a buffer.` — every load of the ring NAND's enable net was dont-touch, leaving the resizer no legal buffer-insertion point | high | re-verified 2026-09-29 — raw job log, run `36463341477`, job `109069809333` (S25) | D-DONTTOUCH, D-REGMAP |
| Fix (RTL v0.2, commit `908c9e18c8cbefb4f079439a7c6056e5b986299f`) | Added dedicated `notouch_` `BUF_1` stage on that enable net + squeezed register map (removed duplicate clk-domain capture registers since ring-domain counters ARE the capture registers; combined SPI shift registers into one; derived CMD pulses combinationally from the write strobe), area estimate cut from ~42.9k to ~32.8k um² (local yosys estimate — **not** independently re-verified this pass, see below) | medium | re-verified 2026-09-29 that this commit is the head of the branch and that its CI run succeeded (S23); the ~42.9k→~32.8k um² area numbers themselves are yosys-estimate figures from earlier work and were **not** recomputed in this pass | D-DONTTOUCH, D-REGMAP, D-CAPTURE |
| RTL v0.2 hardened successfully | Confirmed: gds workflow run `36464908611`, `conclusion: success`, `head_sha: 908c9e18c8cbefb4f079439a7c6056e5b986299f`. Sub-jobs: `gds` `109072435540` success, `precheck` `109074209083` success, `gl_test` `109074209359` success, `viewer` `109074209878` success | high | re-verified 2026-09-29 — Actions API run + jobs (S23) | D-CI, D-GL, D-PROCESS |
| Real measured utilization/area from CI artifacts | **Not yet available.** No `docs/reports/<sha>/` metrics-summary directory exists in this repo or in the sibling `tools`-focused worktree (`../agent-a85afed95f0feb0d1`), and no `tools/metrics_summary.py` script exists yet in either worktree. Pending — see `tools/metrics_summary.py` output once produced | high (confidence in the "not yet available" finding itself) | re-verified 2026-09-29 — directory listing of `../agent-a85afed95f0feb0d1/docs/reports/` and `/tools/` (read-only) plus this worktree's own `tools/` (S29) | D-REGMAP, D-CAPTURE |

---

## Exact steps to switch the registered tile from Wokwi to this repo

Quoted verbatim from **https://tinytapeout.com/guides/change-project-repo/** (fetched 2026-09-29, S18):

1. "Navigate to your project on the Tiny Tapeout submission app. Click the 'Change' button."
2. "You will be prompted to enter a new repo URL. Enter it and click the 'Change Repo' button. Your repo must be based on one of our templates."
3. "For the changes to take effect, you must submit a new revision. The project in the newly linked repository must have a passing GDS action. Click on the 'Submit a new revision' button to automatically fetch the latest build."

The guide also notes that after completing these steps, the new repository should be the one submitted, and documentation should be updated so others can learn from the design.

Applied to BINNER: the project currently registered on `ttgf26d` is the Wokwi-based tile `tt_um_wokwi_476390545349040129` ("TT Workshop 8 bit LSFR", sourced from `github.com/Parv-B/tt-8-bit-lfsr`, re-verified above). To register this repo (`Parv-B/tt-binner`) instead, the owner must: (1) go to that project's page on `app.tinytapeout.com`, click **Change**; (2) enter `https://github.com/Parv-B/tt-binner`, click **Change Repo**; (3) ensure `tt-binner`'s `gds` GitHub Action is green (re-verified above at commit `908c9e1` — it is), then click **Submit a new revision**.

## Local hardening procedure — and why this project doesn't use it

Quoted / summarized from **https://tinytapeout.com/guides/local-hardening/** (fetched 2026-09-29, S19):

**Prerequisites:** Python 3.11+ and Docker (or a compatible container engine), or `uv` for older Python versions.

**Steps:**
1. Clone support tools: `git clone https://github.com/TinyTapeout/tt-support-tools tt`
2. Create and activate a Python virtualenv (venv or uv), then `pip install -r tt/requirements.txt`
3. Configure PDK environment variables (example given for SKY130: `PDK_ROOT`, `PDK=sky130A`, `LIBRELANE_TAG=3.0.3`)
4. `pip install librelane==$LIBRELANE_TAG`
5. `./tt/tt_tool.py --create-user-config`
6. `./tt/tt_tool.py --harden`
7. `./tt/tt_tool.py --print-warnings`

Notes from the guide: IHP projects need `--ihp`, GF180MCU projects need `--gf`; macOS users additionally need `brew install libpng qhull cairo`; the whole process takes roughly 10 minutes.

**This project does not run this locally.** The owner's machine has no Docker and no Nix installed, so BINNER runs the equivalent hardening flow exclusively via the repo-owned GitHub Actions workflows (`.github/workflows/gds.yaml`, which pulls in `TinyTapeout/tt-gds-action@ttgf26c`, LibreLane `3.0.14` by default — re-verified above). This is a deliberate owner decision made **2026-09-29**, not a gap: every hardening attempt in this repo's history (baseline `568ef71`, first real attempt `4673f5b`, and the successful fix `908c9e1`) was hardened exclusively through CI, and all are independently re-verified above via the GitHub Actions API.

---

## Summary of what could not be re-verified today

See the per-row "not re-verified" markers above for full detail and reasoning. In short, the following categories were **not** re-checked against a primary source in this pass (all are unchanged carry-overs from the prior planning research, flagged here rather than silently presented as fresh):

- Owner's tile numeric "address" (e.g. 581) — no address field surfaced anywhere reachable without rendering the app's JS SPA.
- Tile physical dimensions (346.64 x 160.72 um) and standard-cell site dimensions (`GF018hv5v_mcu_sc7`, 0.56 x 3.92 um).
- `mux2_1` in `drc_exclude.cells` — actively searched for and **not found** in TinyTapeout tooling repos; may live in the PDK repo itself.
- Individual cell port lists (`inv_1`, `nand2_1`, `nor2_1`, `mux2_2`, `dffrnq_1`, `dlyd_1`, `buf_1`) and their typical-corner delay numbers.
- Whether `RSZ_DONT_TOUCH_RX` is specifically exempted from the CTS step (existence and general resizer usage confirmed; the CTS-exemption detail was not traced).
- Whether the two prior ring-oscillator project repos actually use a `notouch_` naming convention in their RTL (repo existence confirmed; RTL content not diffed).
- Multiplexer 8x20 grid geometry, and whether `ena`/power-gate-enable are driven from literally the same `l_ena` net (signal existence confirmed; wiring not traced).
- Unselected-mux-input tie-off / output-disconnect / "no output registers in mux path" claims.
- GF chip-on-board carrier's fixed AP2112K-3.3 LDO / 0805-jumper claim.
- `clock_project_PWM` max ~125MHz rule, hardware SPI0 pin mapping (`ui_in[0..2]`/`uo_out[3]`), and the GF0p2 factory-test 188MHz claim.
- Docs image size limits (<512kB/image, <1MB total) — not present on the FAQ page fetched.
- The precise ~42.9k → ~32.8k um² area-reduction numbers from the RTL v0.1 → v0.2 fix (yosys-estimate figures, not recomputed this pass; real measured area is confirmed **not yet available** anywhere in the repo tree, pending `tools/metrics_summary.py`).
