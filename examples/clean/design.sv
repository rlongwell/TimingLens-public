module clean(input logic clk, input logic [7:0] data, output logic [7:0] result);
    logic [7:0] launch;
    always_ff @(posedge clk) begin
        launch <= data;
        result <= launch ^ 8'hA5;
    end
endmodule
