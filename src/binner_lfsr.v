/*
 * BINNER 16-bit self-test LFSR (lock-up-free).
 *
 * Copyright (c) 2026 Parv Bhadra
 * SPDX-License-Identifier: Apache-2.0
 *
 * Fibonacci LFSR, shift left, polynomial x^16 + x^15 + x^13 + x^4 + 1 (taps
 * 16,15,13,4; maximal length per Xilinx XAPP052 Table 3).
 *
 * De Bruijn modification: the feedback bit is XORed with (q[14:0] == 0). This
 * splices the all-zero state into the maximal-length cycle between 0x8000 and
 * 0x0001:
 *   0x8000 -> fb = 1 ^ 1 = 0 -> 0x0000
 *   0x0000 -> fb = 0 ^ 1 = 1 -> 0x0001   (the plain LFSR maps 0x8000 -> 0x0001)
 * Every other state has q[14:0] != 0 and follows the plain LFSR. The sequence is
 * therefore a single cycle through all 2^16 states. Whatever state the flops
 * power up or glitch into, the register is on that cycle, so there is no
 * lock-up state. (Proof and exhaustive check: DECISIONS.md D-LFSR, and
 * test/test_lfsr.py, which walks all 65536 states.)
 *
 * The asynchronous reset loads SEED (0xACE1), so reset can never produce a
 * lock-up either. `reseed` reloads SEED synchronously.
 */

`default_nettype none

module binner_lfsr #(
    parameter [15:0] SEED = 16'hACE1
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        step,
    input  wire        reseed,
    output wire [15:0] state
);
  reg  [15:0] q;
  wire        zero15 = (q[14:0] == 15'd0);
  wire        fb     = q[15] ^ q[14] ^ q[12] ^ q[3] ^ zero15;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)      q <= SEED;
    else if (reseed) q <= SEED;
    else if (step)   q <= {q[14:0], fb};
  end

  assign state = q;
endmodule
