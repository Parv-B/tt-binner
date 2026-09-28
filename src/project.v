/*
 * BINNER: on-die process monitor, speed-binning and variation characterisation.
 *
 * Copyright (c) 2026 Parv Bhadra
 * SPDX-License-Identifier: Apache-2.0
 *
 * Tiny Tapeout TTGF26d (GF180MCU, gf180mcu_fd_sc_mcu7t5v0 at 3.3 V), 1x1 tile.
 * Full specification: docs/SPEC.md. Decisions and evidence: DECISIONS.md.
 *
 * Pins
 *   ui_in[0]  SPI CS_N          uo_out[0] LFSR serial (state bit 15)
 *   ui_in[1]  SPI SCK           uo_out[1] channel A counter bit PINDIV (ring / 2^(PINDIV+1))
 *   ui_in[2]  SPI MOSI          uo_out[2] channel B counter bit PINDIV
 *   ui_in[3]  PINMODE           uo_out[3] SPI MISO
 *   ui_in[6:4] pin-mode select  uo_out[4] BUSY
 *   ui_in[7]  FMAX_RUN (SPI mode) / bank select (pin mode)
 *                               uo_out[5] FMAX_FAIL_ANY
 *                               uo_out[6] DONE
 *                               uo_out[7] FMAX_ARMED
 *   uio       debug byte out when UIOOE = 1, otherwise all inputs (reset state)
 *
 * Measurement sources (SRCA / SRCB, 5 bits)
 *   0..15  identical INV rings (within-die variation, RO-PUF)
 *   16     NAND2 ring   17 NOR2 ring   18 FO4 INV ring
 *   19     delay-chain ring (tap from DTAP)
 *   20     clk / 2 test source (known answer; gate-level test)
 *   21..31 constant 0
 */

