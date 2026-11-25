#!/usr/bin/env python3
"""Reproduce two expression experiments in a new output directory; no hardware.

Run with the repository venv. --with-vivado performs four sequential OOC
implementations using two threads. No supplied project Tcl is executed.
"""
import argparse
from dataclasses import asdict
from difflib import unified_diff
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import time

from timinglens import analyze
from timinglens.analysis.rtl_fixes import factored
from timinglens.rtl.semantics import SemanticIndex
from timinglens.rtl.syntax import build_index
from timinglens.service import export_result
from timinglens.timing.models import Source
from timinglens.vivado.decode import decode

ROOT = Path(__file__).resolve().parents[1]


def design(width, operator):
    return f'''module counter(input bit clk, rst, accept, load,
    input bit [3:0] amount, input bit [{width-1}:0] initial_value,
    output bit [{width-1}:0] remaining);
always_ff @(posedge clk) begin
    if (rst) remaining <= 0;
    else if (load) remaining <= initial_value;
    else if (accept && (remaining {operator} amount)) remaining <= remaining - amount;
end
endmodule
'''


XDC = '''create_clock -name clk -period 2.000 [get_ports clk]
set data_inputs [get_ports -filter {DIRECTION == IN && NAME != clk}]
set_input_delay -clock clk -max 0.300 $data_inputs
set_input_delay -clock clk -min 0.100 $data_inputs
set_output_delay -clock clk -max 0.300 [all_outputs]
set_output_delay -clock clk -min -0.100 [all_outputs]
'''

TCL = '''set_param general.maxThreads 2
read_verilog -sv design.sv
read_xdc timing.xdc
synth_design -top counter -part xc7z020clg400-1 -mode out_of_context
opt_design
place_design -directive Default
route_design -directive Default
write_checkpoint routed.dcp
report_utilization -file utilization.rpt
report_drc -file drc.rpt
report_route_status -file route_status.rpt
source extract.tcl
tl::collect demo [file normalize design.sv] counter counter {} 80 3 0
set stats [open metrics.tsv w]
foreach pattern {LUT* FD* RAMB* DSP*} {
    puts $stats "$pattern\t[llength [get_cells -hier -filter [format {REF_NAME =~ %s && IS_PRIMITIVE == 1} $pattern]]]"
}
foreach severity {Error {Critical Warning} Warning} {
    puts $stats "$severity\t[llength [get_drc_violations -quiet -filter [format {SEVERITY == \"%s\"} $severity]]]"
}
close $stats
exit
'''


