`default_nettype none
`timescale 1ns / 1ps

/* This testbench just instantiates the module and makes some convenient wires
   that can be driven / tested by the cocotb tests (test_*.py).

   The port hookup is identical for RTL, structural (make struct) and
   gate-level (GATES=yes, GL_TEST) simulation. The named single-bit wires below
   exist only so cocotb can wait on edges of individual output bits (Icarus
   does not give handles to bits of a packed vector).
*/
module tb ();

  // Dump the signals to a FST file. You can view it with gtkwave or surfer.
  // +NODUMP disables dumping (used by long configurations).
  initial begin
    if (!$test$plusargs("NODUMP")) begin
      $dumpfile("tb.fst");
      $dumpvars(0, tb);
    end
    #1;
  end

  // Wire up the inputs and outputs:
  reg clk;
  reg rst_n;
  reg ena;
  reg [7:0] ui_in;
  reg [7:0] uio_in;
  wire [7:0] uo_out;
  wire [7:0] uio_out;
  wire [7:0] uio_oe;
`ifdef GL_TEST
  wire VPWR = 1'b1;
  wire VGND = 1'b0;
`endif

  // Named output bits (docs/SPEC.md section 1).
  wire lfsr_pin = uo_out[0];
  wire cha_div  = uo_out[1];
  wire chb_div  = uo_out[2];
  wire miso_pin = uo_out[3];
  wire busy_pin = uo_out[4];
  wire ffail_pin = uo_out[5];
  wire done_pin = uo_out[6];
  wire farmed_pin = uo_out[7];  // FMAX_ARMED

  // Replace tt_um_parv_b_binner with your module name:
  tt_um_parv_b_binner user_project (

      // Include power ports for the Gate Level test:
`ifdef GL_TEST
      .VPWR(VPWR),
      .VGND(VGND),
`endif

      .ui_in  (ui_in),    // Dedicated inputs
      .uo_out (uo_out),   // Dedicated outputs
      .uio_in (uio_in),   // IOs: Input path
      .uio_out(uio_out),  // IOs: Output path
      .uio_oe (uio_oe),   // IOs: Enable path (active high: 0=input, 1=output)
      .ena    (ena),      // enable - goes high when design is selected
      .clk    (clk),      // clock
      .rst_n  (rst_n)     // not reset
  );

endmodule
