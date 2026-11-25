module fanout #(parameter N=192)(
    input logic clk, control,
    input logic [7:0] seed,
    output logic [7:0] result
);
    (* DONT_TOUCH = "true" *) logic control_q;
    logic [7:0] seed_q;
    wire [N-1:0] values;
    always_ff @(posedge clk) begin
        seed_q <= seed;
        control_q <= control;
    end
    for (genvar i=0; i<N; i++) begin : lane
        (* DONT_TOUCH = "true" *) logic active;
        localparam logic [7:0] TAG = 8'(i);
        always_ff @(posedge clk)
            if (control_q) active <= (seed_q == TAG) ^ active;
        assign values[i] = active;
    end
    for (genvar j=0; j<8; j++) begin : lane_reduce
        wire [N/8-1:0] group;
        for (genvar k=0; k<N/8; k++) assign group[k] = values[k*8+j];
        always_ff @(posedge clk) result[j] <= ^group;
    end
endmodule
