// Four-cycle interface. Retain full precision through the first multiply,
// round down at bit eight, apply the 18-bit modular bias and rescale.
module calibration(input clk, input [15:0] a, b, bias, scale, output reg [31:0] result);
    wire [31:0] product = a * b;
    wire [17:0] adjusted = product[25:8] + {2'b0, bias};
    reg [31:0] stage0, stage1, stage2;
    always @(posedge clk) begin
        stage0 <= adjusted * scale;
        stage1 <= stage0;
        stage2 <= stage1;
        result <= stage2;
    end
endmodule
