/*
 * BINNER synchronisers.
 *
 * Copyright (c) 2026 Parv Bhadra
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

// Two-flop synchroniser with asynchronous reset to RST_VAL.
module binner_sync2 #(
    parameter RST_VAL = 1'b0
) (
    input  wire clk,
    input  wire rst_n,
    input  wire d,
    output wire q
);
  reg s1, s2;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      s1 <= RST_VAL;
      s2 <= RST_VAL;
    end else begin
      s1 <= d;
      s2 <= s1;
    end
  end
  assign q = s2;
endmodule

// Reset synchroniser: asynchronous assert, synchronous (2-flop) de-assert.
module binner_rst_sync (
    input  wire clk,
    input  wire rst_n_in,
    output wire rst_n_out
);
  reg s1, s2;
  always @(posedge clk or negedge rst_n_in) begin
    if (!rst_n_in) begin
      s1 <= 1'b0;
      s2 <= 1'b0;
    end else begin
      s1 <= 1'b1;
      s2 <= s1;
    end
  end
  assign rst_n_out = s2;
endmodule
