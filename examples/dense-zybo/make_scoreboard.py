"""Generate full-system expected outputs from the mathematical distance and gain model."""
import argparse
from pathlib import Path

BANKS = 13
LANES = 8
FIRST = 1088
COUNT = 2560
MASK = (1 << 32) - 1


def samples(channel):
    word = (0x7DB813F5 ^ (0x9E3779B9 * (channel + 1))) & MASK
    series = []
    for _ in range(FIRST + COUNT):
        series.append(word)
        word ^= (word << 13) & MASK
        word ^= word >> 17
        word ^= (word << 5) & MASK
    return series


def lane_result(series, t):
    # Six distance stages and four calibration stages. At output edge t, the
    # calibration's time-varying side inputs were sampled alongside the distance.
    query = series[t - 10]
    distance = sum((query ^ series[t - 10 - 1025 - tap]).bit_count() for tap in range(6))
    current = series[t - 4]
    delayed = series[t - 4 - 1024]
    operand = (distance << 7) | (current & 127)
    product = operand * (delayed & 0xffff)
    biased = ((product >> 8) + (current >> 16)) & 0x3ffff
    return (biased * (delayed >> 16)) & MASK


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    out = parser.parse_args().output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    all_samples = [samples(i) for i in range(BANKS * LANES)]
    check = out / "expected.hex"
    digests = []
    with check.open("w") as stream:
        for t in range(FIRST - 6, FIRST + COUNT):
            words = [lane_result(history, t) for history in all_samples]
            checksum = 0
            for word in words:
                checksum ^= word
            folded = 0
            for shift in range(0, 32, 4):
                folded ^= (checksum >> shift) & 15
            digests.append(folded)
            if t >= FIRST:
                stream.write(''.join(f'{w:08x}' for w in reversed(words)) + f'{digests[-7]:x}\n')
    probes = []
    for b in range(BANKS):
        for lane in range(LANES):
            i = b * LANES + lane
            probes.append(f"    assign result_bus[{32*i} +: 32] = dut.monitor_i.bank_{b}.inst.result[{lane}];")
    if any(x in str(check) for x in ('"', '\\', '\n')):
        raise ValueError("Unsupported character in simulation path")
    (out / "tb.sv").write_text(f"""`timescale 1ns/1ps
module tb;
    bit clk;
    wire [3:0] digest;
    wire strobe;
    monitor_wrapper dut(.*);
    always #4 clk = !clk;
    wire [{32*BANKS*LANES-1}:0] result_bus;
{chr(10).join(probes)}
    reg [{32*BANKS*LANES+3}:0] expected[0:{COUNT-1}];
    integer cycle, lane;
    initial begin
        $readmemh("{check}", expected);
        for (cycle=0; cycle<{FIRST+COUNT}; cycle=cycle+1) begin
            @(posedge clk); #1;
            if (cycle >= {FIRST}) begin
                if (strobe !== 1'b0) $fatal(1, "Forwarded strobe high after rising edge");
                if ({{result_bus, digest}} !== expected[cycle-{FIRST}]) begin
                    for (lane=0; lane<{BANKS*LANES}; lane=lane+1)
                        if (result_bus[lane*32 +: 32] !== expected[cycle-{FIRST}][4+lane*32 +: 32])
                            $fatal(1, "Mismatch in lane %0d at cycle %0d", lane, cycle);
                    $fatal(1, "Output digest mismatch at cycle %0d", cycle);
                end
                @(negedge clk); #1;
                if (strobe !== 1'b1) $fatal(1, "Forwarded strobe low after falling edge");
            end
        end
        $display("PASS: {COUNT} consecutive frames, {COUNT*BANKS*LANES} full 32-bit lane results, output digest and both forwarded strobe edges");
        $finish;
    end
endmodule
""")


if __name__ == "__main__":
    main()
