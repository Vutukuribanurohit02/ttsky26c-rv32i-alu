<!--
  ->  replaces docs/info.md

  This file becomes your page in the Tiny Tapeout datasheet, so it is read by
  people holding the chip, not just by you.  Keep the pin tables accurate.
-->

## How it works

This is a 32-bit RV32I arithmetic and logic unit — the datapath block that a
RISC-V core uses for every `ADD`, `SUB`, shift, comparison and bitwise
instruction. It takes two 32-bit operands and a 4-bit opcode, and produces a
32-bit result plus a zero flag (which a core uses to resolve `BEQ`/`BNE`).

The ALU itself is purely combinational. The interesting part is getting it onto
a Tiny Tapeout tile at all: the ALU needs 68 input bits and produces 33 output
bits, and a tile provides 8 dedicated inputs, 8 dedicated outputs and 8
bidirectionals. Rather than serialising with a handshake FSM, the operands are
exposed as a **byte-addressed register file**. The host writes nine bytes —
four for `a`, four for `b`, one opcode — in any order, then selects which
result byte to observe. There is no sequencing state to lose, so the interface
cannot get out of sync, and rewriting a single operand byte to re-evaluate
costs one clock instead of a full nine-byte reload.

The register file is 68 flip-flops. Writes are captured on the rising edge of
`clk` while `WE` is high; reads are combinational, so the result is valid as
soon as the last write has settled.

Address 9 is an **accumulate** command rather than a register: writing to it
feeds the ALU result back into `a`. That turns the chip into an accumulator —
load `a` and the opcode once, then stream new `b` values and take a running
total at one clock per operation instead of reloading all nine bytes each time.
It also creates the design's only register-to-register path, `a → ALU → a`,
which is what the static timing analysis has to close.

### Write address map

Little-endian: address 0 is the least significant byte.

| Address | Register        | Address | Register        |
| ------- | --------------- | ------- | --------------- |
| 0       | `a[7:0]`        | 5       | `b[15:8]`       |
| 1       | `a[15:8]`       | 6       | `b[23:16]`      |
| 2       | `a[23:16]`      | 7       | `b[31:24]`      |
| 3       | `a[31:24]`      | 8       | `alu_op[3:0]` (low nibble of the data byte) |
| 4       | `b[7:0]`        | 9       | **accumulate**: `a <= result` (data byte ignored) |
|         |                 | 10–15   | no effect       |

### Result byte select (`RSEL1:RSEL0`, `uio[6:5]`)

| Value | Byte on `uo_out` |
| ----- | ---------------- |
| 0     | `result[7:0]`    |
| 1     | `result[15:8]`   |
| 2     | `result[23:16]`  |
| 3     | `result[31:24]`  |

The zero flag is on `uio[7]`, driven continuously. `uio_oe` is `8'b1000_0000`.

### Opcodes

| Encoding | Operation | Encoding | Operation |
| -------- | --------- | -------- | --------- |
| `0000`   | ADD       | `0101`   | SLT       |
| `0001`   | SUB       | `0110`   | SLTU      |
| `0010`   | AND       | `0111`   | SLL       |
| `0011`   | OR        | `1000`   | SRL       |
| `0100`   | XOR       | `1001`   | SRA       |

Encodings `1010`–`1111` are unused and return zero.

`SLT` and `SLTU` return the comparison result zero-extended to 32 bits, so the
only non-zero value they can produce is `0x00000001`.

Shift amounts use `b[4:0]`, per the RV32I specification.

### Verification

The ALU was proven equivalent to a golden reference by BDD-based combinational
equivalence checking, and previously taken through a full open-source
RTL-to-GDSII flow on SkyWater 130 nm — nine-corner static timing analysis clean,
zero DRC, LVS and antenna violations. The wrapper adds the register file, so
this build is the first version of the design with a real clock tree and hold
analysis.

## How to test

Reset the design by pulling `rst_n` low for a few clocks. All registers clear to
zero, so immediately after reset the ALU is computing `0 + 0` and you should see
`0x00000000` on the result bytes with the zero flag high.

To evaluate an operation:

1. For each of the nine bytes, put the data on `ui[7:0]`, the address on
   `uio[3:0]`, raise `WE` (`uio[4]`), and clock once.
2. Lower `WE`.
3. Set `RSEL` (`uio[6:5]`) to 0, 1, 2, 3 in turn and read `uo[7:0]` each time to
   assemble the 32-bit result. Read the zero flag on `uio[7]`.

For example, `0x0000_0001 + 0x0000_0001`: write `01 00 00 00` to addresses 0–3,
`01 00 00 00` to addresses 4–7, `00` to address 8, then read `0x00000002`.

A quick sanity check that exercises the whole datapath is `SRA` of `0x80000000`
by 31, which should return `0xFFFFFFFF` — if you get `0x00000001` the shifter is
not sign-extending.

The cocotb testbench in `test/` runs directed corner vectors, 120 constrained
random vectors across every opcode, partial-write isolation, write-enable
gating, accumulate and running-total sequences, and reset behaviour. The same
suite is re-run against the hardened gate-level netlist.

## External hardware

None. The design works directly from the demo board's switches, PMOD headers or
the RP2040 firmware — eight switches for the data byte, the bidirectional
header for address and select, and the seven-segment or LED bank for the result
byte.
