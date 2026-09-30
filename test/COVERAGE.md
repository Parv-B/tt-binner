# BINNER test coverage map

Maps `docs/SPEC.md` v0.2 items, register fields and FSM states to the tests
that exercise them. Everything here is derived from the SPEC (the contract),
not from `src/` — see `test/binner_tb.py`'s module docstring. Register/bit
names below match `binner_tb.py`.

Test files run under `make` (RTL, `BINNER_BEHAV`) unless marked otherwise.
`@rtl_only` tests are skipped under `GATES=yes`. `@gl_safe` tests run in
both RTL and `GATES=yes` (they never enable a ring). `make struct` tests
(`test_struct.py`) are a separate, developer-only target — see item 9.

## 1. Pins (SPEC §1)

| Item | Test(s) |
|---|---|
| SPI pin mapping (CS_N/SCK/MOSI/MISO), MISO=0 when CS_N high | `test_spi.py::test_spi_miso_zero_when_cs_high` |
| uo_out bit assignment (LFSR/CNTA/CNTB/MISO/BUSY/FFAIL/DONE/FMAX_ARMED) | `test_reset.py::test_reset_values` (`UO_RESET` derivation), `test_lfsr.py::test_lfsr_free_run_pin`, `test_meas.py::test_done_busy_timing`, `test_fmax.py::test_fmax_arming_pin` |
| uio debug byte / UIOOE, reset = inputs | `test_spi.py::test_debug_byte_and_armed_pin`, `test_reset.py::check_outputs` (every reset test) |
| Pin-strap mode: bank/sel source select, B = 8+sel | `test_pinmode.py::test_pinmode_source_select` |
| Pin-strap mode: no SPI needed, SPI still works | `test_pinmode.py::test_pinmode_spi_still_works` |

## 2. Reset and clocking (SPEC §2)

| Item | Test(s) |
|---|---|
| Async assert / sync (2-flop) de-assert, every flop resets | `test_reset.py::test_reset_outputs_during_reset` (outputs defined the instant `rst_n` drops, no clock edge needed) |
| All registers at SPEC reset values after reset | `test_reset.py::test_reset_values`, `check_all_reset_values` (walks `RW_REGS` + `RO_RESET` + `MISC`) |
| Rings off, uio inputs after reset | `test_reset.py::test_rings_off_after_reset` (hierarchical `en` probe) |
| Reset aborts a running measurement / mid-SPI transaction | `test_reset.py::test_reset_mid_measurement`, `test_reset_mid_spi` |
| f_SCK ≤ f_clk/8 (spec limit), works at /8, /10, /12, /16 | `test_spi.py::test_spi_sck_rates` (also swept over 4 clk periods 1..50 MHz-ish) |
| Below-spec SCK rates (informational only) | `test_spi.py::test_spi_below_clk8_characterisation` |
| 1 Hz .. 20 MHz normal-operation clock range | Exercised indirectly: `test_spi_sck_rates` sweeps clk 1/20/37.3/1000 ns (1 MHz–50 MHz region incl. the 20 MHz boundary); RTL tests never assume a fixed `clk` (period is a `TB.set_clock()` parameter throughout). No test sweeps all the way down to 1 Hz (would cost real sim time for no additional RTL coverage — the design has no clock-rate-dependent logic below 20 MHz). |

## 3. SPI protocol (SPEC §3)

| Item | Test(s) |
|---|---|
| Write auto-increment | `test_spi.py::test_spi_burst` |
| Read auto-increment, no read side effects | `test_spi.py::test_spi_burst`, `test_spi_reads_no_side_effects` |
| MISO = 0 during command byte | `TB.rd()` asserts this on every read in every test |
| Unmapped reads 0x00, writes ignored | `test_spi.py::test_spi_ro_and_unmapped_ignore_writes` |
| CS_N abort mid-byte: write has no effect, read is clean | `test_spi.py::test_spi_abort_mid_byte` |
| CS_N abort mid-burst (2nd data byte) | `test_spi.py::test_spi_abort_mid_byte` (final case) |

## 4. Register map v0.2 (SPEC §4)

