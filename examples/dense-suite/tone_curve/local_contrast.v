// Sum of absolute differences across a 9-pixel horizontal neighborhood.
module local_contrast(input clk, input [11:0] pixel, output reg [15:0] pedestal);
    reg [11:0] past [0:8];
    wire [107:0] magnitudes;
    genvar t;
    generate for (t=0;t<9;t=t+1) begin : tap
        if (t==0) always @(posedge clk) past[t]<=pixel;
        else always @(posedge clk) past[t]<=past[t-1];
        reg [12:0] difference;
        reg [11:0] magnitude;
        always @(posedge clk) begin
            difference <= {1'b0,pixel}-{1'b0,past[t]};
            magnitude <= difference[12] ? -difference[11:0] : difference[11:0];
        end
        assign magnitudes[12*t+:12] = magnitude;
    end endgenerate
    wire [41:0] groups;
    genvar g;
    generate for (g=0;g<3;g=g+1) begin : neighbors
        reg [13:0] sum;
        always @(posedge clk) sum <= magnitudes[36*g+:12]+magnitudes[36*g+12+:12]+magnitudes[36*g+24+:12];
        assign groups[14*g+:14] = sum;
    end endgenerate
    always @(posedge clk) pedestal <= groups[13:0]+groups[27:14]+groups[41:28];
endmodule
