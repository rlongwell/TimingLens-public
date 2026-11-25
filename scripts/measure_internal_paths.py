#!/usr/bin/env python3
"""Read isolated experiment checkpoints and retain register-only timing.

OOC port delays and clock insertion are incomplete without integration. These
reports isolate internal register paths; they still are not full-design signoff.
"""
import argparse
import json
from pathlib import Path
from validate_semantic_changes import command


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiments',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--vivado',default='/opt/amd/xilinx/Vivado/2024.2/bin/vivado')
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    code=['set_param general.maxThreads 2']
    for name in ('unsigned32_ge','unsigned64_gt'):
        for variant in ('before','after'):
            path=(args.experiments/name/variant/'routed.dcp').resolve()
            # Tcl path data is hex-decoded, never interpolated as executable text.
            label=f'{name}-{variant}'
            code += [f'open_checkpoint [encoding convertfrom utf-8 [binary decode hex {str(path).encode().hex()}]]',
                     f'set stats [open {label}.tsv w]',
                     'foreach {check delay} {setup max hold min} {',
                     'set paths [get_timing_paths -delay_type $delay -from [all_registers] -to [all_registers] -max_paths 10000 -nworst 1]',
                     'set worst unavailable; set tns 0; set failed 0; set endpoints [dict create]',
                     'foreach p $paths {',
                     'set slack [get_property SLACK $p]',
                     'set end [get_property ENDPOINT_PIN $p]',
                     'if {$worst eq "unavailable" || $slack < $worst} {set worst $slack}',
                     'if {$slack < 0 && ![dict exists $endpoints $end]} {incr failed; set tns [expr {$tns + $slack}]}',
                     'dict set endpoints $end 1',
                     '}',
                     'puts $stats "$check\t$worst\t$tns\t$failed\t[dict size $endpoints]"',
                     f'report_timing -of_objects [lrange $paths 0 4] -file {label}-$check.rpt',
                     '}', 'close $stats', 'close_design']
    code.append('exit');(out/'run.tcl').write_text('\n'.join(code)+'\n')
    run=command(['nice','-n','10',args.vivado,'-mode','batch','-source','run.tcl','-notrace'],out,'console.log',600)
    data={'run':run,'scope':'Internal register paths, OOC default clock model. Integration, I/O and DFX compatibility remain unvalidated.','results':{}}
    if run['returncode']==0:
        for path in sorted(out.glob('*.tsv')):
            data['results'][path.stem]={}
            for line in path.read_text().splitlines():
                check,wns,tns,failed,total=line.split('\t')
                data['results'][path.stem][check]={'worst_slack_ns':float(wns),'total_negative_slack_ns':round(float(tns),3),
                                                  'failing_endpoints':int(failed),'captured_endpoints':int(total)}
    (out/'metrics.json').write_text(json.dumps(data,indent=2)+'\n')


if __name__=='__main__': main()
