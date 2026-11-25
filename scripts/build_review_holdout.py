#!/usr/bin/env python3
"""Build frozen held-out designs in a new folder. Does not access hardware."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil

from timinglens import analyze
from timinglens.service import export_result
from timinglens.timing.models import Source
from timinglens.vivado.decode import decode
from validate_semantic_changes import command, XDC, ROOT


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--vivado',default='/opt/amd/xilinx/Vivado/2024.2/bin/vivado')
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    manifest={'partition':'held-out for semantic-review v2; frozen before first implementation',
              'rules_sha256':{str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest()
                              for folder in ('analysis','rtl') for p in (ROOT/'src/timinglens'/folder).glob('*.py')},'designs':[]}
    for name,top in [('stream','stream_top'),('memory_dsp','memory_dsp')]:
        work=out/name;work.mkdir()
        shutil.copy2(ROOT/f'examples/review-holdout/{name}.sv',work/'design.sv')
        shutil.copy2(ROOT/'src/timinglens/vivado/extract.tcl',work/'extract.tcl')
        (work/'timing.xdc').write_text(XDC)
        (work/'run.tcl').write_text(f'''set_param general.maxThreads 2
read_verilog -sv design.sv
read_xdc timing.xdc
synth_design -top {top} -part xc7z020clg400-1 -flatten_hierarchy none
opt_design
place_design -directive Default
route_design -directive Default
write_checkpoint routed.dcp
report_utilization -file utilization.rpt
report_drc -file drc.rpt
source extract.tcl
tl::collect demo [file normalize design.sv] {name} {top} {{}} 80 3 0
exit
''')
        print('Building '+name,flush=True)
        run=command(['nice','-n','10',args.vivado,'-mode','batch','-source','run.tcl','-notrace'],work,'console.log',1200)
        row={'name':name,'run':run,'source_sha256':sha256((work/'design.sv').read_bytes()).hexdigest()};manifest['designs'].append(row)
        if run['returncode']==0:
            s=decode(work,80,3,'route',[work/'design.sv'],True)
            if name=='stream':
                context=ROOT/'examples/review-holdout/stream.bd.tcl'
                s=s.model_copy(update={'sources':[*s.sources,Source(path=str(context),text=context.read_text(),sha256=sha256(context.read_bytes()).hexdigest())]})
            export_result(analyze(s),work/'review')
            row['summary']={k:v.model_dump() for k,v in s.summary.items()}
        (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')


if __name__=='__main__':main()
