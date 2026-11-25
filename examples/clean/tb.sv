module tb;
    logic clk = 0;
    logic [7:0] data, result;
    clean dut (.*);
    always #5 clk = !clk;

    initial begin
        logic [7:0] previous;
        previous = 0;
        for (int i = 0; i < 16; i++) begin
            @(negedge clk);
            data = 8'(i * 19);
            @(posedge clk);
            #1;
            if (i > 0 && result !== (previous ^ 8'hA5)) $fatal(1, "reference latency or data");
            previous = data;
        end
        $finish;
    end
endmodule
