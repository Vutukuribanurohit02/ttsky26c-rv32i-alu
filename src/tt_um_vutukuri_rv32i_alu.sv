/*
 * tt_um_vutukuri_rv32i_alu.sv   ->  goes in  src/
 *
 * Tiny Tapeout TTSKY26c wrapper for the RV32I ALU.
 *
 * Copyright (c) 2026 Banu Rohit Vutukuri
 * SPDX-License-Identifier: Apache-2.0
 *
 * ---------------------------------------------------------------------------
 * Why a wrapper
 * ---------------------------------------------------------------------------
 * The ALU needs 68 input bits (a[31:0], b[31:0], alu_op[3:0]) and produces
 * 33 output bits (result[31:0], zero).  Tiny Tapeout gives 8 dedicated inputs,
 * 8 dedicated outputs and 8 bidirectionals.  This wrapper exposes the operands
 * as a byte-addressed register file written over ui_in, and multiplexes the
 * result back out one byte at a time over uo_out.
 *
 * No FSM, no handshake, no sequencing.  68 flip-flops, one write port, two
 * read multiplexers.  The host is fully in control of ordering.
 *
 * ---------------------------------------------------------------------------
 * Pin map
 * ---------------------------------------------------------------------------
 *   ui_in[7:0]     in    write data byte
 *
 *   uio_in[3:0]    in    write address (see table below)
 *   uio_in[4]      in    write enable - byte is captured on the rising clk
 *                        edge while this is HIGH
 *   uio_in[6:5]    in    result byte select
 *   uio_in[7]      -     unused (this pin is driven as an output)
 *
 *   uo_out[7:0]    out   selected result byte (combinational)
 *   uio_out[7]     out   zero flag (combinational)
 *   uio_out[6:0]   out   tied low, not driven
 *
 *   uio_oe = 8'b1000_0000
 *
 * ---------------------------------------------------------------------------
 * Write address map  (little-endian: address 0 is the least significant byte)
 * ---------------------------------------------------------------------------
 *   0  a[7:0]      4  b[7:0]      8  {4'bx, alu_op[3:0]}  (upper nibble ignored)
 *   1  a[15:8]     5  b[15:8]     9..15  no effect
 *   2  a[23:16]    6  b[23:16]
 *   3  a[31:24]    7  b[31:24]
 *
 * ---------------------------------------------------------------------------
 * Result byte select  (uio_in[6:5])
 * ---------------------------------------------------------------------------
 *   0  result[7:0]     2  result[23:16]
 *   1  result[15:8]    3  result[31:24]
 *
 * ---------------------------------------------------------------------------
 * Usage
 * ---------------------------------------------------------------------------
 *   1. Release rst_n.
 *   2. Nine writes: four bytes of a, four bytes of b, one opcode byte.
 *      Order does not matter; you can rewrite any single byte and re-read.
 *   3. Drive uio_in[6:5] to pick a result byte and read uo_out.  The ALU is
 *      purely combinational, so the result is valid as soon as the registers
 *      have settled - no extra clock is required between the last write and
 *      the first read.
 *   4. Read the zero flag on uio_out[7] at any time.
 */

`default_nettype none

module tt_um_vutukuri_rv32i_alu (
    input  wire [7:0] ui_in,    // dedicated inputs
    output wire [7:0] uo_out,   // dedicated outputs
    input  wire [7:0] uio_in,   // bidirectional: input path
    output wire [7:0] uio_out,  // bidirectional: output path
    output wire [7:0] uio_oe,   // bidirectional: 1 = drive as output
    input  wire       ena,      // always 1 when the design is selected
    input  wire       clk,
    input  wire       rst_n     // active low
);

  // --------------------------------------------------------------------
  // control field decode
  // --------------------------------------------------------------------
  wire [3:0] wr_addr = uio_in[3:0];
  wire       wr_en   = uio_in[4];
  wire [1:0] res_sel = uio_in[6:5];

  // --------------------------------------------------------------------
  // operand registers - 32 + 32 + 4 = 68 flip-flops
  // --------------------------------------------------------------------
  reg [31:0] a_reg;
  reg [31:0] b_reg;
  reg [3:0]  op_reg;

  always @(posedge clk) begin
    if (!rst_n) begin
      a_reg  <= 32'd0;
      b_reg  <= 32'd0;
      op_reg <= 4'd0;
    end else if (wr_en) begin
      case (wr_addr)
        4'd0:    a_reg[7:0]    <= ui_in;
        4'd1:    a_reg[15:8]   <= ui_in;
        4'd2:    a_reg[23:16]  <= ui_in;
        4'd3:    a_reg[31:24]  <= ui_in;
        4'd4:    b_reg[7:0]    <= ui_in;
        4'd5:    b_reg[15:8]   <= ui_in;
        4'd6:    b_reg[23:16]  <= ui_in;
        4'd7:    b_reg[31:24]  <= ui_in;
        4'd8:    op_reg        <= ui_in[3:0];
        default: /* addresses 9..15 are no-ops */ ;
      endcase
    end
  end

  // --------------------------------------------------------------------
  // the DUT - unmodified, purely combinational
  // --------------------------------------------------------------------
  wire [31:0] alu_result;
  wire        alu_zero;

  alu u_alu (
      .a      (a_reg),
      .b      (b_reg),
      .alu_op (op_reg),
      .result (alu_result),
      .zero   (alu_zero)
  );

  // --------------------------------------------------------------------
  // result byte multiplexer
  // --------------------------------------------------------------------
  reg [7:0] result_byte;

  always @(*) begin
    case (res_sel)
      2'd0:    result_byte = alu_result[7:0];
      2'd1:    result_byte = alu_result[15:8];
      2'd2:    result_byte = alu_result[23:16];
      default: result_byte = alu_result[31:24];
    endcase
  end

  assign uo_out  = result_byte;
  assign uio_out = {alu_zero, 7'b000_0000};
  assign uio_oe  = 8'b1000_0000;

  // --------------------------------------------------------------------
  // tie off genuinely unused inputs so the linter stays quiet
  // --------------------------------------------------------------------
  wire _unused = &{ena, uio_in[7], 1'b0};

endmodule

`default_nettype wire
