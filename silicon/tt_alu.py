"""
tt_alu.py — driver for the TTSKY26c RV32I ALU, running on the demo board's
RP2040 under MicroPython.

The chip presents a byte-addressed register file across Tiny Tapeout's fixed
24-pin interface:

    writes   ui_in[7:0]  = data byte
             uio_in[3:0] = address
             uio_in[4]   = write enable      (captured on the rising clock edge)

    reads    uio_in[6:5] = which result byte appears on uo_out[7:0]
             uio_out[7]  = zero flag         (the only pin the chip drives)

    address  0-3  a[31:0], byte 0 = LSB
             4-7  b[31:0], byte 0 = LSB
             8    alu_op[3:0]  (low nibble)
             9    accumulate — loads a <= result

All hardware access is confined to DemoBoardIO. Everything above it is plain
Python and testable on a desktop against the same golden model the cocotb suite
uses, which is how this file gets validated before silicon exists.

Written September 2026. The die returns May 2027; expect the ttboard SDK to
have moved by then. If it has, DemoBoardIO is the only class that should need
touching.
"""

# --------------------------------------------------------------- opcode table
ADD, SUB, AND, OR, XOR, SLT, SLTU, SLL, SRL, SRA = range(10)

OPNAMES = {ADD: "ADD", SUB: "SUB", AND: "AND", OR: "OR", XOR: "XOR",
           SLT: "SLT", SLTU: "SLTU", SLL: "SLL", SRL: "SRL", SRA: "SRA"}

ADDR_A, ADDR_B, ADDR_OP, ADDR_ACC = 0, 4, 8, 9

MASK = 0xFFFFFFFF


# ------------------------------------------------------------------- hardware
class DemoBoardIO:
    """The only class that touches hardware.

    Wraps the ttboard SDK. Isolated deliberately: the SDK's surface has changed
    across shuttles, and when it changes again this is the single place to fix.
    """

    def __init__(self, project="tt_um_vutukuri_rv32i_alu"):
        from ttboard.demoboard import DemoBoard          # noqa: import inside
        self.tt = DemoBoard.get()
        self.tt.shuttle[project].enable()
        # uio[7] is the chip's zero-flag output; uio[6:0] are our inputs.
        self.tt.uio_oe_pico.value = 0x7F
        self.tt.ui_in.value = 0
        self.tt.uio_in.value = 0

    def set_inputs(self, ui_in, uio_in):
        self.tt.ui_in.value = ui_in & 0xFF
        self.tt.uio_in.value = uio_in & 0x7F

    def clock_once(self):
        self.tt.clock_project_once()

    def read_uo(self):
        return self.tt.uo_out.value & 0xFF

    def read_zero_flag(self):
        return (self.tt.uio_out.value >> 7) & 1

    def reset(self):
        self.tt.reset_project(True)
        self.tt.reset_project(False)


# ---------------------------------------------------------------------- driver
class Alu:
    """Byte-level protocol on top of whatever IO layer it's given."""

    def __init__(self, io):
        self.io = io
        self.io.reset()

    # -- primitives ---------------------------------------------------------
    def _write(self, addr, data):
        """One register write: present data and address, pulse write enable
        through a clock edge, then drop it."""
        self.io.set_inputs(data, (addr & 0xF) | (1 << 4))
        self.io.clock_once()
        self.io.set_inputs(data, addr & 0xF)

    def _read_byte(self, sel):
        """Result byte `sel`. Reads are combinational — no clock needed."""
        self.io.set_inputs(0, (sel & 0x3) << 5)
        return self.io.read_uo()

    # -- word-level ---------------------------------------------------------
    def load_a(self, value):
        for i in range(4):
            self._write(ADDR_A + i, (value >> (8 * i)) & 0xFF)

    def load_b(self, value):
        for i in range(4):
            self._write(ADDR_B + i, (value >> (8 * i)) & 0xFF)

    def set_op(self, op):
        self._write(ADDR_OP, op & 0xF)

    def result(self):
        v = 0
        for i in range(4):
            v |= self._read_byte(i) << (8 * i)
        return v & MASK

    def zero(self):
        return self.io.read_zero_flag()

    def accumulate(self):
        """Address 9 folds the result back into a. One clock, versus a nine-byte
        reload — which is the whole reason the address exists."""
        self._write(ADDR_ACC, 0)

    # -- the operation everything else is built from ------------------------
    def compute(self, op, a, b):
        """Thirteen bus transactions for one 32-bit operation. Slower than the
        RP2040 computing it directly, by a wide margin. This chip is a tapeout
        vehicle, not an accelerator, and the write-up says so."""
        self.load_a(a)
        self.load_b(b)
        self.set_op(op)
        return self.result(), self.zero()


