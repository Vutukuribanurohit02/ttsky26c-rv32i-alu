# test.py   ->  goes in  test/
#
# Copyright (c) 2026 Banu Rohit Vutukuri
# SPDX-License-Identifier: Apache-2.0

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge, Timer

# ---------------------------------------------------------------------------
# Opcode encoding - transcribed from the localparams in src/alu.sv.
# Note the ordering: comparisons sit at 5/6 and shifts at 7/8, which is not
# the ordering most RV32I ALU examples use.
# ---------------------------------------------------------------------------
OP_ADD  = 0x0
OP_SUB  = 0x1
OP_AND  = 0x2
OP_OR   = 0x3
OP_XOR  = 0x4
OP_SLT  = 0x5
OP_SLTU = 0x6
OP_SLL  = 0x7
OP_SRL  = 0x8
OP_SRA  = 0x9

MASK = 0xFFFFFFFF

# write addresses
ADDR_A = 0   # 0..3
ADDR_B = 4   # 4..7
ADDR_OP = 8


def to_signed(x):
    return x - (1 << 32) if x & 0x8000_0000 else x


def model(op, a, b):
    """Golden reference for the RV32I ALU."""
    sa, sb = to_signed(a), to_signed(b)
    sh = b & 0x1F

    if op == OP_ADD:
        return (a + b) & MASK
    if op == OP_SUB:
        return (a - b) & MASK
    if op == OP_AND:
        return a & b
    if op == OP_OR:
        return a | b
    if op == OP_XOR:
        return a ^ b
    if op == OP_SLL:
        return (a << sh) & MASK
    if op == OP_SRL:
        return a >> sh
    if op == OP_SLT:
        return 1 if sa < sb else 0
    if op == OP_SLTU:
        return 1 if a < b else 0
    if op == OP_SRA:
        return (sa >> sh) & MASK
    raise ValueError(f"unmodelled opcode {op:#x}")


# ---------------------------------------------------------------------------
# bus helpers
# ---------------------------------------------------------------------------
async def write_byte(dut, addr, data):
    """One register write: address + data on the bus, WE high for one edge."""
    dut.ui_in.value = data & 0xFF
    dut.uio_in.value = (addr & 0xF) | (1 << 4)
    await RisingEdge(dut.clk)
    # drop write enable, keep the bus quiet
    dut.uio_in.value = 0
    await Timer(1, units="ns")


async def write_word(dut, base_addr, value):
    """Four byte writes, LSB first."""
    for i in range(4):
        await write_byte(dut, base_addr + i, (value >> (8 * i)) & 0xFF)


async def read_result(dut):
    """Read all four result bytes plus the zero flag."""
    result = 0
    for i in range(4):
        dut.uio_in.value = i << 5          # RSEL, WE low
        await Timer(2, units="ns")         # let the combinational path settle
        result |= int(dut.uo_out.value) << (8 * i)
    zero = (int(dut.uio_out.value) >> 7) & 1
    dut.uio_in.value = 0
    return result, zero


async def apply(dut, op, a, b):
    await write_word(dut, ADDR_A, a)
    await write_word(dut, ADDR_B, b)
    await write_byte(dut, ADDR_OP, op)
    return await read_result(dut)


async def reset(dut):
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_pin_directions(dut):
    """uio_oe must be 8'b1000_0000 at all times."""
    cocotb.start_soon(Clock(dut.clk, 100, units="ns").start())
    await reset(dut)
    assert int(dut.uio_oe.value) == 0b1000_0000, (
        f"uio_oe is {int(dut.uio_oe.value):#010b}, expected 0b10000000"
    )
    dut._log.info("uio_oe correct")


@cocotb.test()
async def test_reset_state(dut):
    """After reset both operands and the opcode are zero, so ADD gives 0."""
    cocotb.start_soon(Clock(dut.clk, 100, units="ns").start())
    await reset(dut)
    result, zero = await read_result(dut)
    assert result == 0, f"result after reset is {result:#010x}, expected 0"
    assert zero == 1, "zero flag should be set when result is 0"


