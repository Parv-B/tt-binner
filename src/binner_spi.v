/*
 * BINNER SPI slave (mode 0, MSB first), oversampled in the clk domain.
 *
 * Copyright (c) 2026 Parv Bhadra
 * SPDX-License-Identifier: Apache-2.0
 *
 * SCK, CS_N and MOSI are asynchronous pad inputs. Each is synchronised with two
 * flops, and SCK edges are detected in the clk domain, so the SPI logic adds no
 * clock domain. Requirement: f_SCK <= f_clk / 8 (recommended f_clk / 16).
 *
 * Transaction (CS_N low for the whole transaction):
 *   byte 0 : {W, A[6:0]}   W = 1 write, 0 read
 *   byte 1+: write -> data written to A, A+1, ... (auto-increment)
 *            read  -> MISO returns reg[A], reg[A+1], ... (auto-increment)
 * MISO is driven on falling SCK edges and is 0 whenever CS_N is high and
 * during byte 0. Reads have no side effects.
 */

`default_nettype none

module binner_spi (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       sck_in,
    input  wire       cs_n_in,
    input  wire       mosi_in,
    output reg        miso,
    // register-file port
    output reg  [6:0] addr,     // register address (read and write)
    output wire       wr_stb,   // one-cycle write strobe (combinational from flops)
    output wire [7:0] wr_data,  // valid with wr_stb
    input  wire [7:0] rd_data   // combinational read of reg[addr]
);
  wire sck, cs_n, mosi;
  binner_sync2 #(.RST_VAL(1'b0)) u_s_sck  (.clk(clk), .rst_n(rst_n), .d(sck_in),  .q(sck));
  binner_sync2 #(.RST_VAL(1'b1)) u_s_cs   (.clk(clk), .rst_n(rst_n), .d(cs_n_in), .q(cs_n));
  binner_sync2 #(.RST_VAL(1'b0)) u_s_mosi (.clk(clk), .rst_n(rst_n), .d(mosi_in), .q(mosi));

  reg       sck_d;
  reg [2:0] bitcnt;
  reg [7:0] sr;       // shared shift register: MOSI in at LSB, MISO out from MSB
  reg       first;    // next complete byte is the command byte
  reg       is_wr;
  reg       ld;       // load sr from rd_data on the next cycle

  wire sck_rise = sck & ~sck_d;
  wire sck_fall = ~sck & sck_d;
  wire [7:0] byte_in = {sr[6:0], mosi};

  // Write port: a data byte completes on this clk edge. The register file
  // samples wr_data at addr on the same edge that increments addr. All inputs
  // are flops, so the strobe is a clean one-cycle pulse in the clk domain.
  assign wr_stb  = ~cs_n & sck_rise & (bitcnt == 3'd7) & ~first & is_wr;
  assign wr_data = byte_in;

  // Mode 0: the slave samples MOSI on rising SCK and changes MISO on falling
  // SCK. One 8-bit register does both: each rising edge shifts MOSI in at the
  // LSB; each falling edge copies the MSB to the MISO flop. After a complete
  // byte, sr is reloaded with the read data for the next byte (0 for writes),
  // before the next falling edge (guaranteed by f_SCK <= f_clk/8).
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      sck_d   <= 1'b0;
      bitcnt  <= 3'd0;
      sr      <= 8'd0;
      first   <= 1'b1;
      is_wr   <= 1'b0;
      ld      <= 1'b0;
      miso    <= 1'b0;
      addr    <= 7'd0;
    end else begin
      sck_d  <= sck;
      if (cs_n) begin
        bitcnt <= 3'd0;
        first  <= 1'b1;
        ld     <= 1'b0;
        sr     <= 8'd0;
        miso   <= 1'b0;
      end else begin
        if (ld) begin
          sr <= is_wr ? 8'd0 : rd_data;
          ld <= 1'b0;
        end
        if (sck_rise) begin
          sr     <= byte_in;
          bitcnt <= bitcnt + 3'd1;
          if (bitcnt == 3'd7) begin
            ld <= 1'b1;
            if (first) begin
              first <= 1'b0;
              is_wr <= byte_in[7];
              addr  <= byte_in[6:0];
            end else begin
              addr <= addr + 7'd1;   // after the write below has used addr
            end
          end
        end
        if (sck_fall) miso <= sr[7];
      end
    end
  end
endmodule
