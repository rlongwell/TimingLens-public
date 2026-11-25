module tb;
    logic clk = 0;
    logic [15:0] request, data;
    logic result;
    priority_top dut (.*);
    always #5 clk = !clk;

    task automatic check(input logic [15:0] req, val, input logic winner);
        @(negedge clk);
        request = req;
        data = val;
        repeat (2) @(posedge clk);
        #1;
        if (result !== winner) $fatal(1, "request=%h data=%h expected=%b", req, val, winner);
    endtask

    initial begin
        check(16'h0000, 16'hFFFF, 0);
        check(16'h0001, 16'h0001, 1);
        check(16'h8001, 16'h0001, 0);
        check(16'h8001, 16'h8000, 1);
        check(16'h0304, 16'h0104, 0);
        check(16'h0304, 16'h0200, 1);
        $finish;
    end
endmodule
