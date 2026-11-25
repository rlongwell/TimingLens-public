// Unsigned baseband I/Q power, with per-channel window weighting.
module energy(input clk, input [15:0] i_sample, q_sample, weight, output reg [31:0] level);
    wire [31:0] ii = i_sample * i_sample;
    wire [31:0] qq = q_sample * q_sample;
    wire [32:0] power_sum = {1'b0,ii} + {1'b0,qq};
    reg [31:0] d0, d1, d2;
    always @(posedge clk) begin
        d0 <= power_sum[32:17] * weight;
        d1 <= d0;
        d2 <= d1;
        level <= d2;
    end
endmodule
