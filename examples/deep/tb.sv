module tb;
    logic clk = 0;
    logic [16:0] data;
    logic result;
    deep dut (.*);
    always #5 clk = !clk;

    function automatic logic expected(input logic [16:0] word);
        logic state;
        state = word[0];
        for (int i = 1; i <= 16; i++)
            state = i % 2 != 0 ? ~(state ^ word[i]) : state & word[i];
        return state;
    endfunction

    initial begin
        logic prior;
        prior = 0;
        for (int i = 0; i < 48; i++) begin
            @(negedge clk);
            data = i % 3 == 0 ? '1 : 17'((i * 3203) ^ 93);
            @(posedge clk);
            #1;
            if (i > 0 && result !== prior) $fatal(1, "deep result at sample %0d", i);
            prior = expected(data);
        end
        $finish;
    end
endmodule
