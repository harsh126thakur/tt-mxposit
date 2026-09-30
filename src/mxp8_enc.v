// ============================================================================
// mxp8_enc : round a block-scaled value  t = (-1)^sign * 1.frac * 2^E  (E <= 0)
//            to posit<8,1> with round-to-nearest-even, and decode the result
//            back into fields for the multiplier.
//
//   * posit never rounds a non-zero value to 0  -> values below minpos give minpos
//   * block scaling guarantees |t| < 2, so the result is at most 2 (no overflow)
//   * E is the element exponent minus the shared block exponent (-39 .. 0)
//
// outputs:
//   code  : the actual posit8 bit pattern (two's complement for negatives)
//   ep    : posit scale  2k+e  of the rounded value   (-12 .. 1)
//   pf    : 4 fraction bits of the rounded value (zero-padded when fewer exist)
// ============================================================================
module mxp8_enc (
    input  wire              sign,
    input  wire              zero,
    input  wire signed [6:0] E,
    input  wire [9:0]        frac,
    output wire [7:0]        code,
    output reg  signed [4:0] ep,
    output reg  [3:0]        pf
);
    // ---- encode: build regime | e | fraction as an 18-bit string -----------
    wire signed [6:0] k   = E >>> 1;              // floor(E/2)  (-6 .. 0 when E >= -12)
    wire              e   = E[0];
    wire [2:0]        m   = -k[2:0];              // regime run length for k < 0
    wire              tiny = (E < -7'sd12);       // below minpos range

    wire [17:0] body_k0 = {2'b10, e, frac, 5'b0};        // k = 0  : "10" e f..
    wire [17:0] body_kn = {1'b1, e, frac, 6'b0} >> m;    // k = -m : m zeros, "1", e f..
    wire [17:0] body    = (k == 7'sd0) ? body_k0 : body_kn;

    wire [6:0] trunc   = body[17:11];
    wire       guard   = body[10];
    wire       sticky  = |body[9:0];
    wire       rnd_up  = guard & (sticky | trunc[0]);
    wire [6:0] mag_r   = trunc + {6'd0, rnd_up};

    wire [6:0] mag = zero ? 7'd0 : (tiny ? 7'd1 : mag_r);
    assign code = sign ? -{1'b0, mag} : {1'b0, mag};

    // ---- decode the rounded magnitude back into (ep, pf) ---------------------
    integer i;
    reg [2:0] lz;
    /* verilator lint_off UNUSEDSIGNAL */   // rest[1:0] are fraction bits beyond the 4 kept
    reg [6:0] rest;
    /* verilator lint_on UNUSEDSIGNAL */
    always @* begin
        lz = 3'd0;  rest = 7'd0;  ep = 5'sd0;  pf = 4'd0;
        for (i = 0; i < 7; i = i + 1)
            if (mag[i]) lz = 3'd6 - i[2:0];       // leading zeros of mag[6:0]
        if (mag[6]) begin                          // regime "10" -> k = 0
            ep = {4'd0, mag[4]};
            pf = mag[3:0];
        end else begin                             // regime lz zeros + "1" -> k = -lz
            rest = mag << (lz + 3'd1);
            ep   = -$signed({1'b0, lz, 1'b0}) + $signed({4'd0, rest[6]});
            pf   = rest[5:2];
        end
    end
endmodule