`default_nettype none

module tt_um_parv_b_binner (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
    input  wire       ena,      // always 1 when the design is powered, so you can ignore it
    input  wire       clk,      // clock
    input  wire       rst_n     // reset_n - low to reset
);

  // ---------------------------------------------------------------------------
  // Parameters
  // ---------------------------------------------------------------------------
  localparam integer N_PUF  = 16;   // identical rings
  localparam integer N_STG  = 25;   // stages per ring (INV, NAND, NOR rings)
  localparam integer N_FO4  = 13;   // stages in the FO4 ring (4x the cells per stage)
  localparam [7:0]   ID0    = 8'h42; // 'B'
  localparam [7:0]   ID1    = 8'h4E; // 'N'
  localparam [7:0]   VER    = 8'h02;

  // ---------------------------------------------------------------------------
  // Reset and asynchronous pin synchronisers
  // ---------------------------------------------------------------------------
  wire rst_sn;
  binner_rst_sync u_rst (.clk(clk), .rst_n_in(rst_n), .rst_n_out(rst_sn));

  wire pinmode, fmax_pin;
  binner_sync2 u_s_pm  (.clk(clk), .rst_n(rst_sn), .d(ui_in[3]), .q(pinmode));
  binner_sync2 u_s_fr  (.clk(clk), .rst_n(rst_sn), .d(ui_in[7]), .q(fmax_pin));

  // ---------------------------------------------------------------------------
  // SPI slave and register file
  // ---------------------------------------------------------------------------
  wire [6:0] reg_addr;
  wire       wr_stb;
  wire [7:0] wr_data;
  reg  [7:0] rd_data;
  wire       miso;

  binner_spi u_spi (
      .clk(clk), .rst_n(rst_sn),
      .sck_in(ui_in[1]), .cs_n_in(ui_in[0]), .mosi_in(ui_in[2]),
      .miso(miso),
      .addr(reg_addr), .wr_stb(wr_stb), .wr_data(wr_data),
      .rd_data(rd_data)
  );

  reg [6:0]  r_ctrl;     // RUN, FREE, LFSR_RUN, LFSR_GATED, FMAX_EN, FMAX_INV, UIOOE
  reg [7:0]  r_srca;     // [4:0] SRCA, [7:5] DTAP
  reg [7:0]  r_srcb;     // [4:0] SRCB, [7:5] DBG (debug byte select)
  reg [7:0]  r_timing;   // [3:0] GEXP (gate = 2^GEXP clk cycles), [7:4] PINDIV
  // CMD (0x07) bits are one-cycle pulses taken straight from the write strobe.
  wire       cmd_wr   = wr_stb & (reg_addr == 7'h07);
  wire       c_start  = cmd_wr & wr_data[0];
  wire       c_clear  = cmd_wr & wr_data[1];
  wire       c_reseed = cmd_wr & wr_data[2];
  wire       c_fclr   = cmd_wr & wr_data[3];

  always @(posedge clk or negedge rst_sn) begin
    if (!rst_sn) begin
      r_ctrl   <= 7'd0;
      r_srca   <= 8'h00;
      r_srcb   <= 8'h08;
      r_timing <= 8'h5A;   // PINDIV = 5, GEXP = 10 (gate 1024 cycles)
    end else begin
      if (wr_stb) begin
        case (reg_addr)
          7'h03: r_ctrl   <= wr_data[6:0];
          7'h04: r_srca   <= wr_data;
          7'h05: r_srcb   <= wr_data;
          7'h06: r_timing <= wr_data;
          default: ;
        endcase
      end
    end
  end

  wire ctl_run   = r_ctrl[0];
  wire ctl_free  = r_ctrl[1];
  wire ctl_lrun  = r_ctrl[2];
  wire ctl_lgate = r_ctrl[3];
  wire ctl_fen   = r_ctrl[4];
  wire ctl_finv  = r_ctrl[5];
  wire ctl_uiooe = r_ctrl[6];
  wire [2:0] r_dtap   = r_srca[7:5];
  wire [2:0] r_dbg    = r_srcb[7:5];
  wire [3:0] r_gexp   = r_timing[3:0];
  wire [3:0] r_pindiv = r_timing[7:4];

  // ---------------------------------------------------------------------------
  // Source selection (SPI registers, or pins in pin-strap mode)
  // ---------------------------------------------------------------------------
  wire [4:0] src_a = pinmode ? (ui_in[7] ? {2'b10, ui_in[6:4]} : {2'b00, ui_in[6:4]}) : r_srca[4:0];
  wire [4:0] src_b = pinmode ? {2'b01, ui_in[6:4]} : r_srcb[4:0];
  wire       run   = ena & (ctl_run | pinmode);

  // ---------------------------------------------------------------------------
  // Ring bank
  // ---------------------------------------------------------------------------
  wire [31:0] src;   // source outputs
  wire [19:0] ren;   // ring enables

  genvar gi;
  generate
    for (gi = 0; gi < 20; gi = gi + 1) begin : g_en
      assign ren[gi] = run & ((src_a == gi) | (src_b == gi));
    end
    for (gi = 0; gi < N_PUF; gi = gi + 1) begin : g_puf
      binner_ring #(.N(N_STG), .KIND(0), .IDX(gi)) u_ring (.en(ren[gi]), .out(src[gi]));
    end
  endgenerate

  binner_ring #(.N(N_STG), .KIND(1), .IDX(16)) u_ring_nand (.en(ren[16]), .out(src[16]));
  binner_ring #(.N(N_STG), .KIND(2), .IDX(17)) u_ring_nor  (.en(ren[17]), .out(src[17]));
  binner_ring #(.N(N_FO4), .KIND(3), .IDX(18)) u_ring_fo4  (.en(ren[18]), .out(src[18]));

  // Delay chain: Fmax path, or ring when selected as a source.
  wire [7:0] dtaps;
  wire       launch;
  binner_dchain u_dchain (
      .launch(launch), .ring_mode(ren[19]), .ring_en(ren[19]), .tap_sel(r_dtap),
      .taps(dtaps), .ring_out(src[19])
  );

  // clk / 2 known-answer source.
  reg clk_div2;
  always @(posedge clk or negedge rst_sn) begin
    if (!rst_sn) clk_div2 <= 1'b0;
    else         clk_div2 <= ~clk_div2;
  end
  assign src[20]    = clk_div2;
  assign src[31:21] = 11'd0;

  wire clk_a = src[src_a];
  wire clk_b = src[src_b];

  // ---------------------------------------------------------------------------
  // Paired counters and measurement controller
  // ---------------------------------------------------------------------------
  wire        cnt_en, ring_clr, running;
  wire [15:0] cnt_a, cnt_b;
  wire        ovf_a, ovf_b, ack_a_raw, ack_b_raw;
  wire [6:0]  mstat;
  wire [1:0]  ack_sync;
  wire        rarst_n = rst_sn & ~ring_clr;

  binner_rcnt u_cnt_a (.src_clk(clk_a), .arst_n(rarst_n), .cnt_en(cnt_en),
                       .en_ack(ack_a_raw), .cnt(cnt_a), .ovf(ovf_a));
  binner_rcnt u_cnt_b (.src_clk(clk_b), .arst_n(rarst_n), .cnt_en(cnt_en),
                       .en_ack(ack_b_raw), .cnt(cnt_b), .ovf(ovf_b));

  binner_meas u_meas (
      .clk(clk), .rst_n(rst_sn),
      .start(c_start), .clear(c_clear), .gexp(r_gexp), .free_run(ctl_free | pinmode),
      .ack_a_raw(ack_a_raw), .ack_b_raw(ack_b_raw), .ovf_a(ovf_a), .ovf_b(ovf_b),
      .cnt_en(cnt_en), .ring_clr(ring_clr), .running(running),
      .status(mstat), .ack_sync(ack_sync)
  );

  // ---------------------------------------------------------------------------
  // Fmax checker
  // ---------------------------------------------------------------------------
  wire [15:0] lfsr;
  wire        f_armed, f_valid;
  wire [7:0]  f_fail, f_cap;
  wire        f_arm_lvl = ctl_fen & fmax_pin & ~pinmode;

  binner_fmax u_fmax (
      .clk(clk), .rst_n(rst_sn), .arm_lvl(f_arm_lvl), .clr(c_fclr), .inv_exp(ctl_finv),
      .data_in(lfsr[15] ^ lfsr[7]), .taps(dtaps), .launch(launch),
      .armed(f_armed), .fail(f_fail), .cap_raw(f_cap), .valid(f_valid)
  );

  // ---------------------------------------------------------------------------
  // LFSR
  // ---------------------------------------------------------------------------
  wire lfsr_step = ctl_lrun | (ctl_lgate & running) | pinmode | f_armed;
  binner_lfsr u_lfsr (.clk(clk), .rst_n(rst_sn), .step(lfsr_step), .reseed(c_reseed),
                      .state(lfsr));

  // ---------------------------------------------------------------------------
  // Register read mux (no read side effects)
  // ---------------------------------------------------------------------------
  wire [7:0] status = {f_armed, mstat};
  wire [7:0] misc   = {ring_clr, cnt_en, ena, f_valid, fmax_pin, ack_sync, pinmode};

  // CNTA/CNTB read the ring-domain counters directly. They are static from
  // DONE until the next START/CLEAR (handshake in binner_meas); in FREE mode
  // they are live and the read is debug-only.
  always @(*) begin
    case (reg_addr)
      7'h00: rd_data = ID0;
      7'h01: rd_data = ID1;
      7'h02: rd_data = VER;
      7'h03: rd_data = {1'b0, r_ctrl};
      7'h04: rd_data = r_srca;
      7'h05: rd_data = r_srcb;
      7'h06: rd_data = r_timing;
      7'h08: rd_data = status;
      7'h09: rd_data = cnt_a[7:0];
      7'h0A: rd_data = cnt_a[15:8];
      7'h0B: rd_data = cnt_b[7:0];
      7'h0C: rd_data = cnt_b[15:8];
      7'h0D: rd_data = lfsr[7:0];
      7'h0E: rd_data = lfsr[15:8];
      7'h0F: rd_data = f_fail;
      7'h10: rd_data = f_cap;
      7'h11: rd_data = misc;
      default: rd_data = 8'h00;
    endcase
  end

  // ---------------------------------------------------------------------------
  // Debug byte and outputs
  // ---------------------------------------------------------------------------
  reg [7:0] dbg_byte;
  always @(*) begin
    case (r_dbg)
      3'd0: dbg_byte = lfsr[7:0];
      3'd1: dbg_byte = lfsr[15:8];
      3'd2: dbg_byte = cnt_a[7:0];
      3'd3: dbg_byte = cnt_b[7:0];
      3'd4: dbg_byte = status;
      3'd5: dbg_byte = f_fail;
      3'd6: dbg_byte = misc;
      default: dbg_byte = cnt_a[15:8];   // live ring-domain bits: debug only
    endcase
  end

  assign uo_out[0] = lfsr[15];
  assign uo_out[1] = cnt_a[r_pindiv];
  assign uo_out[2] = cnt_b[r_pindiv];
  assign uo_out[3] = miso;
  assign uo_out[4] = mstat[0];      // BUSY
  assign uo_out[5] = |f_fail;
  assign uo_out[6] = mstat[1];      // DONE
  assign uo_out[7] = f_armed;       // confirms Fmax arming while at speed

  assign uio_out = dbg_byte;
  assign uio_oe  = {8{ctl_uiooe}};

  wire _unused = &{uio_in, 1'b0};

endmodule
