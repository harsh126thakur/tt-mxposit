// ============================================================================
// tt_um_harshrajthakur_mxposit : Tiny Tapeout top - block of 4 FP16 pairs, one shared lane
//                 PIPELINED version (2 register stages in the datapath)
//
//  ui_in[7:0]   data byte in
//  uio_in[0]    WR  : rising edge stores ui_in at the write pointer, pointer++
//                     byte order: A0.lo A0.hi A1.lo ... A3.hi  B0.lo ... B3.hi
//  uio_in[1]    RD  : rising edge advances the read pointer
//  uio_in[2]    CLR : high clears both pointers
//  uio_in[3]    MODE: 0 = read products  (ptr 0..7 : Y0.lo Y0.hi ... Y3.hi)
//                     1 = read debug      (ptr 0..3 : posit A0..A3, 4..7 : posit B0..B3,
//                                          8 : shared exp A, 9 : shared exp B)
//  uo_out[7:0]  selected byte (registered)
//  uio_out[4]   FULL : all 16 input bytes written
//  uio_out[5]   NaN  : current element had an Inf/NaN input
//  uio_out[6]   OVF  : current product overflowed to Inf
//  uio_out[7]   UNF  : current product underflowed to 0
//
//  Pipeline (the original single-cycle path was ~27 LUT levels, ~30.6 ns on Artix-7 -1):
//    R0  shared block exponents sA/sB registered   (they depend only on the stored
//        bytes, which change only on writes, so this adds no read latency)
//    S1  element select -> FP16 unpack -> posit8 encode/round   -> register
//    S2  posit multiply -> FP16 pack -> output byte select      -> uo_out register
//  A new read pointer reaches uo_out 2 clocks after it changes (was 1). The host
//  protocol (strobes >= 3 clocks high and low, synchronised on-chip) leaves more
//  time than that, so the pin interface is unchanged.
// ============================================================================
module tt_um_harshrajthakur_mxposit (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);
    // ---- synchronise the strobes coming from the host ------------------------
    reg [2:0] wr_s, rd_s;
    reg [1:0] clr_s, mode_s;
    always @(posedge clk) begin
        if (!rst_n) begin
            wr_s <= 0; rd_s <= 0; clr_s <= 0; mode_s <= 0;
        end else begin
            wr_s   <= {wr_s[1:0],  uio_in[0]};
            rd_s   <= {rd_s[1:0],  uio_in[1]};
            clr_s  <= {clr_s[0],   uio_in[2]};
            mode_s <= {mode_s[0],  uio_in[3]};
        end
    end
    wire wr_p = wr_s[1] & ~wr_s[2];
    wire rd_p = rd_s[1] & ~rd_s[2];
    wire clr  = clr_s[1];
    wire mode = mode_s[1];

    // ---- input storage: 16 bytes ----------------------------------------------
    reg [7:0] mem [0:15];
    reg [4:0] wptr;                 // 0..16
    reg [3:0] rptr;
    integer i;
    always @(posedge clk) begin
        if (!rst_n) begin
            wptr <= 0; rptr <= 0;
            for (i = 0; i < 16; i = i + 1) mem[i] <= 8'd0;
        end else if (clr) begin
            wptr <= 0; rptr <= 0;
        end else begin
            if (wr_p && !wptr[4]) begin
                mem[wptr[3:0]] <= ui_in;
                wptr <= wptr + 1'b1;
            end
            if (rd_p) rptr <= rptr + 1'b1;
        end
    end

    wire [63:0] A = {mem[7],  mem[6],  mem[5],  mem[4],  mem[3],  mem[2],  mem[1], mem[0]};
    wire [63:0] B = {mem[15], mem[14], mem[13], mem[12], mem[11], mem[10], mem[9], mem[8]};

    // ---- R0: shared block exponents, registered ----------------------------------
    wire signed [5:0] sA_c, sB_c;
    mxp_blockexp #(4) bxa (.xs(A), .s(sA_c));
    mxp_blockexp #(4) bxb (.xs(B), .s(sB_c));
    reg  signed [5:0] sA, sB;
    always @(posedge clk) begin
        if (!rst_n) begin sA <= 0; sB <= 0; end
        else        begin sA <= sA_c; sB <= sB_c; end
    end

    // ---- S1: select element, unpack, encode to posit8 ------------------------------
    wire [1:0]  idx = mode ? rptr[1:0] : rptr[2:1];
    wire [15:0] a   = A[16*idx +: 16];
    wire [15:0] b   = B[16*idx +: 16];

    wire sga, zra, spa, sgb, zrb, spb;
    wire signed [5:0] lga, lgb;
    wire [9:0] fra, frb;
    fp16_split ua (.x(a), .sign(sga), .zero(zra), .special(spa), .lg(lga), .frac(fra));
    fp16_split ub (.x(b), .sign(sgb), .zero(zrb), .special(spb), .lg(lgb), .frac(frb));

    wire signed [6:0] Ea = lga - sA;        // <= 0 by construction of the block exponent
    wire signed [6:0] Eb = lgb - sB;

    wire [7:0] pa_c, pb_c;
    wire signed [4:0] epa_c, epb_c;
    wire [3:0] pfa_c, pfb_c;
    mxp8_enc ea_i (.sign(sga), .zero(zra), .E(Ea), .frac(fra), .code(pa_c), .ep(epa_c), .pf(pfa_c));
    mxp8_enc eb_i (.sign(sgb), .zero(zrb), .E(Eb), .frac(frb), .code(pb_c), .ep(epb_c), .pf(pfb_c));

    reg [7:0] pa, pb;
    reg signed [4:0] epa, epb;
    reg [3:0] pfa, pfb;
    reg sga_r, zra_r, sgb_r, zrb_r, nan_r, mode_r;
    reg [3:0] rptr_r;
    always @(posedge clk) begin
        if (!rst_n) begin
            pa <= 0; pb <= 0; epa <= 0; epb <= 0; pfa <= 0; pfb <= 0;
            sga_r <= 0; zra_r <= 0; sgb_r <= 0; zrb_r <= 0; nan_r <= 0; mode_r <= 0; rptr_r <= 0;
        end else begin
            pa <= pa_c; pb <= pb_c; epa <= epa_c; epb <= epb_c; pfa <= pfa_c; pfb <= pfb_c;
            sga_r <= sga; zra_r <= zra; sgb_r <= sgb; zrb_r <= zrb;
            nan_r <= spa | spb; mode_r <= mode; rptr_r <= rptr;
        end
    end

    // ---- S2: multiply, pack FP16, choose the output byte -----------------------------
    wire [15:0] y;
    wire        ovf, unf;
    mxp8_mul_fp16 mul (.sa(sga_r), .za(zra_r), .ea(epa), .fa(pfa),
                       .sb(sgb_r), .zb(zrb_r), .eb(epb), .fb(pfb),
                       .sa_blk(sA), .sb_blk(sB), .nan_in(nan_r),
                       .y(y), .ovf(ovf), .unf(unf));

    reg [7:0] obyte, dbyte;
    always @* begin
        case (rptr_r)
            4'd8:    dbyte = {{2{sA[5]}}, sA};
            4'd9:    dbyte = {{2{sB[5]}}, sB};
            default: dbyte = rptr_r[3] ? 8'd0 : (rptr_r[2] ? pb : pa);
        endcase
    end
    reg [3:0] flags;
    always @(posedge clk) begin
        if (!rst_n) begin
            obyte <= 0; flags <= 0;
        end else begin
            obyte <= mode_r ? dbyte : (rptr_r[0] ? y[15:8] : y[7:0]);
            flags <= {unf, ovf, nan_r, wptr[4]};
        end
    end

    assign uo_out  = obyte;
    assign uio_out = {flags, 4'b0000};
    assign uio_oe  = 8'b1111_0000;

    wire _unused = &{ena, uio_in[7:4], 1'b0};
endmodule
