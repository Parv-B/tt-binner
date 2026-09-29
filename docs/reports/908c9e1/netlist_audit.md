# BINNER netlist structural audit

**Overall: PASS**

## tt_submission powered netlist

- Netlist: `ci_artifacts\908c9e1\tt_submission\tt_submission\tt_um_parv_b_binner.v`
- Module: `tt_um_parv_b_binner`
- Instances parsed: 3335
- Result: **PASS** (0 FAIL, 0 WARN)

No findings -- structure matches src/binner_ring.v, src/binner_dchain.v, src/binner_fmax.v exactly.

## GDS_logs final nl.v (unpowered)

- Netlist: `ci_artifacts\908c9e1\GDS_logs\runs\wokwi\final\nl\tt_um_parv_b_binner.nl.v`
- Module: `tt_um_parv_b_binner`
- Instances parsed: 3335
- Result: **PASS** (0 FAIL, 0 WARN)

No findings -- structure matches src/binner_ring.v, src/binner_dchain.v, src/binner_fmax.v exactly.

## GDS_logs final pnl.v (powered)

- Netlist: `ci_artifacts\908c9e1\GDS_logs\runs\wokwi\final\pnl\tt_um_parv_b_binner.pnl.v`
- Module: `tt_um_parv_b_binner`
- Instances parsed: 3335
- Result: **PASS** (0 FAIL, 0 WARN)

No findings -- structure matches src/binner_ring.v, src/binner_dchain.v, src/binner_fmax.v exactly.

## Checks performed

- Stage census (missing/extra) for each of the 16 PUF/INV rings (N=25), the NAND ring (N=25), the NOR ring (N=25), the FO4 ring (N=13).
- Exact cell type/drive strength for every notouch_ instance (resize detection).
- Ring loop connectivity (stage i driven by stage (i-1) mod N, tap driven by stage N-1).
- Enable wiring: NAND ring en_buf_notouch_ fans out to exactly all N stage A2 pins; NOR ring en_b_notouch_ likewise.
- FO4 dummy loads (3 per stage, each driven by that stage's own output).
- Delay-chain stage census/connectivity, 8:1 tap-mux tree wiring, feedback loop closure.
- Fmax fcap_keep_[k].D driven by exactly the delay-chain stage at TAPPOS[k] = [3, 4, 5, 6, 8, 10, 12, 14] (these flops are intentionally NOT notouch_; only checked for D-pin wiring and cell type, not fanout on CLK/RN).
- Global scan: every notouch_-named net's driver is itself a notouch_-classified instance (catches any inserted buffer/resize on a protected net).