# ------------------------------------------------------------- golden model
def golden(op, a, b):
    """Reference result, computed on the RP2040. Same semantics as the Python
    model used by the cocotb suite and the DII differ."""
    a &= MASK
    b &= MASK
    sa = a - (1 << 32) if a & 0x80000000 else a
    sb = b - (1 << 32) if b & 0x80000000 else b
    sh = b & 0x1F
    if op == ADD:  r = (a + b) & MASK
    elif op == SUB:  r = (a - b) & MASK
    elif op == AND:  r = a & b
    elif op == OR:   r = a | b
    elif op == XOR:  r = a ^ b
    elif op == SLT:  r = 1 if sa < sb else 0
    elif op == SLTU: r = 1 if a < b else 0
    elif op == SLL:  r = (a << sh) & MASK
    elif op == SRL:  r = a >> sh
    elif op == SRA:  r = (sa >> sh) & MASK
    else:            r = 0
    return r, (1 if r == 0 else 0)


# ------------------------------------------------------------------- vectors
DIRECTED = [
    (ADD,  0x00000001, 0x00000001),
    (ADD,  0xFFFFFFFF, 0x00000001),   # wraps to zero -> zero flag
    (SUB,  0x00000005, 0x00000005),   # equal -> zero flag
    (SUB,  0x00000000, 0x00000001),   # borrow
    (AND,  0xF0F0F0F0, 0x0FF00FF0),
    (OR,   0xF0F0F0F0, 0x0F0F0F0F),
    (XOR,  0xAAAAAAAA, 0xFFFFFFFF),
    (SLL,  0x00000001, 0x0000001F),   # shift to the top bit
    (SRL,  0x80000000, 0x0000001F),
    (SRA,  0x80000000, 0x0000001F),   # sign extends to all ones
    (SRA,  0x80000000, 0x00000000),   # shift amount zero
    (SLT,  0xFFFFFFFF, 0x00000001),   # -1 < 1 signed
    (SLTU, 0xFFFFFFFF, 0x00000001),   # but not unsigned
    (SLL,  0x12345678, 0x00000020),   # shamt is b[4:0], so this is 0
]


def _lcg(seed):
    """Small deterministic PRNG — MicroPython's random module is not always
    present, and a fixed sequence makes silicon results comparable across runs."""
    state = seed & MASK
    while True:
        state = (1103515245 * state + 12345) & MASK
        yield state


def random_vectors(n=120, seed=0xC0FFEE):
    rng = _lcg(seed)
    ops = [ADD, SUB, AND, OR, XOR, SLL, SRL, SLT, SLTU, SRA]
    out = []
    for _ in range(n):
        op = ops[next(rng) % len(ops)]
        out.append((op, next(rng), next(rng)))
    return out


# --------------------------------------------------------------------- runner
def run(alu, vectors, label, verbose=False):
    passed = failed = 0
    failures = []
    for op, a, b in vectors:
        got, gz = alu.compute(op, a, b)
        exp, ez = golden(op, a, b)
        if got == exp and gz == ez:
            passed += 1
            if verbose:
                print("  ok   %-4s %08x %08x -> %08x" % (OPNAMES[op], a, b, got))
        else:
            failed += 1
            failures.append((op, a, b, got, gz, exp, ez))
            print("  FAIL %-4s a=%08x b=%08x  got=%08x/z%d  exp=%08x/z%d"
                  % (OPNAMES[op], a, b, got, gz, exp, ez))
    print("%s: %d/%d passed" % (label, passed, passed + failed))
    return failures


def read_accumulator(alu):
    """The chip exposes f(a, b), never `a` itself. To observe the accumulator,
    set b = 0 and read a + 0.

    Worth knowing before bench time: after an accumulate, result() returns
    a_new + b, not a_new, because the read is combinational and b is unchanged.
    """
    alu.load_b(0)
    alu.set_op(ADD)
    return alu.result()


def run_accumulate(alu):
    """Load a and the opcode once, then stream b values through address 9.
    Exercises the design's only register-to-register path — the a -> ALU -> a
    arc that gave static timing analysis something real to close."""
    print("accumulate: running total")
    alu.load_a(0)
    total = 0
    for b in (1, 2, 3, 4, 5, 0x7FFFFFFF, 0x80000000):
        alu.set_op(ADD)
        alu.load_b(b)
        alu.accumulate()
        total = (total + b) & MASK
        got = read_accumulator(alu)
        if got != total:
            print("  FAIL after +%08x: got %08x expected %08x" % (b, got, total))
            return 1
    print("  ok   final %08x after 7 accumulates" % total)
    return 0


def main():
    print("TTSKY26c RV32I ALU — silicon correlation")
    print("comparing measured behaviour against the same vectors that passed")
    print("at RTL and post-route gate level\n")

    alu = Alu(DemoBoardIO())

    f1 = run(alu, DIRECTED, "directed (14)")
    f2 = run(alu, random_vectors(120), "random (120)")
    f3 = run_accumulate(alu)

    total_fail = len(f1) + len(f2) + (f3 or 0)
    print("\n%s" % ("ALL PASS — silicon matches simulation"
                    if total_fail == 0 else
                    "%d FAILURES — silicon diverges from simulation" % total_fail))
    return total_fail


if __name__ == "__main__":
    main()
