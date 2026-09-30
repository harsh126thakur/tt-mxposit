"""Write test/block_vectors.hex for the cocotb test, using the Python model (mxposit.py).
Same format and generator as tb/gen_vectors.py (block part only), so it runs in seconds.
Usage:  python3 make_vectors.py [N_BLOCKS]"""
import sys, os
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mxposit import P8, to_fp16

val2code = {float(v): int(c) for v, c in zip(P8.vals, P8.codes)}
def f16bits(v): return int(np.array(v, dtype=np.float16).view(np.uint16))
def bits2f(b):  return float(np.array(b, dtype=np.uint16).view(np.float16))
def lg_of(v):   return int(np.floor(np.log2(abs(v))))
def block_exp(vals):
    nz = [abs(v) for v in vals if v != 0]
    return lg_of(max(nz)) if nz else 0
def posit_of(v, s):
    if v == 0: return 0.0, 0
    q = float(P8.quantize(np.array([v / 2.0 ** s]))[0])
    c = val2code[abs(q)]
    return q, ((-c) & 0xFF) if q < 0 else c
def lane(a, b, sa, sb):
    qa, ca = posit_of(a, sa); qb, cb = posit_of(b, sb)
    y = float(to_fp16(np.array([qa * 2.0 ** sa * qb * 2.0 ** sb]))[0])
    yb = f16bits(y)
    if y == 0: yb &= 0x7FFF           # sign of zero results is not compared
    return yb, ca, cb

def block_line(A, B):
    sa, sb = block_exp(A), block_exp(B)
    out = [lane(a, b, sa, sb) for a, b in zip(A, B)]
    return (" ".join("%04x" % f16bits(x) for x in A + B) + " " +
            " ".join("%04x" % o[0] for o in out) + " " +
            " ".join("%02x" % o[1] for o in out) + " " + " ".join("%02x" % o[2] for o in out) +
            " %02x %02x" % (sa & 0x3F, sb & 0x3F))

if __name__ == "__main__":
    import warnings; warnings.filterwarnings('ignore')
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    rng = np.random.default_rng(2)
    finite = [b for b in range(0x10000) if (b >> 10) & 0x1F != 0x1F]
    lines = []
    for _ in range(n):
        kind = rng.integers(0, 5)
        if kind == 0: v = rng.normal(0, 1, 8)
        if kind == 1: v = rng.normal(0, 0.02, 8)
        if kind == 2: v = rng.choice([-1, 1], 8) * np.exp(rng.normal(0, 4, 8))
        if kind == 3: v = rng.standard_t(2, 8) * 100
        if kind == 4: v = np.array([bits2f(x) for x in rng.choice(finite, 8)])
        v = np.clip(v, -65504, 65504)
        if rng.random() < 0.1: v[rng.integers(0, 8)] = 0.0
        v = [bits2f(f16bits(x)) for x in v]
        lines.append(block_line(v[:4], v[4:]))
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "block_vectors.hex")
    open(out, "w").write("\n".join(lines) + "\n")
    print("wrote", len(lines), "blocks to", out)
