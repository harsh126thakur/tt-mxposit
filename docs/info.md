<!---

This file is used to generate your project datasheet. Please fill in the information below and delete any unused
sections.

You can also include images in this folder and reference them in the markdown. Each image must be less than
512 kb in size, and the combined size of all images must be less than 1 MB.
-->

## How it works

This project multiplies a block of four FP16 pairs through an 8-bit posit format with a shared block exponent. It follows the idea of the OCP Microscaling (MX) formats, but uses posit<8,1> elements instead of FP8 or INT8.

For each operand block (A0..A3 and B0..B3), the chip computes a shared exponent s = floor(log2 max|x|), ignoring zeros, Inf and NaN. Every element is divided by 2^s, which brings its magnitude below 2. It is then rounded to posit<8,1> with round-to-nearest-even; a non-zero value never rounds to zero. The two posits are multiplied, and the result is scaled back by 2^(sA+sB) and returned as FP16. A posit8 significand has at most 5 bits, so the 10-bit product is exact in FP16. Rounding only happens when the result falls into the FP16 subnormal range, and overflow gives ±Inf.

Inside the chip there is a 16-byte input store, two block-exponent units and a single multiplier lane. The lane is shared across the four elements by the read pointer. The datapath has two pipeline stages:

1. Select the element, unpack FP16 and encode to posit8 (shared exponents are held in registers).
2. Multiply the posits, pack to FP16 and select the output byte.

A new read pointer reaches `uo_out` two clocks after it changes. The host protocol below leaves more time than that.

## How to test

All host signals are synchronised on-chip. Keep every strobe high and low for at least 3 clock cycles.

1. Pulse CLR (uio[2]).
2. Write 16 bytes. For each byte, put it on ui_in and pulse WR (uio[0]). The order is A0.lo A0.hi A1.lo A1.hi A2.lo A2.hi A3.lo A3.hi, then B0.lo … B3.hi. FULL (uio[4]) goes high after the 16th byte.
3. Set MODE (uio[3]) low and pulse CLR. Then read 8 bytes from uo_out, pulsing RD (uio[1]) after each: Y0.lo Y0.hi … Y3.hi, where Yi = Ai × Bi in FP16.
   - While an element is being read, uio[5] = NaN input, uio[6] = overflow to Inf and uio[7] = underflow to zero.
   - CLR also resets the write pointer, so FULL drops at this point. The stored inputs are kept.
4. Optional debug read: set MODE high, pulse CLR and read 10 bytes.
   - Bytes 0–3 are the posit8 codes of A0..A3.
   - Bytes 4–7 are the posit8 codes of B0..B3.
   - Bytes 8 and 9 are the shared exponents sA and sB (sign-extended).

Example: A = {1.0, 2.0, 0.5, 1.5} = {3C00, 4000, 3800, 3E00} and B = four times 1.0 (3C00).
- The products read back as 3C00 4000 3800 3E00.
- The debug read gives A codes 30 40 20 38 and B codes 40 40 40 40, with sA = 1 and sB = 0.

## External hardware

None. The RP2040/RP2350 on the demo board can drive the protocol directly.
