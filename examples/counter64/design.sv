module counter(input bit clk, rst, accept, load,
    input bit [3:0] amount, input bit [63:0] initial_value,
    output bit [63:0] remaining);
always_ff @(posedge clk) begin
    if (rst) remaining <= 0;
    else if (load) remaining <= initial_value;
    else if (accept && (remaining > amount)) remaining <= remaining - amount;
end
endmodule
