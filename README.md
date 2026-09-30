![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg) ![](../../workflows/fpga/badge.svg)

# MX-Posit8 block multiplier (FP16 in/out)

A Tiny Tapeout design with this datapath:

FP16 A, B → shared block exponent (OCP-MX "max" rule, block of 4) → posit<8,1> with round-to-nearest-even → posit × posit → FP16

The FP16 result is exact for normal results, rounds to nearest-even into subnormals, and overflows to ±Inf.

- Datasheet, pinout and protocol: [docs/info.md](docs/info.md)
- Top module: `tt_um_harshrajthakur_mxposit`, 1x2 tiles, 50 MHz, two pipeline stages

## Source files

| File | What it is |
|---|---|
| `src/tt_um_harshrajthakur_mxposit.v` | Top: 16-byte input store, 2 block-exponent units, 1 pipelined lane, byte-wide read-out |
| `src/mxp_blockexp.v` | Shared block exponent s = floor(log2 max\|x\|) over 4 elements |
| `src/fp16_split.v` | Unpacks FP16 into sign, zero, Inf/NaN, floor(log2) and normalised fraction (handles subnormals) |
| `src/mxp8_enc.v` | Block-scaled value → posit8 code with RNE; decodes back to (scale, fraction) |
| `src/mxp8_mul_fp16.v` | 5×5-bit significand multiply plus exponent add → FP16 |
| `test/test.py` | cocotb test: directed cases, overflow/underflow/NaN flags, 200 random blocks vs the Python model |
| `test/mxposit.py`, `test/make_vectors.py` | Python reference model and vector generator |

## Verification

- **cocotb** (this repo, `cd test && make`): 3 tests, run by the `test` GitHub action. After hardening, the `gds` action repeats them on the gate-level netlist.
- **Vivado 2024.1 xsim** (outside this repo): run on xc7a35tcpg236-1.
  - 431,424 single-element vectors, 20,000 blocks, and 300 blocks through the pin protocol: 0 mismatches.
  - Post-synthesis and post-implementation timing simulation: 0 mismatches.
  - 50 MHz timing met with WNS +2.690 ns.

## Run the test locally

```
cd test
pip install -r requirements.txt
make
```
