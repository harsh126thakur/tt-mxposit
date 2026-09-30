// ============================================================================
// fp16_split : unpack an IEEE-754 binary16 value
//   lg   = floor(log2(|x|))          (-24 .. 15)   valid when !zero && !special
//   frac = 10 fraction bits after the leading 1 (subnormals are normalised)
// ============================================================================
module fp16_split (
    input  wire [15:0]       x,
    output wire              sign,
    output wire              zero,
    output wire              special,     // Inf or NaN
    output reg  signed [5:0] lg,
    output reg  [9:0]        frac
);
    wire [4:0] ex = x[14:10];
    wire [9:0] mt = x[9:0];

    assign sign    = x[15];
    assign special = (ex == 5'd31);
    assign zero    = (ex == 5'd0) && (mt == 10'd0);

    integer i;
    reg [3:0] p;                          // position of leading 1 in a subnormal mantissa
    always @* begin
        p = 4'd0;
        for (i = 0; i < 10; i = i + 1)
            if (mt[i]) p = i[3:0];
        if (ex != 5'd0) begin             // normal
            lg   = $signed({1'b0, ex}) - 6'sd15;
            frac = mt;
        end else begin                    // subnormal: value = mt * 2^-24
            lg   = $signed({2'b00, p}) - 6'sd24;
            frac = mt << (4'd10 - p);     // drop the leading 1, left-align
        end
    end
endmodule
