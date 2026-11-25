module tone_curve(input clk, output [3:0] digest, output strobe);
    localparam BANKS = 13;
    wire [BANKS*32-1:0] words;
    genvar b,l;
    generate for (b=0; b<BANKS; b=b+1) begin : bank
        wire [255:0] results;
        for (l=0; l<8; l=l+1) begin : channel
            wire [31:0] now, prior, value;
            sample_history #(.ID(8*b+l)) history(.clk(clk), .recent(now), .delayed(prior));
            wire [15:0] pedestal;
            local_contrast contrast(.clk(clk), .pixel(now[27:16]), .pedestal(pedestal));
            curve compute(.clk(clk), .pixel(prior[15:0]), .quadratic(now[31:16]), .linear(prior[31:16]), .black(pedestal), .corrected(value));
            assign results[l*32 +: 32] = value;
        end
        reg [31:0] lo, hi, word_q;
        always @(posedge clk) begin
            lo <= results[31:0] ^ results[63:32] ^ results[95:64] ^ results[127:96];
            hi <= results[159:128] ^ results[191:160] ^ results[223:192] ^ results[255:224];
            word_q <= lo ^ hi;
        end
        assign words[b*32 +: 32] = word_q;
    end endgenerate
    lane_readout #(.BANKS(BANKS)) readout(.clk(clk),.bank_words(words),.digest(digest),.strobe(strobe));
endmodule
