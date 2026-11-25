// Held-out investigation design. Stages preserve beat ownership under stalls.
module stream_source(input logic aclk, aresetn, valid, ready,
                     input logic [7:0] data,
                     output logic M_AXIS_tvalid, output logic [7:0] M_AXIS_tdata);
    always_ff @(posedge aclk) begin
        if (!aresetn) M_AXIS_tvalid <= 0;
        else if (ready) begin
            M_AXIS_tvalid <= valid;
            if (valid) M_AXIS_tdata <= data;
        end
    end
endmodule

module stream_sink(input logic aclk, aresetn, valid, ready,
                   input logic [7:0] data, input logic [7:0] key,
                   output logic S_AXIS_tvalid, output logic [7:0] S_AXIS_tdata);
    wire [7:0] mix [0:8];
    assign mix[0]=data;
    for(genvar i=0;i<8;i++) begin:stage
        assign mix[i+1] = {mix[i][6:0],mix[i][7]} + (mix[i] ^ key);
    end
    always_ff @(posedge aclk) begin
        if (!aresetn) S_AXIS_tvalid <= 0;
        else if (ready) begin
            S_AXIS_tvalid <= valid;
            if (valid) S_AXIS_tdata <= mix[8];
        end
    end
endmodule

module stream_top(input logic clk, resetn, valid, ready,
                  input logic [7:0] data, key,
                  output logic input_ready, output logic output_valid,
                  output logic [7:0] output_data);
    logic tx_valid, rx_valid;
    logic [7:0] tx_data,rx_data;
    wire rx_ready = !rx_valid || ready;
    wire tx_ready = !tx_valid || rx_ready;
    stream_source tx(clk, resetn, valid, tx_ready, data, tx_valid, tx_data);
    stream_sink rx(clk, resetn, tx_valid, rx_ready, tx_data, key, rx_valid, rx_data);
    assign input_ready=tx_ready;
    assign output_valid=rx_valid;
    assign output_data=rx_data;
endmodule