| Register | Test(s) |
|---|---|
| ID0/ID1/VER (0x00-0x02) reset values, RO | `test_reset.py`, `test.py::test_smoke`, `test_struct.py::test_struct_smoke` |
| CTRL (0x03) all 7 bits, RW, bit7 always 0 | `test_spi.py::test_spi_rw_registers` (mask 0x7F) |
| SRCA/SRCB (0x04/0x05), DTAP/DBG subfields | `test_spi.py::test_spi_rw_registers`, `test_ring.py` (DTAP), `test_spi.py::test_debug_byte_and_armed_pin` (DBG) |
| TIMING (0x06): GEXP/PINDIV | `test_spi.py::test_spi_rw_registers`, `test_meas.py::test_clk2_known_answer` (GEXP sweep 0..15), `test_meas.py::test_free_mode_clk2` (PINDIV sweep) |
| CMD (0x07) WO, reads 0, one-cycle pulses | `test_spi.py::test_spi_cmd_reads_zero`, `test_meas.py::test_start_while_busy_ignored` |
| STATUS (0x08) all 7 bits + ARMED (bit7) | see FSM/status table below |
| CNTA/CNTB (0x09-0x0C) static-after-DONE, live in FREE | `test_meas.py::test_counters_static_after_done`, `test_free_mode_clk2` |
| LFSR_L/H (0x0D/0x0E) reset 0xACE1, live state | `test_lfsr.py` (all tests) |
| FFAIL (0x0F) sticky per-tap | `test_fmax.py` |
| FCAP (0x10) raw capture (debug) | read as part of `test_spi.py::test_spi_ro_and_unmapped_ignore_writes` reset-value sweep; not independently driven (no RTL hook to force a capture mismatch without a real Fmax fault, which `test_fmax.py` covers via FFAIL instead) |
| MISC (0x11) all 8 bits | `test_reset.py::check_all_reset_values` (reset), `test_spi.py::test_debug_byte_and_armed_pin` (DBG sel=6), `test_meas.py::test_free_mode_clk2` (cnt_en via live counter read) |
| Unmapped 0x12-0x7F read 0, ignore writes | `test_spi.py::test_spi_ro_and_unmapped_ignore_writes` (full-range burst write + full-range readback) |
| Register readback (freely readable for full config) | `test_spi.py::test_spi_rw_registers` |

## 5. Sources and measurement (SPEC §5)

| Item | Test(s) |
|---|---|
| Ring oscillates iff `ena & (CTRL.RUN|PINMODE)` and selected | `test_ring.py::test_ring_enable_sweep`, `test_ring_ena_gates_everything` (hierarchical `en` probe of all 20 sources) |
| At most two rings run at a time | `test_ring.py::test_ring_enable_sweep` (`sum(en) <= 2` assertion on every combo) |
| Sources 0-15 (INV rings) | `test_ring.py::test_ring_oscillation_functional` (loops idx 0..18) |
| Source 16 (NAND ring), enable buffer | `test_ring.py::test_ring_oscillation_functional`; structurally: `test_struct.py::test_ring_periods_all_kinds` — **see Finding 1, FAILS** |
| Source 17 (NOR ring) | `test_ring.py::test_ring_oscillation_functional` |
| Source 18 (FO4 ring, N_FO4=13 stages) | `test_ring.py::test_ring_oscillation_functional`; structurally: `test_struct.py::test_ring_periods_all_kinds` |
| Source 19 (delay-chain ring), all 8 DTAP values | `test_ring.py::test_dchain_ring_taps`; structurally: `test_struct.py::test_dchain_ring_tap_periods` — **see Finding 2, FAILS at DTAP=4** |
| Source 20 (clk/2 known answer) | `test_meas.py::test_clk2_known_answer` (GEXP 0..15) |
| Sources 21-31 (constant 0 / dead) | `test_meas.py::test_dead_sources` |
| Both channels simultaneously, different rings | `test_ring.py::test_ring_at_most_two_with_both_channels_running` |
| CNT = gate/2 ± 1 for clk/2 (known answer) | `test_meas.py::test_clk2_known_answer` |
| SEEN_x semantics (dead/slow source) | `test_meas.py::test_dead_sources`, `test_clk2_known_answer` |
| OVF_x (16-bit counter wrap) | `test_meas.py::test_overflow` (rtl_only, fast ring + wide gate) |
| TIMEOUT (ack stuck > 63 cycles, FREE mode) | `test_meas.py::test_timeout_free_mode` |
| BUSY/DONE timing (gate + ~10 cycles) | `test_meas.py::test_done_busy_timing` |
| CNTA/CNTB static from DONE to next START/CLEAR | `test_meas.py::test_counters_static_after_done` |
| CLEAR aborts a running measurement | `test_meas.py::test_clear_during_run` |
| CLEAR when idle | `test_meas.py::test_clear_during_run` |
| START while BUSY is ignored (not queued) | `test_meas.py::test_start_while_busy_ignored` |
| START clears previous STATUS (no stale SEEN/DONE) | `test_meas.py::test_start_clears_previous_status` |
| FREE mode: counters run continuously, uo_out[1]/[2] toggle at source/2^(PINDIV+1) | `test_meas.py::test_free_mode_clk2` |

