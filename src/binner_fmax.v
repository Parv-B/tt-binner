/*
 * BINNER at-speed launch/capture Fmax checker.
 *
 * Copyright (c) 2026 Parv Bhadra
 * SPDX-License-Identifier: Apache-2.0
 *
 *   LFSR bit --> [launch flop] --> delay chain --tap k--> [capture flop k]
 *                     |                                        |
 *                     +--------> [reference flop R] ---- XOR ---+--> sticky FAIL[k]
 *
 * While armed, the launch flop loads a pseudo-random LFSR bit every clk cycle
 * (random data, so a path longer than 2 periods cannot alias to a pass as it
 * would with a toggle pattern). R captures the launch value one cycle later
 * over a short path. Capture flop k captures tap k at the same edge. If tap k's
 * delay (plus clk-to-Q and setup) exceeds the clock period, C_k != R on some
 * cycle and FAIL[k] sets and stays set until FMAX_CLEAR.
 *
 * Polarity: a tap passes when C_k == R. The FMAX_INV fault-injection bit
 * inverts the expected value, so every tap must fail at any frequency. That
 * proves each comparator and sticky flag can fire and has the right polarity.
 *
 * Arming is a LEVEL (arm_lvl), not an SPI command. The top level derives it
 * from CTRL.FMAX_EN AND the synchronised ui_in[7] pin, so firmware can:
 * switch the clock to the test frequency, raise the pin for the test window,
 * lower it, and only then return to a safe clock to read FAIL over SPI.
 * Glitches during PWM frequency changes therefore happen while disarmed.
 * The comparison is enabled three cycles after arming (pipeline fill) and
 * stops as soon as arm_lvl falls.
 *
 * The launch and capture flops are hand-instantiated DFFRNQ cells whose names
 * contain "notouch_"; binner.sdc declares the paths into the capture flops
 * false (they are slow on purpose), and the resizer leaves them alone.
 */

`default_nettype none
`include "binner_cells.vh"

module binner_fmax (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       arm_lvl,    // level: 1 = checking (already synchronised)
    input  wire       clr,        // one-cycle command: clear sticky flags
    input  wire       inv_exp,    // fault injection: invert expected value
    input  wire       data_in,    // pseudo-random launch data (LFSR)
    input  wire [7:0] taps,       // from binner_dchain
    output wire       launch,     // to binner_dchain
    output reg        armed,
    output reg  [7:0] fail,
    output wire [7:0] cap_raw,
    output wire       valid
);
  reg ref_q;
  reg [2:0] v;

  wire launch_d = armed ? data_in : launch;

`ifdef BINNER_BEHAV
  reg       launch_q;
  reg [7:0] cap_q;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      launch_q <= 1'b0;
      cap_q    <= 8'd0;
    end else begin
      launch_q <= launch_d;
      cap_q    <= taps;
    end
  end
  assign launch  = launch_q;
  assign cap_raw = cap_q;
`else
  /* verilator lint_off PINMISSING */
  (* keep *) `BINNER_DFFRN flaunch_notouch_ (.CLK(clk), .D(launch_d), .RN(rst_n), .Q(launch));
  genvar i;
  generate
    for (i = 0; i < 8; i = i + 1) begin : g_cap
      (* keep *) `BINNER_DFFRN fcap_notouch_ (.CLK(clk), .D(taps[i]), .RN(rst_n), .Q(cap_raw[i]));
    end
  endgenerate
  /* verilator lint_on PINMISSING */
`endif

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      armed <= 1'b0;
      ref_q <= 1'b0;
      v     <= 3'd0;
      fail  <= 8'd0;
    end else begin
      armed <= arm_lvl;
      ref_q <= launch;
      v     <= {v[1:0], armed & arm_lvl};
      if (clr)
        fail <= 8'd0;
      else if (v[2] & armed)
        fail <= fail | (cap_raw ^ {8{ref_q ^ inv_exp}});
    end
  end

  assign valid = v[2];
endmodule
