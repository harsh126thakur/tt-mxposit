// ============================================================================
// mxp_blockexp : shared block exponent (OCP MX "max" rule, element emax = 0)
//   s = floor(log2(max |x_i|)) over the non-zero, non-special elements; 0 if none
//
//   Implemented as a 2-level comparator tree (tournament) instead of a
//   linear scan: same 3 comparators, but only 2 in series on the timing path.
//   Round 1:  max(e0, e1)   max(e2, e3)     (in parallel)
//   Round 2:  max(winner01, winner23)
//   NOTE: written for K = 4 only.
// ============================================================================
module mxp_blockexp #(parameter K = 4) (
    input  wire [16*K-1:0]   xs,
    output wire signed [5:0] s
);
    wire signed [5:0] lg [0:3];
    wire              v  [0:3];          // element takes part: non-zero and finite

    genvar g;
    generate for (g = 0; g < 4; g = g + 1) begin : u
        /* verilator lint_off UNUSEDSIGNAL */   // sign and fraction are not needed for the block max
        wire sg, zr, sp; wire [9:0] fr;
        /* verilator lint_on UNUSEDSIGNAL */
        fp16_split sp_i (.x(xs[16*g +: 16]), .sign(sg), .zero(zr), .special(sp),
                         .lg(lg[g]), .frac(fr));
        assign v[g] = !zr && !sp;
    end endgenerate

    // ---- round 1: two comparators working in parallel ----------------------
    wire              pick1 = v[1] && (!v[0] || lg[1] > lg[0]);
    wire signed [5:0] m01   = pick1 ? lg[1] : lg[0];
    wire              v01   = v[0] | v[1];

    wire              pick3 = v[3] && (!v[2] || lg[3] > lg[2]);
    wire signed [5:0] m23   = pick3 ? lg[3] : lg[2];
    wire              v23   = v[2] | v[3];

    // ---- round 2: final comparator -------------------------------------------
    wire              pickB = v23 && (!v01 || m23 > m01);
    wire signed [5:0] m     = pickB ? m23 : m01;

    assign s = (v01 | v23) ? m : 6'sd0;  // all zero / special -> 0
endmodule
