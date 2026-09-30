`default_nettype none
`timescale 1ns / 1ps

/* Virtual demo board testbench wrapper -- identical shape to test/tb.v.
   Kept as its own copy (rather than reusing ../tb.v) so the vboard's
   Makefile/sim_build tree is fully self-contained.
*/
module tb ();

  // No $dumpfile/$dumpvars here (unlike test/tb.v): test/vboard/run_population.py
  // runs many chips as separate `make` invocations *in this same directory*
  // in parallel, and a shared "tb.fst" would race between them. The CSV is
  // the useful output for a population run; for one-off waveform debugging
  // of a single vboard chip, temporarily add the dump block back (or just
  // use test/Makefile's own test.py, which exercises the same RTL and
  // already dumps to test/tb.fst).

  reg clk;
  reg rst_n;
  reg ena;
  reg [7:0] ui_in;
  reg [7:0] uio_in;
  wire [7:0] uo_out;
  wire [7:0] uio_out;
  wire [7:0] uio_oe;

  tt_um_parv_b_binner user_project (
      .ui_in  (ui_in),
      .uo_out (uo_out),
      .uio_in (uio_in),
      .uio_out(uio_out),
      .uio_oe (uio_oe),
      .ena    (ena),
      .clk    (clk),
      .rst_n  (rst_n)
  );

endmodule
