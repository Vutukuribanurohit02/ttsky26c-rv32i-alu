#!/usr/bin/env python3
"""
test_tt_alu.py — validate the demo-board driver before silicon exists.

The chip returns in May 2027. This substitutes a Python model of the chip's
register interface for DemoBoardIO, so the protocol logic in tt_alu.py — byte
ordering, address decode, write-enable pulsing, result byte selection,
accumulate — is exercised today rather than debugged on a bench in eighteen
months with a part that either works or doesn't.

What this does NOT test: the ttboard SDK calls inside DemoBoardIO, which can
only be checked against real hardware. That class is deliberately thin for
exactly that reason.

    python3 test_tt_alu.py
"""

import sys
import tt_alu
from tt_alu import golden, MASK


class SimulatedChipIO:
    """Models the TTSKY26c register interface at the pin level.

    Deliberately written from the *interface documentation* rather than from
    tt_alu.py, so a misunderstanding of the protocol shows up as a mismatch
    instead of being silently shared by both sides.
    """

    def __init__(self):
        self.a = 0
        self.b = 0
        self.op = 0
        self.ui_in = 0
        self.uio_in = 0

    # -- what the chip computes combinationally ----------------------------
    def _result(self):
        return golden(self.op, self.a, self.b)[0]

    # -- the IO surface tt_alu.Alu drives ----------------------------------
    def set_inputs(self, ui_in, uio_in):
        self.ui_in = ui_in & 0xFF
        self.uio_in = uio_in & 0x7F

    def clock_once(self):
        """Register writes commit on the rising edge, when write enable is set."""
        if not (self.uio_in >> 4) & 1:
            return
        addr = self.uio_in & 0xF
        data = self.ui_in
        if 0 <= addr <= 3:
            sh = 8 * addr
            self.a = (self.a & ~(0xFF << sh) | (data << sh)) & MASK
        elif 4 <= addr <= 7:
            sh = 8 * (addr - 4)
            self.b = (self.b & ~(0xFF << sh) | (data << sh)) & MASK
        elif addr == 8:
            self.op = data & 0xF
        elif addr == 9:
            self.a = self._result()

    def read_uo(self):
        sel = (self.uio_in >> 5) & 0x3
        return (self._result() >> (8 * sel)) & 0xFF

    def read_zero_flag(self):
        return 1 if self._result() == 0 else 0

    def reset(self):
        self.a = self.b = self.op = 0


def main():
    print("driver validation against a simulated chip\n")
    alu = tt_alu.Alu(SimulatedChipIO())

    f1 = tt_alu.run(alu, tt_alu.DIRECTED, "directed (14)")
    f2 = tt_alu.run(alu, tt_alu.random_vectors(120), "random (120)")
    f3 = tt_alu.run_accumulate(alu)

    # Partial-write isolation: rewriting one byte of a must leave the rest
    # intact. This is the property the byte-addressed interface exists to
    # guarantee, so it deserves an explicit check.
    print("partial write isolation")
    alu.load_a(0xAABBCCDD)
    alu.load_b(0)
    alu.set_op(tt_alu.ADD)
    alu._write(tt_alu.ADDR_A + 2, 0x99)
    got = alu.result()
    ok = got == 0xAA99CCDD
    print("  %s a after rewriting byte 2: %08x" % ("ok  " if ok else "FAIL", got))

    total = len(f1) + len(f2) + (f3 or 0) + (0 if ok else 1)
    print("\n%s" % ("driver logic validated — ready for silicon"
                    if total == 0 else "%d failures" % total))
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
