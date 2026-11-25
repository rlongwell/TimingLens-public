module priority_select #(
    parameter N = 16
)(input logic clk, input logic [N-1:0] request, data,
  output logic result);
    logic [N-1:0] req_q, data_q;
    (* keep = "true" *) wire [N:0] selected;
    assign selected[0] = 1'b0;
    for (genvar i=0; i<N; i++) begin : grant
        // A later asserted request takes precedence over all earlier grants.
        assign selected[i+1] = req_q[i] ? data_q[i] : selected[i];
    end
    always_ff @(posedge clk) begin
        req_q <= request;
        data_q <= data;
        result <= selected[N];
    end
endmodule

module priority_top(input logic clk, input logic [15:0] request, data,
                    output logic result);
    (* keep_hierarchy = "yes" *) priority_select u_select (.*);
endmodule