## 6. Fmax checker (SPEC §6)

| Item | Test(s) |
|---|---|
| 8 taps at stages 3,4,5,6,8,10,12,14, checked simultaneously | `test_fmax.py::test_fmax_tap_thresholds` (rtl_only, sweeps clk across every tap boundary) |
| armed = CTRL.FMAX_EN & sync(ui_in[7]) & !PINMODE | `test_fmax.py::test_fmax_arming_pin` |
| FFAIL sticky until FMAX_CLEAR | `test_fmax.py::test_fmax_clear` |
| FMAX_INV=1 polarity self-test (every tap fails) | `test_fmax.py::test_fmax_polarity_inv` |
| Disarmed: no FFAIL accumulation even with fast/glitchy clk retuning | `test_fmax.py::test_fmax_disarmed_accumulates_nothing` |
| Tap delay model matches SPEC §8 plusarg defaults | `test_fmax.py::test_fmax_tap_delay_matches_dstg_model` |
| Source 19 as ring gives a direct stage-delay measurement | `test_ring.py::test_dchain_ring_taps` (RTL, behavioural); `test_struct.py::test_dchain_ring_tap_periods` (structural, real cell delays) |

## 7. LFSR (SPEC §7)

| Item | Test(s) |
|---|---|
| Independent Python model of the SPEC polynomial (x^16+x^15+x^13+x^4+1, de Bruijn) | `binner_tb.py::lfsr_next` / `lfsr_advance` / `lfsr_distance` |
| Period 65536, single cycle, no lock-up (exhaustive, all 65536 states) | `test_lfsr.py::prove_lfsr_period` — runs both as `test_lfsr_model_pytest` (plain `pytest`) and `test_lfsr_model_period` (inside the cocotb regression, so it's part of `make` too) |
| Underlying plain LFSR (no de Bruijn) has period 65535 and one lock-up state (0x0000), confirming the polynomial is primitive | `test_lfsr.py::prove_lfsr_period` (part 3) |
| De Bruijn splice 0x8000→0x0000→0x0001 | `test_lfsr.py::prove_lfsr_period` (part 4, model); `test_lfsr_splice_known_answer` (RTL, crosses the splice via composed gated measurements) |
| RTL known-answer: reseed + LFSR_GATED + GEXP=k, all k=0..15 | `test_lfsr.py::test_lfsr_known_answer` |
| RTL known-answer: arbitrary N (binary-decomposed gated advance) | `test_lfsr.py::test_lfsr_arbitrary_advance` |
| N=65535 (one short of full period) | `test_lfsr.py::test_lfsr_splice_known_answer` |
| LFSR_RUN: steps every clk, uo_out[0]=state[15] | `test_lfsr.py::test_lfsr_free_run_pin` |
| Pin-strap mode: LFSR steps every clk | `test_lfsr.py::test_lfsr_pinmode_steps` |
| LFSR_GATED only steps during the RUN window (not idle) | `test_lfsr.py::test_lfsr_gated_only_during_run` |

## 8. Simulation hooks (SPEC §8, RTL only)

| Item | Test(s) |
|---|---|
| `+RING<IDX>_HP_FS` plusarg, default 2.5ns+IDX·1ps | `binner_tb.py::ring_hp_fs` / `ring_freq_hz`, used throughout `test_ring.py` |
| `+DSTG<i>_FS` / `+DCHAIN_OVH_FS` plusargs, defaults 3.4ns/0.6ns | `binner_tb.py::dstg_fs`/`dovh_fs`/`tap_delay_fs`; verified against defaults by `test_fmax.py::test_fmax_tap_delay_matches_dstg_model` |
| GATES=yes keeps all rings disabled | Every ring-touching test is `@rtl_only` (skipped under GATES=yes); every `@gl_safe` test only ever selects source 20 or a dead source — see "GL-safe subset" below |

## 9. Structural verification (`make struct`, developer-only, not run by CI)

`test_struct.py` recompiles `project.v` (+ `binner_ring.v`/`binner_dchain.v`/
`binner_fmax.v`) **without** `-DBINNER_BEHAV` (so the physical, hand-instantiated
cell branches are used) and **without** `-DFUNCTIONAL`, against the real
GF180MCU `gf180mcu_fd_sc_mcu7t5v0` PDK cell models, so every comb/seq arc
carries its real specify-block timing (1.0/1.0 ns for every cell used here —
verified directly against the library source, not assumed). Icarus ignores
specify-block path delays by default; `-gspecify` (set in `test/Makefile`,
`STRUCT_MODE` branch) is required or the hand-instantiated ring loops become
zero-delay combinational loops that never advance simulated time.

This is the only place BINNER's actual cell structure (not the behavioural
stand-in) is exercised in simulation.

