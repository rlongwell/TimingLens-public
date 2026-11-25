module pixel_gain(input clk, output [3:0] digest, output strobe);
    localparam BANKS = 14;
    wire [BANKS*32-1:0] words;
    genvar b,l;
    generate for (b=0; b<BANKS; b=b+1) begin : bank
        wire [255:0] results;
        for (l=0; l<8; l=l+1) begin : channel
            wire [31:0] now, prior, value;
            sample_history #(.ID(8*b+l)) history(.clk(clk), .recent(now), .delayed(prior));
            reg [19:0] pixel_q;
            reg [15:0] gain_q;
            always @(posedge clk) begin
                pixel_q <= prior[19:0];
                gain_q <= now[31:16];
            end
            wire [35:0] scaled;
            gain_tile compute(.clk(clk), .sample_in(pixel_q), .gain(gain_q), .value(scaled));
            assign value = scaled[31:0] ^ {28'b0, scaled[35:32]};
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
