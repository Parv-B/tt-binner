/*
 * BINNER ring oscillator.
 *
 * Copyright (c) 2026 Parv Bhadra
 * SPDX-License-Identifier: Apache-2.0
 *
 * One gated ring of N inverting stages (N odd), built only from hand-instantiated
 * GF180MCU standard cells. All instances and loop nets contain "notouch_" so the
 * resizer leaves them alone (RSZ_DONT_TOUCH_RX in src/config.json).
 *
 * KIND 0 (INV) : stage 0 = NAND2(loop, en); stages 1..N-1 = INV_1
 * KIND 1 (NAND): every stage = NAND2(A1 = loop, A2 = en)
 * KIND 2 (NOR) : every stage = NOR2 (A1 = loop, A2 = en_b)
 * KIND 3 (FO4) : as INV, and every stage output also drives 3 dummy INV_1 loads
 *
 * When en = 0 every node is at a static, known level (NAND/INV: stage 0 high,
 * then alternating; NOR: all stage outputs low), so a disabled ring can never
 * oscillate, float or produce X in zero-delay gate-level simulation.
 *
 * The output is taken through one INV_1 tap cell that is identical for every
 * ring, so the output mux loads every ring the same way.
 *
 * Under `BINNER_BEHAV (RTL simulation only), the cell structure is replaced by a
 * behavioural oscillator whose half-period comes from the plusarg
 * +RING<IDX>_HP_FS=<femtoseconds>. This lets the virtual demo board inject
 * die-to-die and within-die variation per simulated chip.
 */

`default_nettype none
`include "binner_cells.vh"

module binner_ring #(
    parameter integer N    = 25,  // number of inverting stages (odd)
    parameter integer KIND = 0,   // 0 INV, 1 NAND, 2 NOR, 3 FO4
    parameter integer IDX  = 0    // source index (for simulation plusargs only)
) (
    input  wire en,   // 1 = oscillate
    output wire out   // ring output (through tap cell)
);

`ifdef BINNER_BEHAV
  // ---------------------------------------------------------------------------
  // Behavioural model (RTL simulation only; never synthesised).
  // ---------------------------------------------------------------------------
  reg     osc;
  integer hp_fs;
  reg [8*16-1:0] argname;
  initial begin
    // Default: 25-stage ring at ~200 MHz nominal (2.5 ns half period).
    hp_fs = 2500000 + IDX * 1000;
    $sformat(argname, "RING%0d_HP_FS=%%d", IDX);
    if ($value$plusargs(argname, hp_fs)) ;
    osc = 1'b0;
    forever begin
      wait (en === 1'b1);
      #(hp_fs * 1.0e-6);  // hp_fs femtoseconds, in ns time units
      if (en === 1'b1) osc = ~osc;
      else osc = 1'b0;
    end
  end
  assign out = ~osc;
  wire _unused_n = &{1'b0, N[0], KIND[0]};
`else
  // ---------------------------------------------------------------------------
  // Physical ring: hand-instantiated cells only.
  // ---------------------------------------------------------------------------
  /* verilator lint_off UNOPTFLAT */  // the ring loop is intentional
  (* keep *) wire [N-1:0] ring_notouch_;   // stage outputs
  wire                    en_b_notouch_;

  /* verilator lint_off PINMISSING */
  genvar i;
  generate
    if (KIND == 2) begin : g_enb
      (* keep *) `BINNER_INV1 enb_notouch_ (.I(en), .ZN(en_b_notouch_));
    end else begin : g_noenb
      assign en_b_notouch_ = 1'b0;
      wire _unused_enb = en_b_notouch_;
    end
    for (i = 0; i < N; i = i + 1) begin : g_stg
      wire prev = (i == 0) ? ring_notouch_[N-1] : ring_notouch_[(i == 0) ? 0 : i-1];
      if (KIND == 1) begin : g_nand
        (* keep *) `BINNER_NAND2 stg_notouch_ (.A1(prev), .A2(en), .ZN(ring_notouch_[i]));
      end else if (KIND == 2) begin : g_nor
        (* keep *) `BINNER_NOR2 stg_notouch_ (.A1(prev), .A2(en_b_notouch_), .ZN(ring_notouch_[i]));
      end else begin : g_inv
        if (i == 0) begin : g_gate
          (* keep *) `BINNER_NAND2 stg_notouch_ (.A1(prev), .A2(en), .ZN(ring_notouch_[i]));
        end else begin : g_plain
          (* keep *) `BINNER_INV1 stg_notouch_ (.I(prev), .ZN(ring_notouch_[i]));
        end
        if (KIND == 3) begin : g_fo4
          // Three dummy loads per stage: with the next stage this is fan-out 4.
          /* verilator lint_off UNUSEDSIGNAL */  // dummy loads: outputs unused by design
          (* keep *) wire [2:0] ld_notouch_;
          /* verilator lint_on UNUSEDSIGNAL */
          (* keep *) `BINNER_INV1 ld0_notouch_ (.I(ring_notouch_[i]), .ZN(ld_notouch_[0]));
          (* keep *) `BINNER_INV1 ld1_notouch_ (.I(ring_notouch_[i]), .ZN(ld_notouch_[1]));
          (* keep *) `BINNER_INV1 ld2_notouch_ (.I(ring_notouch_[i]), .ZN(ld_notouch_[2]));
        end
      end
    end
  endgenerate

  (* keep *) `BINNER_INV1 tap_notouch_ (.I(ring_notouch_[N-1]), .ZN(out));
  /* verilator lint_on PINMISSING */
  /* verilator lint_on UNOPTFLAT */
  wire _unused_idx = &{1'b0, IDX[0]};
`endif

endmodule
