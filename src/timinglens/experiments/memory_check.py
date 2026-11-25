"""Exercise read-first semantics on Vivado's synthesized Xilinx primitive models."""
from pathlib import Path
from .process import execute


def scoreboard(memory):
    width, depth = memory.width, memory.depth
    wiring = ", ".join(f".{port}({signal})" for port,signal in
                       zip(memory.ports, ("clk","we","addr","din","dout")))
    return f"""`timescale 1ns/1ps
module memory_check;
  reg clk=0, we=0;
  always #4 clk=!clk;
  reg [{(depth-1).bit_length()-1}:0] addr;
  reg [{width-1}:0] din, expected, reference [0:{depth-1}];
  wire [{width-1}:0] dout;
  timinglens_memory dut({wiring});
  integer i;
  reg [63:0] state=64'hd1b54a32d192ed03;
  initial begin
    #160;
    for(i=0;i<{3*depth+4096};i=i+1) begin
      @(negedge clk);
      state=state^(state<<13); state=state^(state>>7); state=state^(state<<17);
      addr=(i<{3*depth}) ? i%{depth} : state;
      we=(i<{2*depth}) ? 1 : (i<{3*depth}) ? 0 : state[16];
      din=state^(state>>19); expected=reference[addr];
      if(we) reference[addr]=din;
      @(posedge clk); #1;
      if(i>={depth} && dout!==expected) $fatal(1,"RAM mismatch at %0d",i);
    end
    $display("TIMINGLENS_RAM_PASS {2*depth+4096} reads");
    $finish;
  end
endmodule
"""


def simulate(memory, source, style, part, directory, script, vivado, cancel, log):
    directory.mkdir(parents=True)
    bench = directory/"memory_check.sv"
    bench.write_text(scoreboard(memory))
    tools = Path(vivado).resolve().parent
    commands = ((vivado, "-mode", "batch", "-notrace", "-source", script, "-tclargs", source, part, memory.module, style),
                (tools/"xvlog", "--sv", "model.v", bench, tools.parent/"data/verilog/src/glbl.v"),
                (tools/"xelab", "--mt", "2", "-L", "unisims_ver", "work.glbl", "work.memory_check", "-s", "check"),
                (tools/"xsim", "check", "-runall"))
    for tool, *args in commands:
        transcript = directory/(Path(tool).name + "-output.log")
        execute([tool,*args], directory, transcript, cancel, 900, log)
    if f"TIMINGLENS_RAM_PASS {2*memory.depth+4096} reads" not in transcript.read_text().splitlines():
        raise ValueError(f"Memory simulation did not confirm read-first behavior. See {transcript}")
    return transcript
