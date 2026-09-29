# BINNER LibreLane metrics summary

Source: `ci_artifacts\908c9e1\tt_submission\tt_submission\stats\metrics.csv`

**Utilization: 81.68% (OVER TARGET, target <= 60%)**

| metric | value |
|---|---|
| instance count | 3335 |
| instance area (um^2) | 51967 |
| stdcell area (um^2) | 42446.4 |
| core area (um^2) | 51967 |
| die area (um^2) | 55712 |
| utilization (instance/core) | 81.68% |
| utilization (stdcell/core) | 81.68% |
| placement displacement total/mean/max (um) | 257.600 / 0.120 / 15.680 |

## Cell class breakdown

| class | count | area (um^2) |
|---|---|---|
| buffer | 27 | 1268.83 |
| clock_buffer | 32 | 1286.39 |
| endcap_cell | 78 | 342.45 |
| fill_cell | 1204 | 9520.58 |
| inverter | 528 | 4671.39 |
| multi_input_combinational_cell | 789 | 17047.90 |
| sequential_cell | 170 | 12846.30 |
| tap_cell | 348 | 1527.86 |
| tie_cell | 3 | 26.34 |
| timing_repair_buffer | 156 | 3428.90 |

## Timing WNS/TNS and slew/fanout violations per corner

| corner | setup WNS (ns) | setup TNS (ns) | hold WNS (ns) | hold TNS (ns) | slew violations | fanout violations |
|---|---|---|---|---|---|---|
| max_ff_n40C_3v60 | 0.000 | 0.000 | 0 | 0.000 | 0 | 3 |
| max_ss_125C_3v00 | -2.848 | -48.290 | 0 | 0.000 | 317 | 3 |
| max_tt_025C_3v30 | 0.000 | 0.000 | 0 | 0.000 | 0 | 3 |
| min_ff_n40C_3v60 | 0.000 | 0.000 | 0 | 0.000 | 0 | 3 |
| min_ss_125C_3v00 | -1.658 | -21.173 | 0 | 0.000 | 181 | 3 |
| min_tt_025C_3v30 | 0.000 | 0.000 | 0 | 0.000 | 0 | 3 |
| nom_ff_n40C_3v60 | 0.000 | 0.000 | 0 | 0.000 | 0 | 3 |
| nom_ss_125C_3v00 | -2.193 | -32.895 | 0 | 0.000 | 246 | 3 |
| nom_tt_025C_3v30 | 0.000 | 0.000 | 0 | 0.000 | 0 | 3 |

Overall (worst across corners): setup WNS -2.848 ns, setup TNS -48.290 ns, hold WNS 0 ns, hold TNS 0.000 ns, 317 slew violations, 3 fanout violations.

## Antenna / DRC / lint

| metric | value |
|---|---|
| antenna_violating_nets | 0 |
| antenna_violating_pins | 0 |
| route_antenna_violation_count | 0 |
| antenna_diodes_count | 0 |
| route_drc_errors_final | 0 |
| magic_drc_error_count | 0 |
| lint_error_count | 0 |
| lint_warning_count | 1 |
| lint_timing_construct_count | 0 |
| inferred_latch_count | 0 |
| unmapped_cell_count | 0 |

Detailed-routing DRC error count by repair iteration: 0=348, 1=119, 2=107, 3=0.

## Flags

| category | detail |
|---|---|
| FAIL vs. plan target | utilization 81.68% (stdcell area 42446.4 um^2 / core area 51967 um^2) exceeds the project's <=60% design target. The plan's pre-route yosys estimate was ~32.8k um^2; the real post-route stdcell area is 42446.4 um^2 -- 1.3x the estimate. |
| setup timing | corner max_ss_125C_3v00: setup WNS -2.848 ns, TNS -48.290 ns (317 slew, 3 fanout violations) |
| setup timing | corner min_ss_125C_3v00: setup WNS -1.658 ns, TNS -21.173 ns (181 slew, 3 fanout violations) |
| setup timing | corner nom_ss_125C_3v00: setup WNS -2.193 ns, TNS -32.895 ns (246 slew, 3 fanout violations) |
| fanout | 3 max-fanout violation(s), present in every corner (structural, not corner-dependent) -- metrics.csv does not name the offending net(s). |
| lint (informational) | 1 lint warning(s) in the synthesised design. |
