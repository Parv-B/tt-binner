/*
 * BINNER tapped delay chain (Fmax path and delay-line ring).
 *
 * Copyright (c) 2026 Parv Bhadra
 * SPDX-License-Identifier: Apache-2.0
 *
 *   launch --+
 *            |mux notouch   NS x DLYD_1 (non-inverting)
 *   fb ------+----> d[0] -> d[1] -> ... -> d[NS]
 *                               taps: d[T0] .. d[T7]
 *
 * Fmax mode (ring_mode = 0): d[0] follows the launch flop. The eight taps go
 * to capture flops in binner_fmax, clocked by clk. A tap fails when its path
 * delay exceeds the clock period.
 *
 * Ring mode (ring_mode = 1): an 8:1 tap mux selects one tap and a NAND2
 * (A2 = ring_en) inverts it back into d[0]. The loop oscillates with period
 * 2 * (t_mux_in + t_chain(tap) + t_tapmux + t_nand). Measuring this ring for
 * every tap gives the per-stage delay directly (slope versus tap position),
 * independently of the Fmax measurement.
 *
 * ring_en = 0 forces fb = 1, so the loop is static whenever the ring is not
 * running.
 *
 * Tap positions (stage counts) are fixed by TAPPOS below. See DECISIONS.md
 * (D-FMAX-TAPS) for how they were sized against the demo-board clock range.
 */

`default_nettype none
`include "binner_cells.vh"

module binner_dchain #(
    parameter integer NS = 14
) (
    input  wire       launch,     // from launch flop (clk domain)
    input  wire       ring_mode,  // 0 = Fmax path, 1 = delay-line ring
    input  wire       ring_en,    // ring oscillates when 1 (and ring_mode = 1)
    input  wire [2:0] tap_sel,    // ring-mode tap
    output wire [7:0] taps,       // chain taps to Fmax capture flops
    output wire       ring_out    // ring-mode oscillator output
);

  // Stage count at each tap: 3,4,5,6,8,10,12,14 DLYD_1 stages.
  function integer tappos(input integer k);
    case (k)
      0: tappos = 3;  1: tappos = 4;  2: tappos = 5;  3: tappos = 6;
      4: tappos = 8;  5: tappos = 10; 6: tappos = 12; default: tappos = 14;
    endcase
  endfunction

`ifdef BINNER_BEHAV
  // ---------------------------------------------------------------------------
  // Behavioural model: transport delay per stage from +DSTG<i>_FS (default
  // 3.4 ns), fixed mux/NAND overhead from +DCHAIN_OVH_FS (default 0.6 ns,
  // applied in the input mux).
  // ---------------------------------------------------------------------------
  reg [NS:0] d;
  wire [7:0] tapv;
  integer    dfs [1:NS];
  integer    ovh_fs;
  integer    k, tmp;
  reg [8*16-1:0] argname;
  initial begin
    ovh_fs = 600000;
    if ($value$plusargs("DCHAIN_OVH_FS=%d", ovh_fs)) ;
    for (k = 1; k <= NS; k = k + 1) begin
      tmp = 3400000;
      $sformat(argname, "DSTG%0d_FS=%%d", k);
      if ($value$plusargs(argname, tmp)) ;
      dfs[k] = tmp;
    end
    d = {(NS+1){1'b0}};
  end

  wire tsel = tapv[tap_sel];
  wire fb   = ~(tsel & ring_en);
  wire din  = ring_mode ? fb : launch;

  always @(din) d[0] <= #(ovh_fs * 1.0e-6) din;
  genvar g;
  generate
    for (g = 1; g <= NS; g = g + 1) begin : g_bstg
      always @(d[g-1]) d[g] <= #(dfs[g] * 1.0e-6) d[g-1];
    end
    for (g = 0; g < 8; g = g + 1) begin : g_btap
      assign tapv[g] = d[tappos(g)];
    end
  endgenerate
  assign taps     = tapv;
  assign ring_out = ~fb;
`else
  // ---------------------------------------------------------------------------
  // Physical chain: hand-instantiated cells only.
  // ---------------------------------------------------------------------------
  /* verilator lint_off UNOPTFLAT */  // the ring-mode loop is intentional
  (* keep *) wire [NS:0] dch_notouch_;
  (* keep *) wire [6:0]  tmx_notouch_;   // tap-mux tree nodes
  (* keep *) wire        dfb_notouch_;   // NAND feedback

  /* verilator lint_off PINMISSING */
  (* keep *) `BINNER_MUX2 dmx_notouch_ (.I0(launch), .I1(dfb_notouch_), .S(ring_mode),
                                        .Z(dch_notouch_[0]));
  genvar i;
  generate
    for (i = 1; i <= NS; i = i + 1) begin : g_stg
      (* keep *) `BINNER_DLY dly_notouch_ (.I(dch_notouch_[i-1]), .Z(dch_notouch_[i]));
    end
    for (i = 0; i < 8; i = i + 1) begin : g_tap
      assign taps[i] = dch_notouch_[tappos(i)];
    end
  endgenerate

  // 8:1 tap mux for ring mode.
  (* keep *) `BINNER_MUX2 tm0_notouch_ (.I0(taps[0]), .I1(taps[1]), .S(tap_sel[0]), .Z(tmx_notouch_[0]));
  (* keep *) `BINNER_MUX2 tm1_notouch_ (.I0(taps[2]), .I1(taps[3]), .S(tap_sel[0]), .Z(tmx_notouch_[1]));
  (* keep *) `BINNER_MUX2 tm2_notouch_ (.I0(taps[4]), .I1(taps[5]), .S(tap_sel[0]), .Z(tmx_notouch_[2]));
  (* keep *) `BINNER_MUX2 tm3_notouch_ (.I0(taps[6]), .I1(taps[7]), .S(tap_sel[0]), .Z(tmx_notouch_[3]));
  (* keep *) `BINNER_MUX2 tm4_notouch_ (.I0(tmx_notouch_[0]), .I1(tmx_notouch_[1]), .S(tap_sel[1]), .Z(tmx_notouch_[4]));
  (* keep *) `BINNER_MUX2 tm5_notouch_ (.I0(tmx_notouch_[2]), .I1(tmx_notouch_[3]), .S(tap_sel[1]), .Z(tmx_notouch_[5]));
  (* keep *) `BINNER_MUX2 tm6_notouch_ (.I0(tmx_notouch_[4]), .I1(tmx_notouch_[5]), .S(tap_sel[2]), .Z(tmx_notouch_[6]));
  (* keep *) `BINNER_NAND2 dfbg_notouch_ (.A1(tmx_notouch_[6]), .A2(ring_en), .ZN(dfb_notouch_));
  (* keep *) `BINNER_INV1  dtap_notouch_ (.I(dfb_notouch_), .ZN(ring_out));
  /* verilator lint_on UNOPTFLAT */
  /* verilator lint_on PINMISSING */
`endif

endmodule
