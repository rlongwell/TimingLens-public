// Streaming pattern-distance monitor. Each bank processes eight independent
// 32-bit streams. Deterministic local sources make full-rate bring-up repeatable.
module monitor_bank #(parameter integer BANK_ID = 0)(
    input clk, output reg [31:0] digest
);
    wire [31:0] result [0:7];
    reg [31:0] pair0, pair1;
    genvar i;
    generate for (i = 0; i < 8; i = i + 1) begin : lanes
        localparam [31:0] SEED = 32'h7db813f5 ^ (32'h9e3779b9 * (8*BANK_ID+i+1));
        reg [31:0] stream = SEED;
        wire [31:0] x = stream ^ (stream << 13);
        wire [31:0] y = x ^ (x >> 17);
        always @(posedge clk) stream <= y ^ (y << 5);
        distance_lane lane(.clk(clk), .sample(stream), .result(result[i]));
    end endgenerate
    always @(posedge clk) begin
        pair0 <= result[0] ^ result[1] ^ result[2] ^ result[3];
        pair1 <= result[4] ^ result[5] ^ result[6] ^ result[7];
        digest <= pair0 ^ pair1;
    end
endmodule

module distance_lane(input clk, input [31:0] sample, output [31:0] result);
    // Read-first circular buffer: the read port supplies the sample from 1024 ticks ago.
    (* ram_style = "block" *) reg [31:0] history [0:1023];
    reg [9:0] address = 0;
    reg [31:0] prior, taps [0:5], now_q;
    integer n;
    always @(posedge clk) begin
        prior <= history[address];
        history[address] <= sample;
        address <= address + 1'b1;
        taps[0] <= prior;
        for (n=1; n<6; n=n+1) taps[n] <= taps[n-1];
        now_q <= sample;
    end

    // One distance per historical tap. Bound every adder level with registers.
    function [2:0] count4(input [3:0] bits);
        count4 = {2'b0,bits[0]} + {2'b0,bits[1]} + {2'b0,bits[2]} + {2'b0,bits[3]};
    endfunction
    wire [5:0] tap_score [0:5];
    genvar t, k;
    generate for (t=0; t<6; t=t+1) begin : measure
        reg [31:0] changed;
        reg [2:0] nibble [0:7];
        reg [4:0] low, high;
        reg [5:0] total;
        always @(posedge clk) changed <= now_q ^ taps[t];
        for (k=0; k<8; k=k+1) begin : chunks
            always @(posedge clk) nibble[k] <= count4(changed[4*k +: 4]);
        end
        always @(posedge clk) begin
            low <= nibble[0]+nibble[1]+nibble[2]+nibble[3];
            high <= nibble[4]+nibble[5]+nibble[6]+nibble[7];
            total <= low+high;
        end
        assign tap_score[t] = total;
    end endgenerate
    reg [7:0] first_three, last_three;
    reg [8:0] distance_q;
    always @(posedge clk) begin
        first_three <= tap_score[0]+tap_score[1]+tap_score[2];
        last_three <= tap_score[3]+tap_score[4]+tap_score[5];
        distance_q <= first_three + last_three;
    end
    calibration calibrate(.clk(clk), .a({distance_q,now_q[6:0]}), .b(prior[15:0]),
        .bias(now_q[31:16]), .scale(prior[31:16]), .result(result));
endmodule

module digest_output(input clk, input [415:0] banks,
                     output reg [3:0] digest, output strobe);
    reg [31:0] group0, group1, group2, group3, word_q;
    reg [7:0] folded;
    always @(posedge clk) begin
        group0 <= banks[31:0] ^ banks[63:32] ^ banks[95:64] ^ banks[127:96];
        group1 <= banks[159:128] ^ banks[191:160] ^ banks[223:192] ^ banks[255:224];
        group2 <= banks[287:256] ^ banks[319:288] ^ banks[351:320] ^ banks[383:352];
        group3 <= banks[415:384];
        word_q <= group0 ^ group1 ^ group2 ^ group3;
        folded <= word_q[7:0] ^ word_q[15:8] ^ word_q[23:16] ^ word_q[31:24];
        digest <= folded[3:0] ^ folded[7:4];
    end
    // Forward the falling fabric edge as the rising receiver sampling edge.
    ODDR #(.DDR_CLK_EDGE("SAME_EDGE")) forward_clock(
        .C(clk), .CE(1'b1), .D1(1'b0), .D2(1'b1), .R(1'b0), .S(1'b0), .Q(strobe));
endmodule
