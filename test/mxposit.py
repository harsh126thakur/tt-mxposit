"""
MX-posit8 reference model  (Option 1: FP16 in -> block-scaled posit8 -> posit multiply -> FP16 out)

Formats compared (all 8-bit elements + one shared 8-bit power-of-two scale per block, like OCP MX):
  MX-posit8 (es=1)  scale = max-based      (same rule as OCP MX)
  MX-posit8 (es=1)  scale = centred        (block log-magnitude mean -> 2^0, posit's sweet spot)
  posit8 (es=1)     no scale               (baseline)
  MXFP8 E4M3 / E5M2 / MXINT8               (OCP MX v1.0 rules)
"""
import numpy as np

# ----------------------------------------------------------------------------- posit8
def posit_decode(p, n=8, es=1):
    """bit pattern -> float value (NaR -> nan)"""
    p &= (1 << n) - 1
    if p == 0: return 0.0
    if p == 1 << (n - 1): return float('nan')
    s = p >> (n - 1)
    if s: p = (-p) & ((1 << n) - 1)
    bits = [(p >> i) & 1 for i in range(n - 2, -1, -1)]
    r0 = bits[0]; m = 1
    while m < len(bits) and bits[m] == r0: m += 1
    k = m - 1 if r0 else -m
    rest = bits[m + 1:]
    e = 0
    for i in range(es):
        e = (e << 1) | (rest[i] if i < len(rest) else 0)
    frac = rest[es:]
    f = 1.0 + sum(b * 2.0 ** -(i + 1) for i, b in enumerate(frac))
    v = 2.0 ** (k * (1 << es) + e) * f
    return -v if s else v

class PositTable:
    """exact round-to-nearest-even quantiser built from the full code table"""
    def __init__(self, n=8, es=1):
        self.n, self.es = n, es
        codes = np.arange(1, 1 << (n - 1))                     # positive codes 1..127
        vals = np.array([posit_decode(int(c), n, es) for c in codes])
        self.codes, self.vals = codes, vals                     # ascending
        self.maxpos, self.minpos = vals[-1], vals[0]
        # posit rounding is RNE on the *bit string*; midpoints between adjacent codes:
        # inside a regime -> arithmetic mean ; across regime/exp boundary where
        # the next bit is an exponent bit -> geometric mean (standard posit behaviour).
        # we compute true midpoints by extending to n+1 bits (the rounding point is
        # the (n+1)-bit code between the two n-bit codes)
        ext = PositTableExt(n + 1, es)
        self.mid = np.array([ext.value_of_code((int(c) << 1) | 1) for c in codes[:-1]])

    def quantize(self, x):
        x = np.asarray(x, dtype=np.float64)
        a = np.abs(x)
        idx = np.searchsorted(self.mid, a, side='left')         # a<=mid -> lower
        # ties: a == mid -> choose even code
        tie = (idx < len(self.mid)) & (a == self.mid[np.minimum(idx, len(self.mid) - 1)])
        lower_even = (self.codes[np.minimum(idx, len(self.codes) - 1)] % 2 == 0)
        idx = np.where(tie & ~lower_even, idx + 1, idx)
        q = self.vals[np.clip(idx, 0, len(self.vals) - 1)]
        q = np.where(a == 0, 0.0, q)                            # posit never flushes non-zero to 0
        return np.sign(x) * q

class PositTableExt:
    def __init__(self, n, es): self.n, self.es = n, es
    def value_of_code(self, c): return posit_decode(c, self.n, self.es)

# ----------------------------------------------------------------------------- minifloat / int helpers
def fp_quantize(x, ebits, mbits, emax, maxval, subnormal=True):
    """round-to-nearest-even into a small float with saturation (OCP E4M3/E5M2 style)"""
    x = np.asarray(x, dtype=np.float64)
    a = np.abs(x)
    emin = 1 - (2 ** (ebits - 1) - 1)
    e = np.floor(np.log2(np.where(a > 0, a, 1.0)))
    e = np.maximum(e, emin)
    ulp = 2.0 ** (e - mbits)
    q = np.round(a / ulp) * ulp                                 # numpy round = RNE
    q = np.minimum(q, maxval)
    return np.sign(x) * q

def to_fp16(x):
    """RNE into IEEE fp16, saturating (overflow count reported separately)"""
    return np.asarray(x, dtype=np.float64).astype(np.float16).astype(np.float64)

# ----------------------------------------------------------------------------- block quantisers
P8 = PositTable(8, 1)

def shared_exp(block, rule, emax_elem):
    amax = np.max(np.abs(block), axis=-1, keepdims=True)
    amax = np.where(amax == 0, 1.0, amax)
    if rule == 'max':                                           # OCP MX rule
        s = np.floor(np.log2(amax)) - emax_elem
    elif isinstance(rule, (int, float)) and not isinstance(rule, bool):  # max rule with offset
        s = np.floor(np.log2(amax)) - rule
    elif rule == 'centre':                                      # log-mean of non-zeros -> 2^0
        a = np.abs(block); nz = a > 0
        lm = np.sum(np.where(nz, np.log2(np.where(nz, a, 1)), 0), -1, keepdims=True) / np.maximum(nz.sum(-1, keepdims=True), 1)
        s = np.round(lm)
    return np.clip(s, -127, 127)                                # E8M0 scale

def mx_quant(x, fmt, k, rule='max'):
    """x: (..., N) fp16 values -> dequantised values + shared exponent per block"""
    shp = x.shape
    b = x.reshape(-1, k).astype(np.float64)
    if fmt == 'posit8':
        s = shared_exp(b, rule, emax_elem=0) if not (isinstance(rule, str) and rule == 'none') else np.zeros((b.shape[0], 1))
        q = P8.quantize(b / 2.0 ** s)
    elif fmt == 'e4m3':
        s = shared_exp(b, 'max', 8);  q = fp_quantize(b / 2.0 ** s, 4, 3, 8, 448.0)
    elif fmt == 'e5m2':
        s = shared_exp(b, 'max', 15); q = fp_quantize(b / 2.0 ** s, 5, 2, 15, 57344.0)
    elif fmt == 'int8':
        s = shared_exp(b, 'max', 0)
        q = np.clip(np.round(b / 2.0 ** s * 64), -127, 127) / 64
    return (q * 2.0 ** s).reshape(shp), s

FORMATS = [
    ('MX-posit8 centred', 'posit8', 'centre'),
    ('MX-posit8 max',     'posit8', 'max'),
    ('posit8 no-scale',   'posit8', 'none'),
    ('MXFP8 E4M3',        'e4m3',   'max'),
    ('MXFP8 E5M2',        'e5m2',   'max'),
    ('MXINT8',            'int8',   'max'),
]

def sqnr(ref, q):
    err = np.sum((ref - q) ** 2); sig = np.sum(ref ** 2)
    return 10 * np.log10(sig / err) if err > 0 else np.inf

def rel_metrics(ref, q):
    nz = ref != 0
    r = np.abs(q[nz] - ref[nz]) / np.abs(ref[nz])
    return np.median(r), np.mean(r), np.mean(q[nz] == 0)
