// Channel-local empirical amplitude ranks over two 16-sample histories.
// Register comparison bits and reduction levels so each window advances every tick.
module rank_weight(input clk, input [31:0] iq, output reg [15:0] weight);
    reg [31:0] history [0:15];
    reg [15:0] i_lower, q_lower;
    integer n;
    always @(posedge clk) begin
        history[0] <= iq;
        for (n=1; n<16; n=n+1) history[n] <= history[n-1];
        for (n=0; n<16; n=n+1) begin
            i_lower[n] <= iq[15:0] > history[n][15:0];
            q_lower[n] <= iq[31:16] > history[n][31:16];
        end
    end
    genvar g;
    wire [11:0] i_counts, q_counts;
    generate for (g=0; g<4; g=g+1) begin : count
        reg [2:0] i_sum, q_sum;
        always @(posedge clk) begin
            i_sum <= i_lower[4*g]+i_lower[4*g+1]+i_lower[4*g+2]+i_lower[4*g+3];
            q_sum <= q_lower[4*g]+q_lower[4*g+1]+q_lower[4*g+2]+q_lower[4*g+3];
        end
        assign i_counts[g*3+:3]=i_sum;
        assign q_counts[g*3+:3]=q_sum;
    end endgenerate
    reg [4:0] i_rank, q_rank;
    always @(posedge clk) begin
        i_rank <= i_counts[2:0]+i_counts[5:3]+i_counts[8:6]+i_counts[11:9];
        q_rank <= q_counts[2:0]+q_counts[5:3]+q_counts[8:6]+q_counts[11:9];
        weight <= {i_rank,3'b000,q_rank,3'b000};
    end
endmodule
