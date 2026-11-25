// Deterministic streaming stimulus with a per-channel read-first line/history RAM.
// Every lane contributes all 32 output bits to the board-facing signature.
module sample_history #(parameter ID=0)(input clk, output reg [31:0] recent, delayed);
    reg [31:0] state = 32'h89a74219 ^ (32'h9e3779b9 * (ID+1));
    wire [31:0] x = state ^ (state << 13);
    wire [31:0] y = x ^ (x >> 17);
    (* ram_style = "block" *) reg [31:0] memory [0:1023];
    reg [9:0] address = ID;
    always @(posedge clk) begin
        state <= y ^ (y << 5);
        recent <= state;
        delayed <= memory[address];
        memory[address] <= state;
        address <= address + 1'b1;
    end
endmodule

module lane_readout #(parameter BANKS=1)(input clk, input [BANKS*32-1:0] bank_words, output reg [3:0] digest, output strobe);
    reg [31:0] reduced;
    reg [7:0] folded;
    integer k;
    reg [31:0] combined;
    always @* begin
        combined=0;
        for (k=0;k<BANKS;k=k+1) combined = combined ^ bank_words[k*32 +: 32];
    end
    always @(posedge clk) begin
        reduced <= combined;
        folded <= reduced[31:24] ^ reduced[23:16] ^ reduced[15:8] ^ reduced[7:0];
        digest <= folded[7:4] ^ folded[3:0];
    end
    ODDR #(.DDR_CLK_EDGE("SAME_EDGE")) forward_clock(.C(clk),.CE(1'b1),.D1(1'b0),.D2(1'b1),.R(1'b0),.S(1'b0),.Q(strobe));
endmodule
