`timescale 1ns/1ps
module tb;
    bit clk;
    wire status;
    telemetry_fabric dut(.clk(clk), .status(status));
    always #2 clk = !clk;

    logic [255:0] frames[$], sent;
    logic [31:0] history[8][4], reference[8][4], winner, previous_winner, previous_energy;
    logic [31:0] first, adjusted, energy;
    logic signed [15:0] x, w;
    logic signed [31:0] term;
    int emitted, delivered, checked, status_changes, cycles, overlaps, terms;
    logic prev_status;
    always @(posedge clk) begin
        // Scoreboard across the actual FIFO and register slice in the generated BD.
        if (dut.source_samples_M_AXIS_TVALID && dut.source_samples_M_AXIS_TREADY) begin
            frames.push_back(dut.source_samples_M_AXIS_TDATA);
            emitted++;
        end
        if (dut.stream_slice_M_AXIS_TVALID && dut.stream_slice_M_AXIS_TREADY) begin
            if (frames.size() == 0) $fatal(1, "Unexpected AXIS output");
            sent = frames.pop_front();
            if (dut.stream_slice_M_AXIS_TDATA !== sent) $fatal(1, "AXIS ordering or data error");
            delivered++;
        end
        for (int lane = 0; lane < 8; lane++) begin
            if (cycles > 60 && dut.metrics_concat_dout[lane*32 +: 32] !== reference[lane][3])
                $fatal(1, "Lane %0d differs from reference in cycle %0d", lane, cycles);
            for (int age = 3; age > 0; age--) begin
                history[lane][age] = history[lane][age-1];
                reference[lane][age] = reference[lane][age-1];
            end
            history[lane][0] = dut.unpack_frame[lane*32 +: 32];
            reference[lane][0] = 0;
            for (int age = 0; age < 4; age++) begin
                x = history[lane][age][15:0];
                w = history[lane][3-age][31:16];
                term = x * w;
                reference[lane][0] = reference[lane][0] + term;
            end
        end
        if (cycles > 60) begin
            terms = 0;
            winner = 0;
            for (int k = 15; k >= 0; k--) begin
                if (dut.metrics_concat_dout[k*16 +: 16] > dut.events_threshold) begin
                    if (terms == 0) winner = dut.metrics_concat_dout[(k/2)*32 +: 32];
                    terms++;
                end
            end
            first = dut.lane_0_metric[15:0] * dut.lane_1_metric[15:0];
            adjusted = ((first >> 8) & 'h3ffff) + dut.lane_2_metric[31:16];
            energy = (adjusted & 'h3ffff) * dut.lane_2_metric[15:0];
            if ($isunknown({dut.metrics_concat_dout, dut.events_threshold, status}) ||
                dut.selector_winner !== winner || dut.energy_energy !== energy)
                $fatal(1, "Event data mismatch in cycle %0d", cycles);
            if (cycles > 61 && (dut.events.inst.selected_q !== previous_winner ||
                                dut.events.inst.energy_q !== previous_energy))
                $fatal(1, "Event capture mismatch");
            previous_winner = winner;
            previous_energy = energy;
            if (terms > 1) overlaps++;
            if (status != prev_status) status_changes++;
            checked++;
        end
        prev_status = status;
        cycles++;
        if (cycles == 640) begin
            if (delivered < 450 || status_changes < 100 || overlaps < 100) $fatal(1, "Insufficient activity");
            $display("PASS telemetry BD: %0d input frames, %0d ordered output frames, %0d event and eight-lane checks, %0d overlapping selections, %0d status transitions", emitted, delivered, checked, overlaps, status_changes);
            $finish;
        end
    end
endmodule