| Item | Test |
|---|---|
| Register file / SPI / ID identical in structural mode | `test_struct_smoke` |
| Every ring's oscillation period = 2·N·1ns for its real stage count (N=25 INV/NAND/NOR, N=13 FO4) | `test_ring_periods_all_kinds` — **FAILS for source 16 (NAND ring), see Finding 1** |
| NAND ring's `en_buf_notouch_` buffer (RSZ-3006 fix) adds nothing to the loop period | `test_ring_periods_all_kinds` (compares ring16 period to ring0) — cannot pass while Finding 1 stands |
| Disabled ring is resolvable (no X/Z), static | `test_ring_disabled_static_no_x` |
| Delay-chain ring period per DTAP (real DLYD_1/MUX2_2/NAND2_1 delays) | `test_dchain_ring_tap_periods` — **FAILS for DTAP=4, see Finding 2** |

Run with `make struct` (`test/Makefile`; PDK models loaded from `$PDK_ROOT`).
Takes real GF180MCU cell instantiation, so it is slower to elaborate than RTL
mode but the tests themselves run in a few seconds of wall time.

## GL-safe subset (works under `GATES=yes` semantics)

Every test decorated `@gl_safe` in `binner_tb.py` runs identically under
`make` and `make GATES=yes` (skips are controlled by the `GL` flag, which is
`True` when `GATES=yes` or the `GL_TEST` plusarg is set). These tests never
select a ring source and never set `CTRL.RUN` with a ring-carrying SRCA/SRCB
(the `safe_ctrl()` helper in `test_spi.py` strips `CTRL.RUN` under `GL`), so
no ring ever runs in a zero-delay gate-level simulation (which would hang).
Covered under GL semantics: all of `test_reset.py`, `test_spi.py`, most of
`test_lfsr.py` (LFSR gating uses source 20), most of `test_meas.py` (clk/2 and
dead sources only), `test_pinmode.py::test_pinmode_spi_still_works`, and all
of `test_fmax.py` except the RTL-only tap-threshold sweep. `test_ring.py` and
the ring-frequency parts of `test_meas.py`/`test_pinmode.py` are `@rtl_only`
and skip entirely under `GATES=yes`.

