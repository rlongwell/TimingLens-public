module deep_kernel #(parameter N = 16) (
    input logic clk, input logic [N:0] data, output logic result
);
    logic [N:0] launch;
    (* keep = "true" *) wire [N:0] chain;
    assign chain[0] = launch[0];
    for (genvar i = 1; i <= N; i++) begin : stage
        if ((i % 2) == 1)
            assign chain[i] = ~(chain[i-1] ^ launch[i]);
        else
            assign chain[i] = chain[i-1] & launch[i];
    end
    always_ff @(posedge clk) begin
        launch <= data;
        result <= chain[N];
    end
endmodule

module deep(input logic clk, input logic [16:0] data, output logic result);
    (* keep_hierarchy = "yes" *) deep_kernel u_kernel (.*);
endmodule
