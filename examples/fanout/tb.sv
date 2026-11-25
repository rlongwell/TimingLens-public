module tb;
    logic clk = 0, control = 0;
    logic [7:0] seed = 0, result;
    fanout dut (.*);
    always #5 clk = !clk;

    task automatic tick(input logic drive, input logic [7:0] tag, output logic [7:0] measured);
        @(negedge clk);
        control = drive;
        seed = tag;
        @(posedge clk);
        #1;
        measured = result;
    endtask

    initial begin
        logic [7:0] measured;
        tick(0, 0, measured);
        tick(1, 3, measured);
        tick(0, 7, measured);
        tick(0, 0, measured);
        if (measured !== 8'h08) $fatal(1, "lane 3 should be enabled");
        tick(1, 3, measured);
        tick(0, 0, measured);
        tick(0, 0, measured);
        if (measured !== 8'h00) $fatal(1, "lane 3 should have toggled off");
        $finish;
    end
endmodule
