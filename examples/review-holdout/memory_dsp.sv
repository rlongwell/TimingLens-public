// Dedicated RAM and DSP evidence does not establish legal added latency.
module memory_dsp(input logic clk, write_enable, input logic [8:0] address,
                  input logic [15:0] data, coefficient,
                  output logic [31:0] product);
    (* ram_style = "block" *) logic [15:0] storage [0:511];
    logic [15:0] read_data;
    always_ff @(posedge clk) begin
        if(write_enable) storage[address] <= data;
        read_data <= storage[address];
        product <= read_data * coefficient;
    end
endmodule
