// Synchronous, read-first sample store with a write enable.
module queue_store(input wire clk, input wire we, input wire [5:0] addr,
                   input wire [7:0] din, output reg [7:0] dout);
    (* ram_style = "block" *) reg [7:0] samples [0:63];
    always @(posedge clk) begin
        if (we) samples[addr] <= din;
        dout <= samples[addr];
    end
endmodule
