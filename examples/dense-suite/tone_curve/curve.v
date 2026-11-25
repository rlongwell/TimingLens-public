// Streaming fixed-point quadratic tone curve in Horner form.
module curve(input clk, input [15:0] pixel, quadratic, linear, black, output reg [31:0] corrected);
    wire [31:0] ax = quadratic * pixel;
    wire [16:0] slope = {1'b0,ax[31:16]} + {1'b0,linear};
    wire [32:0] bent = slope * pixel;
    reg [31:0] d0, d1, d2, d3;
    always @(posedge clk) begin
        d0 <= bent[32:1] + {16'b0,black};
        d1 <= d0;
        d2 <= d1;
        d3 <= d2;
        corrected <= d3;
    end
endmodule
