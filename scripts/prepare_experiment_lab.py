#!/usr/bin/env python3
"""Package completed TimingLens-local captures; never invoke tools or follow origins.

Usage: .venv/bin/python scripts/prepare_experiment_lab.py --output work/experiment-lab/catalog
"""
import argparse
import difflib
from hashlib import sha256
import json
from pathlib import Path

from timinglens.experiments.capture import from_session
from timinglens.experiments.io import write_run
from timinglens.experiments.models import Artifact, BuildContext, Check, Run
from timinglens.timing.io import read_session
from timinglens.timing.models import Summary


def prepare(root: Path, output: Path):
    source=root/'work/semantic-review'
    manifest=json.loads((source/'implementation-01/manifest.json').read_text())
    simulation=json.loads((source/'simulation-checked/manifest.json').read_text())
    prior=json.loads((source/'prior-project-review.json').read_text())
    records=[];pairs=[]
    def artifact(path,kind):
        return Artifact(name=str(path.relative_to(source)),sha256=sha256(path.read_bytes()).hexdigest(),kind=kind)
    for experiment in manifest['experiments']:
        name=experiment['name'];width='32' if name=='unsigned32_ge' else '64'
        base=source/'implementation-01'/name
        patch=''.join(difflib.unified_diff((base/'before/design.sv').read_text().splitlines(True),
                 (base/'after/design.sv').read_text().splitlines(True),fromfile='baseline/design.sv',tofile='candidate/design.sv'))
        sim=next(e for e in simulation['experiments'] if e['name']==name)['simulation']
        simbase=source/'simulation-checked'/name/'simulation'
        for variant in ('before','after'):
            directory=base/variant
            capture=from_session(read_session(directory/'review/analysis.json'))
            digest=lambda p:sha256(p.read_bytes()).hexdigest()
            declared=experiment['variants'][variant]
            if digest(directory/'design.sv')!=declared['source_sha256'] or digest(directory/'timing.xdc')!=declared['xdc_sha256']:
                raise ValueError('Completed counter source or constraint bytes changed: '+name+'/'+variant)
            context=BuildContext(design_key=name,mode='out_of_context',dfx=False,
                sources={'design.sv':declared['source_sha256']},constraints={'timing.xdc':declared['xdc_sha256']},
                directives={**manifest['directives'],'threads':str(manifest['threads']),'seed':manifest['seed']},
                compile_context={'top':'counter','language':'SystemVerilog','source_order':'design.sv','defines':'none','includes':'none','parameters':'none'},
                checkpoint_sha256=digest(directory/'routed.dcp'),
                notes=['Compile settings declared by the retained run.tcl. One implementation per variant; no repeatability claim.'])
            passed=sim['build']['returncode']==0 and sim['run'] and sim['run']['returncode']==0
            artifacts=[*capture.artifacts,artifact(source/'implementation-01/manifest.json','implementation_manifest'),
                artifact(directory/'run.tcl','build_script'),artifact(directory/'metrics.tsv','primitive_counts'),
                artifact(source/'simulation-checked/manifest.json','simulation_manifest'),
                artifact(simbase/'simulation.log','simulation_log'),artifact(simbase/'tb.sv','testbench')]
            metrics={**capture.metrics,'area.lut_cells':float(declared['resources_and_drc']['LUT*'])}
            evidence={**capture.metric_evidence,'area.lut_cells':'metrics.tsv: get_cells LUT* primitive count; not physical LUT sites'}
            checks=[Check(name='functional',status='passed' if passed else 'failed',scope=sim['scope'],
                           evidence='Retained Verilator comparison: 10,289 cycles; build and simulation returned zero.' if passed else 'Retained simulation did not complete.'),
                    Check(name='source_checkpoint',scope='Exact built-source correspondence has not been independently verified.')]
            data=capture.model_dump()
            data.update(context=context,checks=checks,artifacts=artifacts,metrics=metrics,metric_evidence=evidence,
                        notes=[*capture.notes,'OOC ports lack placement and clock-source context; global I/O timing does not establish integration signoff.'],
                        change_diff=patch if variant=='after' else '')
            for population,suffix in [('design','global'),('register_paths','internal')]:
                timing=capture.timing;extra=[]
                if population=='register_paths':
                    tsv=source/'internal-paths-01'/f'{name}-{variant}.tsv'
                    timing={}
                    for line in tsv.read_text().splitlines():
                        kind,wns,tns,fail,total=line.split('\t')
                        timing[kind]=Summary(worst_slack_ns=float(wns),total_negative_slack_ns=round(float(tns),3),failing_endpoints=int(fail),total_endpoints=int(total))
                    extra=[artifact(tsv,'register_timing'),artifact(source/'internal-paths-01/run.tcl','register_collection_script')]
                record=Run.model_validate({**data,'label':f'{width}-bit counter · {suffix} · {variant}',
                    'population':population,'timing':timing,'artifacts':[*artifacts,*extra],
                    'attachments':{a.name:(source/a.name).read_text() for a in [*artifacts,*extra] if a.kind not in {'embedded_report','session'}}})
                filename=f'{name}-{suffix}-{variant}.run.json'
                records.append((filename,record))
        for suffix in ('internal','global'):
            pairs.append({'label':f'{width}-bit counter / '+('register timing' if suffix=='internal' else 'global OOC timing'),
                'baseline':f'{name}-{suffix}-before.run.json','candidate':f'{name}-{suffix}-after.run.json'})
    for variant in ('failing','passing'):
        path=source/'corpus-inputs'/f'dfx-{variant}.json'
        capture=from_session(read_session(path),input_sha=sha256(path.read_bytes()).hexdigest())
        checkpoint=prior['live_captures']['project-'+variant]['checkpoint_sha256']
        context=capture.context.model_copy(update={'design_key':'retained DFX hash capture / u_hash','mode':'integrated','dfx':True,'checkpoint_sha256':checkpoint,
            'notes':['Design identity and checkpoint hash come from the prior local review; XDC, complete build context and pr_verify are absent.']})
        record=Run.model_validate({**capture.model_dump(),'label':'DFX hash · '+variant,'context':context,
            'artifacts':[*capture.artifacts,artifact(source/'prior-project-review.json','prior_review')],
            'attachments':{'prior-project-review.json':(source/'prior-project-review.json').read_text()},
            'change_diff':'No exact implementation diff captured. Prior review records an implementation-strategy change, not an RTL rewrite. Attribution remains unverified.' if variant=='passing' else ''})
        records.append((f'dfx-{variant}.run.json',record))
    pairs.append({'label':'DFX hash / retained routed captures','baseline':'dfx-failing.run.json','candidate':'dfx-passing.run.json'})
    output.mkdir(parents=True,exist_ok=False)
    for filename,record in records:write_run(output/filename,record)
    (output/'catalog.json').write_text(json.dumps({'timinglens_catalog':1,'pairs':pairs},indent=2)+'\n')
    print(f'Prepared {len(records)} self-contained runs and {len(pairs)} pairs in {output}')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    prepare(Path(__file__).resolve().parents[1],args.output)
