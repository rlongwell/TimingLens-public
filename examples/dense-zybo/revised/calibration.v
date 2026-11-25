// Keep the four-cycle interface. Capture RAM-derived operands before arithmetic
// and carry each sample's bias and scale alongside the intermediate result.
module calibration(input clk, input [15:0] a, b, bias, scale, output reg [31:0] result);
    reg [15:0] a1, b1, bias1, scale1;
    reg [31:0] product2;
    reg [15:0] bias2, scale2, scale3;
    reg [17:0] adjusted3;
    always @(posedge clk) begin
        a1 <= a;
        b1 <= b;
        bias1 <= bias;
        scale1 <= scale;

        product2 <= a1 * b1;
        bias2 <= bias1;
        scale2 <= scale1;

        adjusted3 <= product2[25:8] + {2'b0, bias2};
        scale3 <= scale2;

        result <= adjusted3 * scale3;
    end
endmodule
