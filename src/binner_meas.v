/*
 * BINNER measurement controller (clk domain).
 *
 * Copyright (c) 2026 Parv Bhadra
 * SPDX-License-Identifier: Apache-2.0
 *
 * One START runs a paired measurement on channels A and B:
 *
 *   IDLE --start--> CLR (2 cycles: ring-domain counters held in async clear)
 *        --> RUN   (cnt_en = 1 for exactly 2^GEXP clk cycles)
 *        --> WAIT  (cnt_en = 0; wait for each channel's acknowledge to fall)
 *        --> DONE = 1, both counters frozen --> IDLE
 *
 * CDC: the ring-domain en_s2 of each channel comes back through a 2-flop
 * synchroniser (ack). ack = 1 proves the channel started counting; ack falling
 * back to 0 proves en_s2 = 0, so the ring-domain counter can no longer change.
 * Only then is DONE raised. From DONE until the next START/CLEAR the counter
 * bits are static and are read directly through the register mux: the
 * ring-domain counters are their own capture registers (a separate clk-domain
 * copy cost 32 flops, about 6 % of the tile; see DECISIONS.md D-CAPTURE). This is
 * the standard "synchronised qualifier, stable data" handshake. Its correctness
 * does not depend on any timing between clk and the ring clock. In FREE mode
 * the counters are live and reads are debug-only.
 *
 * A channel whose source never oscillated (dead ring, or deselected) never
 * raises ack. For such a channel the controller waits a fixed 16 cycles after
 * the gate before finishing, and SEEN = 0 in STATUS marks the result as
 * invalid. If any channel's ack is still high 63 cycles after the gate (a
 * source slower than about clk/16), the controller finishes anyway and sets
 * TIMEOUT.
 *
 * FREE (free-run) holds cnt_en = 1 permanently, so the counters wrap
 * continuously. It is used for the divided ring outputs on the pins (and in
 * pin-strap mode).
 */

`default_nettype none

module binner_meas (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        start,      // one-cycle command
    input  wire        clear,      // one-cycle command
    input  wire [3:0]  gexp,       // gate = 2^gexp clk cycles
    input  wire        free_run,
    input  wire        ack_a_raw,  // ring domain en_s2, channel A
    input  wire        ack_b_raw,  // ring domain en_s2, channel B
    input  wire        ovf_a,
    input  wire        ovf_b,
    output wire        cnt_en,
    output reg         ring_clr,   // registered, drives ring-domain async clear
    output wire        running,    // RUN state (LFSR gated stepping)
    output wire [6:0]  status,     // {TIMEOUT, SEEN_B, SEEN_A, OVF_B, OVF_A, DONE, BUSY}
    output wire [1:0]  ack_sync
);
  localparam [1:0] S_IDLE = 2'd0, S_CLR = 2'd1, S_RUN = 2'd2, S_WAIT = 2'd3;

  reg  [1:0]  state;
  reg  [15:0] gcnt;
  reg         done, seen_a, seen_b, timeout;
  // gcnt counts the gate down in RUN, and is reused to count up in CLR/WAIT.
  wire [5:0]  wcnt = gcnt[5:0];

  wire ack_a, ack_b;
  binner_sync2 u_s_acka (.clk(clk), .rst_n(rst_n), .d(ack_a_raw), .q(ack_a));
  binner_sync2 u_s_ackb (.clk(clk), .rst_n(rst_n), .d(ack_b_raw), .q(ack_b));

  wire ok_a = seen_a ? ~ack_a : wcnt[4];   // unseen channel: wait 16 cycles
  wire ok_b = seen_b ? ~ack_b : wcnt[4];
  wire [15:0] gate_len = 16'd1 << gexp;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state    <= S_IDLE;
      gcnt     <= 16'd0;
      ring_clr <= 1'b1;   // counters held clear through reset
      done     <= 1'b0;
      seen_a   <= 1'b0;
      seen_b   <= 1'b0;
      timeout  <= 1'b0;
    end else if (clear) begin
      state    <= S_IDLE;
      ring_clr <= 1'b1;
      done     <= 1'b0;
      seen_a   <= 1'b0;
      seen_b   <= 1'b0;
      timeout  <= 1'b0;
    end else begin
      case (state)
        S_IDLE: begin
          ring_clr <= 1'b0;
          if (start) begin
            state    <= S_CLR;
            ring_clr <= 1'b1;
            gcnt     <= 16'd0;
            done     <= 1'b0;
            seen_a   <= 1'b0;
            seen_b   <= 1'b0;
            timeout  <= 1'b0;
          end
        end
        S_CLR: begin
          gcnt <= gcnt + 16'd1;
          if (gcnt[0]) begin      // second CLR cycle
            ring_clr <= 1'b0;
            state    <= S_RUN;
            gcnt     <= gate_len;
          end
        end
        S_RUN: begin
          if (ack_a) seen_a <= 1'b1;
          if (ack_b) seen_b <= 1'b1;
          gcnt <= gcnt - 16'd1;
          if (gcnt == 16'd1) begin
            state <= S_WAIT;   // gcnt is now 0
          end
        end
        default: begin  // S_WAIT
          if (ack_a) seen_a <= 1'b1;
          if (ack_b) seen_b <= 1'b1;
          if (wcnt != 6'h3F) gcnt <= gcnt + 16'd1;
          if ((ok_a && ok_b) || wcnt == 6'h3F) begin
            timeout <= ~(ok_a && ok_b);
            done    <= 1'b1;
            state   <= S_IDLE;
          end
        end
      endcase
    end
  end

  assign cnt_en   = free_run | (state == S_RUN);
  assign running  = (state == S_RUN);
  // OVF flags come straight from the (frozen) ring-domain counters.
  assign status   = {timeout, seen_b, seen_a, ovf_b, ovf_a, done, (state != S_IDLE)};
  assign ack_sync = {ack_b, ack_a};
endmodule
