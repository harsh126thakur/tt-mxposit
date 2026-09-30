# SPDX-License-Identifier: Apache-2.0
# cocotb test for tt_um_harshrajthakur_mxposit - drives the byte protocol the way the RP2040 would.
import os
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

WR, RD, CLR, MODE = 0, 1, 2, 3                 # uio_in bits
FULL, NAN, OVF, UNF = 4, 5, 6, 7                # uio_out bits


def make_clock(dut, period_ns=20):
    try:                                        # cocotb 2.x
        return Clock(dut.clk, period_ns, unit="ns")
    except TypeError:                           # cocotb 1.x
        return Clock(dut.clk, period_ns, units="ns")


class Host:
    def __init__(self, dut):
        self.dut, self.uio = dut, 0

    def set(self, bit, v):
        self.uio = (self.uio | (1 << bit)) if v else (self.uio & ~(1 << bit))
        self.dut.uio_in.value = self.uio

    async def pulse(self, bit):                 # strobes must stay stable >= 3 clocks
        await ClockCycles(self.dut.clk, 3); self.set(bit, 1)
        await ClockCycles(self.dut.clk, 4); self.set(bit, 0)
        await ClockCycles(self.dut.clk, 4)

    async def clear(self):
        self.set(CLR, 1); await ClockCycles(self.dut.clk, 4)
        self.set(CLR, 0); await ClockCycles(self.dut.clk, 4)

    def out(self):   return int(self.dut.uo_out.value)
    def flags(self): return int(self.dut.uio_out.value)

    async def load(self, a, b):
        await self.clear()
        for x in list(a) + list(b):
            self.dut.ui_in.value = x & 0xFF;        await self.pulse(WR)
            self.dut.ui_in.value = (x >> 8) & 0xFF; await self.pulse(WR)
        assert self.flags() >> FULL & 1, "FULL flag not set after 16 bytes"

    async def products(self):
        """returns [(y, nan, ovf, unf)] * 4"""
        self.set(MODE, 0); await self.clear()
        res = []
        for _ in range(4):
            await ClockCycles(self.dut.clk, 3)
            lo, f = self.out(), self.flags()
            await self.pulse(RD)
            await ClockCycles(self.dut.clk, 3)
            hi = self.out()
            await self.pulse(RD)
            res.append(((hi << 8) | lo, f >> NAN & 1, f >> OVF & 1, f >> UNF & 1))
        return res

    async def debug(self):
        """returns 8 posit codes (A0..A3, B0..B3) and the two shared exponents (6-bit)"""
        self.set(MODE, 1); await self.clear()
        vals = []
        for _ in range(10):
            await ClockCycles(self.dut.clk, 3)
            vals.append(self.out())
            await self.pulse(RD)
        self.set(MODE, 0)
        return vals[:8], vals[8] & 0x3F, vals[9] & 0x3F


async def start(dut):
    cocotb.start_soon(make_clock(dut).start())
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)
    return Host(dut)


def same(got, exp):
    """exact match, except the sign of a zero result is not checked"""
    return got == exp or (exp == 0 and (got & 0x7FFF) == 0)


# (A, B, expected Y, expected posit codes A+B, sA, sB) - from the Python model
DIRECTED = [
    ([0x3C00, 0x4000, 0x3800, 0x3E00], [0x3C00] * 4,                     # exact values
     [0x3C00, 0x4000, 0x3800, 0x3E00], [0x30, 0x40, 0x20, 0x38] + [0x40] * 4, 0x01, 0x00),
    ([0xBC00, 0x4000, 0xB800, 0x3E00], [0x3C00, 0xC200, 0x3C00, 0x3C00],  # signs
     [0xBC00, 0xC600, 0xB800, 0x3E00], [0xD0, 0x40, 0xE0, 0x38, 0x30, 0xB8, 0x30, 0x30], 0x01, 0x01),
    ([0x0000, 0x3C00, 0x3C00, 0x3C00], [0xBC00, 0x3C00, 0x3C00, 0x3C00],  # zero operand
     [0x0000, 0x3C00, 0x3C00, 0x3C00], [0x00, 0x40, 0x40, 0x40, 0xC0, 0x40, 0x40, 0x40], 0x00, 0x00),
]


@cocotb.test()
async def test_directed(dut):
    h = await start(dut)
    for a, b, y_exp, p_exp, sa, sb in DIRECTED:
        await h.load(a, b)
        for i, (y, nan, ovf, unf) in enumerate(await h.products()):
            assert same(y, y_exp[i]), f"Y{i}: got {y:04x} expected {y_exp[i]:04x}"
            assert (nan, ovf, unf) == (0, 0, 0), f"Y{i}: unexpected flags {nan}{ovf}{unf}"
        codes, gsa, gsb = await h.debug()
        assert codes == p_exp, f"posit codes {[hex(c) for c in codes]}"
        assert (gsa, gsb) == (sa, sb), f"shared exponents {gsa} {gsb}"


@cocotb.test()
async def test_flags(dut):
    h = await start(dut)
    # overflow: 65504 * 65504 -> +Inf, OVF set
    await h.load([0x7BFF] * 4, [0x7BFF] * 4)
    for y, nan, ovf, unf in await h.products():
        assert y == 0x7C00 and ovf == 1 and nan == 0, f"overflow: {y:04x} {nan}{ovf}{unf}"
    # underflow: 2^-24 * 2^-24 -> 0, UNF set
    await h.load([0x0001] * 4, [0x0001] * 4)
    for y, nan, ovf, unf in await h.products():
        assert (y & 0x7FFF) == 0 and unf == 1, f"underflow: {y:04x} {nan}{ovf}{unf}"
    # Inf / NaN inputs -> quiet NaN, NaN flag; excluded from the block max
    await h.load([0x7C00, 0x7E00, 0x3C00, 0x3C00], [0x3C00] * 4)
    res = await h.products()
    for i in (0, 1):
        assert res[i][0] == 0x7E00 and res[i][1] == 1, f"NaN Y{i}: {res[i]}"
    for i in (2, 3):
        assert res[i][0] == 0x3C00 and res[i][1] == 0, f"Y{i} next to NaN: {res[i]}"


@cocotb.test()
async def test_vectors(dut):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "block_vectors.hex")
    if not os.path.exists(path):
        dut._log.warning("block_vectors.hex missing - run make_vectors.py"); return
    h = await start(dut)
    n = 0
    for line in open(path):
        f = [int(t, 16) for t in line.split()]
        if len(f) != 22: continue
        x, y_exp, p_exp, sa, sb = f[0:8], f[8:12], f[12:20], f[20], f[21]
        await h.load(x[:4], x[4:])
        for i, (y, *_ ) in enumerate(await h.products()):
            assert same(y, y_exp[i]), f"block {n} Y{i}: got {y:04x} expected {y_exp[i]:04x}  in={[hex(v) for v in x]}"
        codes, gsa, gsb = await h.debug()
        assert codes == p_exp and (gsa, gsb) == (sa, sb), f"block {n} debug mismatch"
        n += 1
    dut._log.info(f"{n} blocks OK")
