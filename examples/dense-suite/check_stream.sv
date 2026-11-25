// Independent transaction scoreboard for the dense examples, including the output pins.
`timescale 1ns/1ps
module check_stream;
    reg clk = 0;
    always #4 clk = ~clk;
    wire [3:0] digest;
    wire strobe;
`ifdef IQ_POWER
    iq_power dut(clk, digest, strobe);
    localparam BANKS=9, LATENCY=4;
`elsif TONE_CURVE
    tone_curve dut(clk, digest, strobe);
    localparam BANKS=13, LATENCY=5;
`else
    pixel_gain dut(clk, digest, strobe);
    localparam BANKS=14, LATENCY=1;
`endif
    integer cycle = 0;
    always @(posedge clk) cycle <= cycle+1;
    wire [31:0] samples [0:8*BANKS-1];
    genvar b, l;
    generate for (b=0;b<BANKS;b=b+1) begin : banks
        for (l=0;l<8;l=l+1) begin : lanes
`define CHANNEL dut.bank[b].channel[l]
`ifdef IQ_POWER
            wire [63:0] i_word = `CHANNEL.compute.i_sample;
            wire [63:0] q_word = `CHANNEL.compute.q_sample;
            wire [63:0] power = i_word*i_word + q_word*q_word;
            wire [31:0] result = (power >> 17) * `CHANNEL.compute.weight;
`elsif TONE_CURVE
            wire [63:0] x = `CHANNEL.compute.pixel;
            wire [63:0] slope = ((x * `CHANNEL.compute.quadratic) >> 16) + `CHANNEL.compute.linear;
            wire [31:0] result = ((slope * x) >> 1) + `CHANNEL.compute.black;
`else
            wire [35:0] product = `CHANNEL.compute.sample_in * `CHANNEL.compute.gain;
            wire [31:0] result = product[31:0] ^ product[35:32];
`endif
            reg [31:0] expected [0:LATENCY-1];
            integer stage;
            always @(posedge clk) begin
                expected[0] <= result;
                for (stage=1;stage<LATENCY;stage=stage+1) expected[stage] <= expected[stage-1];
            end
            assign samples[8*b+l] = expected[LATENCY-1];
            always @(negedge clk)
                if (cycle > 1100 && ($isunknown(expected[LATENCY-1]) || `CHANNEL.value !== expected[LATENCY-1]))
                    $fatal(1,"Lane %0d cycle %0d: actual %h expected %h",8*b+l,cycle,`CHANNEL.value,expected[LATENCY-1]);
`undef CHANNEL
        end
    end endgenerate

    reg [3:0] signature[0:4];
    reg [31:0] combined;
    reg [3:0] nibble;
    integer k;
    always @(posedge clk) begin
        combined = 0;
        for (k=0;k<8*BANKS;k=k+1) combined = combined ^ samples[k];
        nibble = 0;
        for (k=0;k<8;k=k+1) nibble = nibble ^ combined[k*4+:4];
        signature[0] <= nibble;
        for (k=1;k<5;k=k+1) signature[k] <= signature[k-1];
    end
    initial begin
        repeat (1100) @(negedge clk);
        repeat (256) begin
            @(negedge clk);
            if ($isunknown(signature[4]) || digest !== signature[4]) $fatal(1,"Output mismatch at cycle %0d",cycle);
        end
        $display("TIMINGLENS_STREAM_PASS %0d lane transactions, 256 output samples",BANKS*8*256);
        $finish;
    end
endmodule
