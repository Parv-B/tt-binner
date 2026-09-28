// BINNER standard-cell binding.
//
// Every hand-instantiated cell in the design goes through these macros, so the
// cell library is named in exactly one place. Library: GF180MCU 7-track
// (gf180mcu_fd_sc_mcu7t5v0), which is the library the Tiny Tapeout GF flow
// uses (see GROUND_TRUTH.md, "Standard-cell library").
//
// Naming rule: every instance and every net that forms part of a ring
// oscillator, a delay chain or an Fmax capture point contains the substring
// "notouch_". src/config.json sets RSZ_DONT_TOUCH_RX to that substring so the
// OpenROAD resizer neither buffers nor resizes these structures, and
// tools/netlist_audit.py verifies the result on the post-route netlist.
//
// mux2_1 is deliberately absent: it is listed in the PDK's drc_exclude.cells
// and is removed from the synthesis liberty by LibreLane.

`ifndef BINNER_CELLS_VH
`define BINNER_CELLS_VH

`define BINNER_INV1    gf180mcu_fd_sc_mcu7t5v0__inv_1
`define BINNER_BUF1    gf180mcu_fd_sc_mcu7t5v0__buf_1
`define BINNER_NAND2   gf180mcu_fd_sc_mcu7t5v0__nand2_1
`define BINNER_NOR2    gf180mcu_fd_sc_mcu7t5v0__nor2_1
`define BINNER_MUX2    gf180mcu_fd_sc_mcu7t5v0__mux2_2
`define BINNER_DLY     gf180mcu_fd_sc_mcu7t5v0__dlyd_1
`define BINNER_DFFRN   gf180mcu_fd_sc_mcu7t5v0__dffrnq_1

`endif
