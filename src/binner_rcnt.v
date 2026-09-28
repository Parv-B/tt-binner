/*
 * BINNER ring-domain event counter (one per measurement channel).
 *
 * Copyright (c) 2026 Parv Bhadra
 * SPDX-License-Identifier: Apache-2.0
 *
 * Clock domain: src_clk, the selected ring output (or the clk/2 test source).
 *
 *   cnt_en (clk domain) --> en_s1 --> en_s2      2-flop sync, clocked by src_clk
 *   bit 0  : T flip-flop, toggles on posedge src_clk while en_s2 = 1
 *   bit i  : ripple stage, toggles on negedge of bit i-1 (counts up)
 *   ovf    : sticky, set on negedge of bit 15 (wrap)
 *
 * en_s2 is returned to the clk domain (through binner_sync2 in binner_meas) as
 * the acknowledge. Once the clk domain has seen the acknowledge fall, the
 * counter is guaranteed static (no ring edges are counted after en_s2 = 0), so
 * the clk domain may copy it into its capture registers.
 *
 * Start and stop both pass through the same two-flop synchroniser, so the count
 * window equals the clk-domain gate time to within +-1 src_clk period.
 *
 * Only bit 0 and the synchroniser see the full source frequency; the ripple
 * stages need no timing closure, so the counter works well above the
 * frequency any synchronous 16-bit counter could reach in this process.
 *
 * Every flop is cleared asynchronously by arst_n (clk-domain reset OR clear
 * command). A clear is only ever issued while en_s2 = 0, so bit 0 is not
 * toggling when arst_n is released, and the ripple stages only toggle when bit
 * 0 does. Releasing the reset is therefore safe even if the ring is running.
 */

`default_nettype none

module binner_rcnt (
    input  wire        src_clk,
    input  wire        arst_n,
    input  wire        cnt_en,   // clk domain, level
    output wire        en_ack,   // = en_s2, ring domain (synchronise before use)
    output wire [15:0] cnt,
    output reg         ovf
);
  reg en_s1, en_s2;
  reg         q0;         // bit 0 (src_clk domain)
  wire [15:0] q;          // bits 15..1 are ripple stages, each clocked by the bit below
  assign q[0] = q0;

  always @(posedge src_clk or negedge arst_n) begin
    if (!arst_n) begin
      en_s1 <= 1'b0;
      en_s2 <= 1'b0;
      q0    <= 1'b0;
    end else begin
      en_s1 <= cnt_en;
      en_s2 <= en_s1;
      q0    <= q0 ^ en_s2;
    end
  end

  genvar i;
  generate
    for (i = 1; i < 16; i = i + 1) begin : g_rip
      reg b;
      always @(negedge q[i-1] or negedge arst_n) begin
        if (!arst_n) b <= 1'b0;
        else         b <= ~b;
      end
      assign q[i] = b;
    end
  endgenerate

  always @(negedge q[15] or negedge arst_n) begin
    if (!arst_n) ovf <= 1'b0;
    else         ovf <= 1'b1;
  end

  assign cnt    = q;
  assign en_ack = en_s2;
endmodule