def command(args, cwd, name, timeout):
    start = time.monotonic()
    with (cwd/name).open('w') as log:
        p = subprocess.run(args, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
    return {'command': args, 'returncode': p.returncode, 'seconds': round(time.monotonic()-start, 3), 'log': str(cwd/name)}


def simulate(folder, before, after, width):
    folder.mkdir()
    (folder/'before.sv').write_text(before.replace('module counter(', 'module counter_before('))
    (folder/'after.sv').write_text(after.replace('module counter(', 'module counter_after('))
    (folder/'tb.sv').write_text(f'''module tb;
bit clk=0, rst=1, accept=0, load=0;
bit [3:0] amount=0;
bit [{width-1}:0] initial_value=0;
wire [{width-1}:0] a,b;
bit [63:0] rng=64'h923456789abcdef1;
counter_before before_dut(clk,rst,accept,load,amount,initial_value,a);
counter_after after_dut(clk,rst,accept,load,amount,initial_value,b);
task tick;
  #1 clk=1; #1;
  if (a !== b) $fatal(1,"sequential mismatch a=%h b=%h",a,b);
  clk=0;
endtask
initial begin
  tick(); rst=0;
  for (int n=0;n<16;n++) begin
    for (int k=0;k<6;k++) begin
      load=1; accept=0; amount=4'(n);
      case(k)
        0: initial_value=0;
        1: initial_value={width}'(n);
        2: initial_value={width}'(n+1);
        3: initial_value={width}'(n-1);
        4: initial_value='1;
        5: initial_value={width}'(16);
      endcase
      tick(); load=0; accept=1; tick(); accept=0; tick();
    end
  end
  for(int i=0;i<10000;i++) begin
    rng=rng^(rng<<13); rng=rng^(rng>>7); rng=rng^(rng<<17);
    initial_value={width}'(rng); amount=rng[3:0];
    rst=(i%97==0); load=rng[5]; accept=rng[7]; tick();
  end
  $display("PASS: 10289 sequential comparisons including reset, stalls, load and boundaries");
  $finish;
end
endmodule
''')
    # These kernels deliberately exercise implicit unsigned extension. Retain
    # every other warning as a failure; the subtraction is unchanged by the edit.
    build = command(['verilator','--binary','--timing','-Wno-WIDTHEXPAND','-j','2','--top-module','tb','--Mdir','obj',
                     'before.sv','after.sv','tb.sv'], folder, 'build.log', 180)
    run = command([str(folder/'obj/Vtb')], folder, 'simulation.log', 30) if not build['returncode'] else None
    return {'build': build, 'run': run, 'scope': 'Finite cycle comparison on these binary counter kernels; not arbitrary formal equivalence.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--with-vivado', action='store_true')
    parser.add_argument('--vivado', default='/opt/amd/xilinx/Vivado/2024.2/bin/vivado')
    args = parser.parse_args()
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=False)
    manifest = {'device': 'xc7z020clg400-1', 'clock_ns': 2.0, 'mode':'out_of_context',
                'directives': {'opt':'Default','place':'Default','phys_opt':'not run','route':'Default'},
                'threads':2, 'seed':'No seed override; identical default tool settings, one run per variant.',
                'dfx':'Not applicable to these OOC kernels; no static/RM compatibility claim.', 'experiments':[]}
    for name, width, op in [('unsigned32_ge',32,'>='), ('unsigned64_gt',64,'>')]:
        folder = output/name; folder.mkdir()
        before = design(width,op)
        index = build_index([Source(path='design.sv',text=before)])
        reg, reason = SemanticIndex(index,'counter').resolve(index.modules['counter'][0],None,'remaining')
        assert reg and not reason
        c = reg.enable_decisions[0].comparisons[0]; replacement = factored(c)
        data = before.encode(); after = (data[:c.span.start]+replacement.encode()+data[c.span.end:]).decode()
        (folder/'change.patch').write_text(''.join(unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/design.sv',tofile='b/design.sv')))
        entry = {'name':name,'expression':asdict(c),'replacement':replacement,
                 'simulation':simulate(folder/'simulation',before,after,width),'variants':{}}
        manifest['experiments'].append(entry)
        for variant, text in [('before',before),('after',after)]:
            work=folder/variant;work.mkdir()
            (work/'design.sv').write_text(text);(work/'timing.xdc').write_text(XDC)
            (work/'run.tcl').write_text(TCL)
            shutil.copy2(ROOT/'src/timinglens/vivado/extract.tcl',work/'extract.tcl')
            record={'source_sha256':sha256(text.encode()).hexdigest(),'xdc_sha256':sha256(XDC.encode()).hexdigest()}
            entry['variants'][variant]=record
            if args.with_vivado:
                print(f'Implementing {name}/{variant}',flush=True)
                record['implementation']=command(['nice','-n','10',args.vivado,'-mode','batch','-source','run.tcl','-notrace'],work,'console.log',1200)
                if record['implementation']['returncode']==0 and (work/'records.tsv').exists():
                    session=decode(work,80,3,'route',[work/'design.sv'],True)
                    result=analyze(session);export_result(result,work/'review')
                    record['summary']={k:v.model_dump() for k,v in session.summary.items()}
                    record['candidate_ids']=sorted({p.id for i in result.investigations for p in i.plans})
                    record['resources_and_drc']=dict(line.split('\t') for line in (work/'metrics.tsv').read_text().splitlines())
                    record['route_status_report']=str(work/'route_status.rpt')
                    record['pulse_width_report']=str(work/'timing_summary.rpt')
            (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(output/'manifest.json',flush=True)


if __name__=='__main__': main()
