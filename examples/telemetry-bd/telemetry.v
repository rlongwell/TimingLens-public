// A self-contained eight-channel telemetry fabric with a registered status output.
// A sample word contains a signed measurement and a signed weight (16 bits each).
module power_on(input clk, output resetn);
    reg [7:0] startup = 0;
    always @(posedge clk) startup <= {startup[6:0], 1'b1};
    assign resetn = startup[7];
endmodule

module sample_source(
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF M_AXIS, ASSOCIATED_RESET resetn" *)
    input clk,
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *) input resetn,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TDATA" *) output [255:0] m_axis_tdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TVALID" *) output m_axis_tvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TREADY" *) input m_axis_tready
);
    assign m_axis_tvalid = resetn;
    genvar lane;
    generate for (lane = 0; lane < 8; lane = lane + 1) begin : channel
        reg [31:0] sample;
        always @(posedge clk)
            if (!resetn) sample <= 32'h3ba5c871 ^ (32'h19573a21 * lane);
            else if (m_axis_tready)
                sample <= {sample[30:0], sample[31] ^ sample[21] ^ sample[1] ^ sample[0]};
        assign m_axis_tdata[lane*32 +: 32] = sample;
    end endgenerate
endmodule

module frame_unpack(
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF S_AXIS, ASSOCIATED_RESET resetn" *)
    input clk,
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *) input resetn,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TDATA" *) input [255:0] s_axis_tdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TVALID" *) input s_axis_tvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TREADY" *) output s_axis_tready,
    output reg [255:0] frame
);
    assign s_axis_tready = resetn;
    always @(posedge clk)
        if (s_axis_tvalid && s_axis_tready) frame <= s_axis_tdata;
        else frame <= 0;
endmodule

// Sliding four-term correlation of observed samples with the reversed weight window.
module correlation_lane(input clk, input [31:0] sample_word, output reg [31:0] metric);
    reg signed [15:0] samples [0:3];
    reg signed [15:0] weights [0:3];
    reg signed [31:0] product [0:3];
    reg [31:0] pair_a, pair_b;
    integer j;
    always @(posedge clk) begin
        samples[0] <= sample_word[15:0];
        weights[0] <= sample_word[31:16];
        for (j = 1; j < 4; j = j + 1) begin
            samples[j] <= samples[j-1];
            weights[j] <= weights[j-1];
        end
        for (j = 0; j < 4; j = j + 1)
            product[j] <= samples[j] * weights[3-j];
        pair_a <= product[0] + product[1];
        pair_b <= product[2] + product[3];
        metric <= pair_a + pair_b;
    end
endmodule

// Examine sixteen half-words. On multiple threshold crossings the highest half-word
// index wins and supplies its channel's complete metric.
module priority_pick(input [255:0] metrics, input [15:0] threshold, output reg [31:0] winner);
    integer halfword;
    always @* begin
        winner = 0;
        for (halfword = 0; halfword < 16; halfword = halfword + 1)
            if (metrics[halfword*16 +: 16] > threshold)
                winner = metrics[(halfword/2)*32 +: 32];
    end
endmodule

// Two dependent products and an offset intentionally share one clock period.
module energy_mix(input [31:0] a, b, c, output [31:0] energy);
    wire [31:0] first_product = a[15:0] * b[15:0];
    wire [17:0] adjusted = first_product[25:8] + {2'b00, c[31:16]};
    assign energy = adjusted * c[15:0];
endmodule

module event_log(input clk, input [31:0] winner, energy,
                 output [15:0] threshold, output reg status);
    reg [31:0] selected_q, energy_q;
    // A small local registered control path provides a comparison endpoint.
    reg [7:0] phase = 8'hc5;
    always @(posedge clk) begin
        phase <= {phase[6:0], phase[7] ^ phase[5] ^ phase[4] ^ phase[3]};
        selected_q <= winner;
        energy_q <= energy;
        status <= ^{selected_q, energy_q, phase};
    end
    assign threshold = {phase, 8'h80};
endmodule
