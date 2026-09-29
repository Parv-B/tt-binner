# BINNER LibreLane metrics summary

Source: `ci_artifacts\9692913\tt_submission\tt_submission\stats\metrics.csv`

**Utilization: 81.98% (OVER TARGET, target <= 60%)**

| metric | value |
|---|---|
| instance count | 3334 |
| instance area (um^2) | 51967 |
| stdcell area (um^2) | 42604.4 |
| core area (um^2) | 51967 |
| die area (um^2) | 55712 |
| utilization (instance/core) | 81.98% |
| utilization (stdcell/core) | 81.98% |
| placement displacement total/mean/max (um) | 0 / 0 / 0 |

## Cell class breakdown

| class | count | area (um^2) |
|---|---|---|
| buffer | 27 | 1268.83 |
| clock_buffer | 32 | 1286.39 |
| endcap_cell | 78 | 342.45 |
| fill_cell | 1197 | 9362.53 |
| inverter | 528 | 4667 |
| multi_input_combinational_cell | 789 | 16942.60 |
| sequential_cell | 170 | 12828.70 |
| tap_cell | 348 | 1527.86 |
| tie_cell | 3 | 26.34 |
| timing_repair_buffer | 162 | 3714.28 |

## Timing WNS/TNS and slew/fanout violations per corner

| corner | setup WNS (ns) | setup TNS (ns) | hold WNS (ns) | hold TNS (ns) | slew violations | fanout violations |
|---|---|---|---|---|---|---|
| max_ff_n40C_3v60 | 0.000 | 0.000 | 0 | 0.000 | 0 | 3 |
| max_ss_125C_3v00 | 0.000 | 0.000 | 0 | 0.000 | 348 | 3 |
| max_tt_025C_3v30 | 0.000 | 0.000 | 0 | 0.000 | 11 | 3 |
| min_ff_n40C_3v60 | 0.000 | 0.000 | 0 | 0.000 | 0 | 3 |
| min_ss_125C_3v00 | 0.000 | 0.000 | 0 | 0.000 | 241 | 3 |
| min_tt_025C_3v30 | 0.000 | 0.000 | 0 | 0.000 | 0 | 3 |
| nom_ff_n40C_3v60 | 0.000 | 0.000 | 0 | 0.000 | 0 | 3 |
| nom_ss_125C_3v00 | 0.000 | 0.000 | 0 | 0.000 | 263 | 3 |
| nom_tt_025C_3v30 | 0.000 | 0.000 | 0 | 0.000 | 0 | 3 |

Overall (worst across corners): setup WNS 0.000 ns, setup TNS 0.000 ns, hold WNS 0 ns, hold TNS 0.000 ns, 348 slew violations, 3 fanout violations.

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

Detailed-routing DRC error count by repair iteration: 0=383, 1=101, 2=96, 3=0.

## Flags

| category | detail |
|---|---|
| FAIL vs. plan target | utilization 81.98% (stdcell area 42604.4 um^2 / core area 51967 um^2) exceeds the project's <=60% design target. The plan's pre-route yosys estimate was ~32.8k um^2; the real post-route stdcell area is 42604.4 um^2 -- 1.3x the estimate. |
| fanout | 3 max-fanout violation(s), present in every corner (structural, not corner-dependent) -- metrics.csv does not name the offending net(s). |
| lint (informational) | 1 lint warning(s) in the synthesised design. |