@cocotb.test()
async def test_directed(dut):
    """Hand-picked vectors, including the corners that usually break things."""
    cocotb.start_soon(Clock(dut.clk, 100, units="ns").start())
    await reset(dut)

    vectors = [
        (OP_ADD,  0x0000_0001, 0x0000_0001),
        (OP_ADD,  0xFFFF_FFFF, 0x0000_0001),   # wrap to zero -> zero flag
        (OP_SUB,  0x0000_0005, 0x0000_0005),   # equal -> zero flag
        (OP_SUB,  0x0000_0000, 0x0000_0001),   # borrow
        (OP_AND,  0xF0F0_F0F0, 0x0FF0_0FF0),
        (OP_OR,   0xF0F0_F0F0, 0x0F0F_0F0F),
        (OP_XOR,  0xAAAA_AAAA, 0xFFFF_FFFF),
        (OP_SLL,  0x0000_0001, 0x0000_001F),   # shift to the top bit
        (OP_SRL,  0x8000_0000, 0x0000_001F),
        (OP_SRA,  0x8000_0000, 0x0000_001F),   # sign extends to all ones
        (OP_SRA,  0x8000_0000, 0x0000_0000),   # shift amount 0
        (OP_SLT,  0xFFFF_FFFF, 0x0000_0001),   # -1 < 1 signed
        (OP_SLTU, 0xFFFF_FFFF, 0x0000_0001),   # but not unsigned
        (OP_SLL,  0x1234_5678, 0x0000_0020),   # shamt is b[4:0], so this is 0
    ]

    for op, a, b in vectors:
        result, zero = await apply(dut, op, a, b)
        expect = model(op, a, b)
        assert result == expect, (
            f"op={op:#x} a={a:#010x} b={b:#010x}: "
            f"got {result:#010x}, expected {expect:#010x}"
        )
        assert zero == (1 if expect == 0 else 0), (
            f"op={op:#x} a={a:#010x} b={b:#010x}: zero flag is {zero}"
        )
    dut._log.info(f"{len(vectors)} directed vectors passed")


@cocotb.test()
async def test_random(dut):
    """Constrained random across every opcode."""
    cocotb.start_soon(Clock(dut.clk, 100, units="ns").start())
    await reset(dut)

    random.seed(0xC0FFEE)
    ops = [OP_ADD, OP_SUB, OP_AND, OP_OR, OP_XOR,
           OP_SLL, OP_SRL, OP_SLT, OP_SLTU, OP_SRA]

    for _ in range(120):
        op = random.choice(ops)
        a = random.getrandbits(32)
        b = random.getrandbits(32)
        result, zero = await apply(dut, op, a, b)
        expect = model(op, a, b)
        assert result == expect, (
            f"op={op:#x} a={a:#010x} b={b:#010x}: "
            f"got {result:#010x}, expected {expect:#010x}"
        )
        assert zero == (1 if expect == 0 else 0)
    dut._log.info("120 random vectors passed")


@cocotb.test()
async def test_partial_write(dut):
    """Rewriting one byte must leave the other three alone."""
    cocotb.start_soon(Clock(dut.clk, 100, units="ns").start())
    await reset(dut)

    await write_word(dut, ADDR_A, 0xDEAD_BEEF)
    await write_word(dut, ADDR_B, 0x0000_0000)
    await write_byte(dut, ADDR_OP, OP_ADD)
    result, _ = await read_result(dut)
    assert result == 0xDEAD_BEEF, f"got {result:#010x}"

    # touch only the top byte of a
    await write_byte(dut, ADDR_A + 3, 0x12)
    result, _ = await read_result(dut)
    assert result == 0x12AD_BEEF, f"partial write clobbered a: {result:#010x}"

    # and only the bottom byte
    await write_byte(dut, ADDR_A + 0, 0x34)
    result, _ = await read_result(dut)
    assert result == 0x12AD_BE34, f"partial write clobbered a: {result:#010x}"


@cocotb.test()
async def test_no_write_when_we_low(dut):
    """Address and data on the bus with WE low must not change anything."""
    cocotb.start_soon(Clock(dut.clk, 100, units="ns").start())
    await reset(dut)

    await write_word(dut, ADDR_A, 0x1111_1111)
    await write_word(dut, ADDR_B, 0x0000_0000)
    await write_byte(dut, ADDR_OP, OP_ADD)

    # drive a write-looking bus but leave WE low
    dut.ui_in.value = 0xFF
    dut.uio_in.value = ADDR_A          # bit 4 clear
    await ClockCycles(dut.clk, 3)
    dut.uio_in.value = 0

    result, _ = await read_result(dut)
    assert result == 0x1111_1111, f"register changed with WE low: {result:#010x}"


@cocotb.test()
async def test_reset_clears(dut):
    """Reset must return every register to zero."""
    cocotb.start_soon(Clock(dut.clk, 100, units="ns").start())
    await reset(dut)

    await write_word(dut, ADDR_A, 0xFFFF_FFFF)
    await write_word(dut, ADDR_B, 0xFFFF_FFFF)
    await write_byte(dut, ADDR_OP, OP_XOR)

    await reset(dut)
    result, zero = await read_result(dut)
    assert result == 0, f"result after reset is {result:#010x}"
    assert zero == 1
