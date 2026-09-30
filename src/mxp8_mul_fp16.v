// ============================================================================
// mxp8_mul_fp16 : multiply two block-scaled posit8 values and return binary16
//
//   A = 1.fa * 2^(ea + sa_blk) ,  B = 1.fb * 2^(eb + sb_blk)
//   The 5x5-bit significand product has at most 10 significant bits, so it is
//   always exact in FP16's 11-bit significand: rounding only happens when the
//   result falls into the FP16 subnormal range.  Overflow gives +/-Inf (IEEE).
// ============================================================================
module mxp8_mul_fp16 (
    input  wire              sa, za,
    input  wire signed [4:0] ea,
    input  wire [3:0]        fa,
    input  wire              sb, zb,
    input  wire signed [4:0] eb,
    input  wire [3:0]        fb,
    input  wire signed [5:0] sa_blk,      // shared block exponents
    input  wire signed [5:0] sb_blk,
    input  wire              nan_in,      // an operand was Inf/NaN
    output reg  [15:0]       y,
    output reg               ovf,         // result overflowed to Inf
    output reg               unf          // non-zero result flushed to 0
);
    wire       s  = sa ^ sb;
    wire [9:0] P  = {1'b1, fa} * {1'b1, fb};          // value P/256 in [1,4)
    wire       hi = P[9];
    wire [8:0] nm = hi ? P[8:0] : {P[7:0], 1'b0};    // 9 fraction bits after the leading 1

    /* verilator lint_off WIDTHEXPAND */   // signed operands are sign-extended to 8 bits on purpose
    wire signed [7:0] etot   = ea + eb + sa_blk + sb_blk + $signed({7'd0, hi});
    /* verilator lint_on WIDTHEXPAND */
    wire signed [7:0] biased = etot + 8'sd15;

    // subnormal path
    wire [10:0] sig   = {1'b1, nm, 1'b0};             // 1.mmmmmmmmmm
    wire [7:0]  shraw = 8'sd1 - biased;
    wire [3:0]  sh    = (shraw > 8'd13) ? 4'd13 : shraw[3:0];
    wire [23:0] ext   = {sig, 13'd0} >> sh;
    wire [10:0] mant  = ext[23:13];
    wire        g     = ext[12];
    wire        st    = |ext[11:0];
    wire [10:0] mant_r = mant + {10'd0, g & (st | mant[0])};

    always @* begin
        ovf = 1'b0; unf = 1'b0;
        if (nan_in)
            y = 16'h7E00;                                  // quiet NaN
        else if (za | zb)
            y = {s, 15'd0};
        else if (biased >= 8'sd31) begin
            y = {s, 5'h1F, 10'd0};  ovf = 1'b1;            // overflow -> Inf
        end else if (biased >= 8'sd1)
            y = {s, biased[4:0], nm, 1'b0};                // normal, exact
        else begin
            y = {s, 4'd0, mant_r};                         // subnormal (carry may reach min normal)
            unf = (mant_r == 11'd0);
        end
    end
endmodule
