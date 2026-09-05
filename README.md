# RV32I ALU — Tiny Tapeout TTSKY26c

A formally verified 32-bit RISC-V ALU submitted to the [Tiny Tapeout](https://tinytapeout.com) TTSKY26c shuttle on SkyWater 130nm.

The interesting part of this project is not the ALU. It is getting a 101-signal datapath through a 24-pin fixed interface, and closing timing on a die you do not get to size.

---

## The constraint

Tiny Tapeout gives every project the same pinout: `ui_in[7:0]` in, `uo_out[7:0]` out, `uio[7:0]` bidirectional.

The ALU needs **68 input bits** (`a[31:0]`, `b[31:0]`, `alu_op[3:0]`) and produces **33 output bits** (`result[31:0]`, `zero`). That is four times oversubscribed on input alone. The RTL itself is unchanged — it is byte-for-byte the module formally verified with SymbiYosys and hardened standalone in an earlier project. Everything around it is new.

**Why not a serialisation FSM.** The obvious approach is shifting operands in behind a handshake. It was rejected: an FSM carries sequencing state, and sequencing state can desynchronise. If the host and the chip disagree about which byte is next, there is no way to detect it from outside and no recovery short of a full reset. On a die with no probe access, that is a bad trade.

**What was built instead:** a byte-addressed register file. The host writes any byte in any order, rewrites any single byte, and reads the result back a byte at a time. There is no protocol state to lose, and no illegal states — any sequence of writes leaves the chip in a valid configuration, because no sequence is being tracked.

Cost: 68 flip-flops, and with them a real clock tree and hold analysis.

---

## Interface

### Writes

`ui_in[7:0]` is the data byte, `uio_in[3:0]` the address, `uio_in[4]` the write enable. Captured on the rising edge of `clk` when write enable is high.

| Address | Target |
|---|---|
| `0`–`3` | `a[31:0]`, byte 0 = LSB |
| `4`–`7` | `b[31:0]`, byte 0 = LSB |
| `8` | `alu_op[3:0]` (low nibble of the data byte) |
| `9` | **accumulate** — loads `a <= result` |

### Reads

Purely combinational, no clock required. `uio_in[6:5]` selects which byte of the result appears on `uo_out[7:0]`. The zero flag sits permanently on `uio_out[7]`, with `uio_oe = 8'b1000_0000`.

### Opcodes

| `alu_op` | Operation | `alu_op` | Operation |
|---|---|---|---|
| `0x0` | ADD | `0x5` | SLT |
| `0x1` | SUB | `0x6` | SLTU |
| `0x2` | AND | `0x7` | SLL |
| `0x3` | OR | `0x8` | SRL |
| `0x4` | XOR | `0x9` | SRA |

### Accumulate

Address 9 is not a register. Writing to it feeds the ALU result back into `a`, turning a stateless calculator into an accumulator: load `a` and the opcode once, then stream `b` values and pulse address 9 after each. A running total costs one clock per operation instead of a nine-byte reload.

In RTL it is one case arm. Physically it is the design's only register-to-register path — `a → ALU → a` through the full 32-bit datapath — and it is what gives static timing analysis something real to close. That arc has **+10.49 ns** of slack, comfortably the least critical path in the design.

---

## Sign-off

Hardened with LibreLane 3.x on a fixed 1×1 tile at a 25 ns clock constraint.

| Metric | Value | Metric | Value |
|---|---|---|---|
| Setup worst slack | **+0.425 ns** | Standard cells | 1,602 |
| Reg-to-reg setup slack | +10.49 ns | Core utilisation | 85.5% |
| Hold worst slack | +0.117 ns | Routed wirelength | 55.4 mm |
| Clock skew | 0.255 ns | Flip-flops | 68 |
| DRC / LVS / antenna | 0 / 0 / 0 | Clock buffers | 117 |

Every figure above comes from `tt_submission/stats/metrics.csv` in the `gds` workflow artifact.

### One violation the green checkmark hid

The first hardened build passed DRC, LVS, antenna and every gate-level test. The workflow reported success. It also carried a **−2.19 ns setup violation**, because the shuttle's CI does not fail on timing.

It was found by parsing `metrics.csv` out of the build artifact rather than reading the summary page. The failing path was not the new accumulate arc — that had positive slack throughout — but the older register-to-output path, `a_reg → ALU → result mux → pad`, measuring 22.2 ns against the template's default 20 ns constraint.

The fix was one line: `CLOCK_PERIOD` from 20 ns to 25 ns. For a host-paced register interface the operating frequency is irrelevant — nothing streams — so the only thing given up is a datasheet number. Utilisation dropped from 85.2% to 80.4% in the process, because the relaxed constraint let synthesis pick smaller cells.

The final +0.425 ns is thin, about 1.7% margin, which puts the real critical path at 24.6 ns.

---

## Verification

`test/test.py`, cocotb, ten tests:

| Test | Covers |
|---|---|
| `test_pin_directions` | `uio_oe` drives only bit 7 |
| `test_reset_state` | Registers clear on `rst_n` |
| `test_directed` | 14 hand-picked vectors — zero-flag wrap, borrow, sign-extending SRA, shift-amount truncation to `b[4:0]`, and the SLT/SLTU pair that differs only in signedness |
| `test_random` | 120 constrained-random vectors across all ten opcodes, seeded, checked against a Python golden model |
| `test_partial_write` | Writing one operand byte leaves the other eight untouched |
| `test_no_write_when_we_low` | Data on `ui_in` ignored when `uio_in[4]` is low |
| `test_reset_clears` | Reset mid-sequence returns to a known state |
| `test_accumulate` | Address 9 loads `a <= result` |
| `test_accumulate_running_total` | Repeated accumulate produces a correct running sum |
| `test_accumulate_needs_write_enable` | Address 9 is gated by write enable like any other write |

All ten pass at RTL under Icarus, and again against the post-route gate-level netlist in the `gds` workflow. Simulating the netlist is the part that matters — it is the only check that what was routed still does what the RTL did.

---

## Reproduce

Everything runs in GitHub Actions on the shuttle's template; no local toolchain is needed to rebuild the GDS. Pushing to `main` triggers `test` (cocotb under Icarus), `gds` (LibreLane hardening plus gate-level re-test) and `docs` (datasheet publish).

Locally, the simulation needs only Icarus Verilog and cocotb:

```bash
cd test && make
```

Full ten-test result in under a second. To rebuild the physical design locally instead of in CI, LibreLane via Nix with the sky130 PDK reproduces the same flow.

---

## Files

| Path | Contents |
|---|---|
| `src/tt_um_vutukuri_rv32i_alu.sv` | Wrapper — register file, address decode, result mux |
| `src/alu.sv` | The ALU itself, unmodified |
| `src/config.json` | Hardening constraints, including `CLOCK_PERIOD` |
| `test/test.py` | cocotb suite |
| `docs/info.md` | Datasheet page |
| `info.yaml` | Shuttle metadata — 1×1 tile |

---

## Honest scope

This is a 1×1 tile on a shared educational shuttle, not production silicon, and an ALU behind a byte-wide register interface is slower than the CPU driving it — thirteen bus transactions per operation. It is not an accelerator and is not presented as one.

What it is: the same RTL taken from formal proof through a fixed-die tapeout flow with a real clock tree, one timing violation caught behind a passing CI run, and a design that will come back as a physical part in May 2027. The remaining work is running these same 134 vectors against that part and correlating measured behaviour with simulation.

---

**Banu Rohit Vutukuri** · University of Houston
Portfolio: [vutukuribanurohit02.github.io/fpga-portfolio](https://vutukuribanurohit02.github.io/fpga-portfolio/) · Full write-up: [Project 07](https://vutukuribanurohit02.github.io/fpga-portfolio/project7-tiny-tapeout/)
