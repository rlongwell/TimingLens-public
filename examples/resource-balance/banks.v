// Independent sensor histories / gain stages with a registered board-facing signature.
module banks(input clk, output [3:0] digest, output strobe);
    localparam LANES = 300;
    genvar n;
    wire [7:0] values [0:LANES-1];
    generate for (n=0; n<LANES; n=n+1) begin: channel
        reg [31:0] state = 32'hc17b4a53 ^ (32'h9e3779b9*(n+1));
        wire [31:0] x = state ^ (state << 13);
        wire [31:0] y = x ^ (x >> 17);
        always @(posedge clk) state <= y ^ (y << 5);
        queue_store store(.clk(clk),.we(state[31]),.addr(state[13:8]),.din(state[7:0]),.dout(values[n]));
    end endgenerate
    localparam GROUPS = (LANES+7)/8;
    wire [GROUPS*32-1:0] words;
    generate for (n=0;n<GROUPS;n=n+1) begin: fold
        reg [7:0] comb, q;
        integer k;
        always @* begin
            comb=0;
            for(k=0;k<8 && 8*n+k<LANES;k=k+1) comb=comb^values[8*n+k];
        end
        always @(posedge clk) q<=comb;
        assign words[n*32+:32]={24'b0,q};
    end endgenerate
    lane_readout #(.BANKS(GROUPS)) outstream(.clk(clk),.bank_words(words),.digest(digest),.strobe(strobe));
endmodule