This worktree has no `gate_level_netlist.v` (it is copied in only by the GDS
CI workflow after hardening — `test/Makefile` comment, line ~73), so
`GATES=yes` itself could not be executed here; the GL-safe design was verified
by inspection of the `gl_safe`/`rtl_only`/`GL` gating logic in `binner_tb.py`
and by confirming (via `git grep`) that no `@gl_safe` test ever sets
`CTRL.RUN` on a ring-carrying source select.

## RTL findings (structural mode only — see FINDINGS.md-style detail in the
verification report; summarised here for traceability)

1. **Source 16 (NAND ring) oscillates with the wrong period in structural
   simulation.** `make struct`'s `test_struct.test_ring_periods_all_kinds`
   measures 2.00 ns instead of the expected 50.00 ns (25 stages × 2 × 1.0 ns).
   Direct hierarchical probing of `u_ring_nand.ring_notouch_` (binner_ring.v,
   `KIND==1` branch, instantiated at `project.v:145`) shows all 25 stage
   outputs toggling in perfect lockstep every 1 ns — i.e. behaving as a single
   inverting stage, not a 25-stage traveling-wave ring. `binner_ring.v`'s
   `KIND==0` ring (source 0/1, only stage 0 gated by `en`/`en_buf`, ungated
   `INV_1` for stages 1..24) measures the textbook-correct 50.00 ns in the
   same run, so per-stage `prev` wiring (`binner_ring.v:90`) is not at fault
   in general — the defect is specific to `KIND==1`, where **every** stage is
   a `NAND2` gated by the shared `en_buf_notouch_` net (`binner_ring.v:92`).
   Deterministic and 100% reproducible across repeated `make struct` runs
   (identical period every time, no randomness). Root cause not fully
   isolated (candidates: a genuine coupling introduced by 25 NAND2 instances
   sharing one specify-timed net vs. an Icarus specify/X-propagation
   limitation at this scale) — flagged for `src/` owner + a second simulator
   (or gate-level LVS) to confirm before trusting this ring on silicon.
   Exposing test kept as-is (already correctly named/written); do not
   "fix" it by loosening tolerance.

2. **Source 19 (delay-chain ring), DTAP=4, measures the wrong period only
   when tuned live from a running ring.** `make struct`'s
   `test_struct.test_dchain_ring_tap_periods` measures 9.00 ns instead of the
   expected 26.00 ns for DTAP=4 (stage count 8); DTAP=0..3 all pass exactly.
   Direct probing shows the underlying hardware is not broken: (a) enabling
   the ring cold, directly at DTAP=4, gives a clean, glitch-free 26.0 ns
   period every cycle (16/16 edges, zero jitter); (b) manually reproducing a
   live DTAP=3→4 retune (matching `enable_only()`'s pattern of never clearing
   `CTRL.RUN` between taps) also settled cleanly at 26.0 ns in isolation — so
   the anomaly is sensitive to the *exact* accumulated simulation-time phase
   at which the asynchronous tap-select mux (`binner_dchain.v:113-121`) is
   switched relative to the free-running ring's own oscillation, which the
   real test reaches only after three prior SPI-timed measurements (DTAP
   0,1,2,3) elapse first. This is consistent with a genuine asynchronous
   mode-locking hazard in a combinational-mux ring oscillator (the physical
   ring can, at an unlucky retune phase, lock into an unintended shorter loop
   through the tap tree and never self-correct) rather than a wiring or
   test-measurement bug — and is fully deterministic (identical 9.00 ns each
   `make struct` run). `docs/SPEC.md` §5/§6 does not require disabling the
   ring (`CTRL.RUN=0`) before changing `DTAP` (`SRCA[7:5]`); if this hazard is
   real on silicon, live DTAP sweeps for Fmax/delay-chain characterisation
   would need that as a documented precondition. Exposing test kept as-is.

Both findings were produced using the project's own `make struct` target plus
short-lived hierarchical-signal debug probes (`test/zz_debug_probe.py`,
removed after use — not part of the committed test suite) driven through the
same `binner_tb.TB` driver as every other test, so the repro steps are just
`make struct` (deterministic, no seed dependence for either failure).
