"""Execute reviewed example recommendations in fresh local builds only."""
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from importlib.resources import files
import json
import os
from pathlib import Path
import re
import shutil
from threading import Event
from contextlib import nullcontext

from ..analysis.engine import analyze
from ..timing.io import atomic_text
from ..timing.models import Summary
from ..vivado.decode import decode, read_rows
from ..vivado.runner import Cancelled, discover
from .capture import from_session
from .compare import compare
from .io import export_comparison, load_run, write_run
from .models import Artifact, BuildContext, Check, Run, canonical
from .process import execute, ProcessFailure
from .recipes import RECIPES
from .recommendation import EXAMPLES, PreparedExperiment, build_script, bundled_inputs, revalidate
from .runner import CounterResult, JobFailure, digest, runner_lock, verify_inputs
from .sweep import explain
from .priority_rewrite import SCOPE
from .priority_variants import candidate,source_diff,VARIANTS
from .equivalence import discover_yosys,command_prefix,verify_proof,SCRIPT


@dataclass(frozen=True)
class RecommendationRequest:
    prepared: PreparedExperiment
    output: Path
    vivado: str | None = None
    verilator: str | None = None
    timeout: float = 900.
    yosys: str | None = None

    def validate(self):
        if not 1<=self.timeout<=7200:raise ValueError('Per-tool timeout must be 1–7200 seconds.')
        if self.output.exists() or self.output.is_symlink():raise FileExistsError('Choose a new job directory; existing evidence is never overwritten.')
        revalidate(self.prepared)


def snapshot(folder,source_root):
    allowed={(source_root/name).resolve() for name in ('design.sv','timing.xdc')}
    for filename,_ in read_rows(folder/'records.tsv')['SOURCE']:
        path=Path(filename).resolve()
        if path not in allowed or not path.is_relative_to(source_root.resolve()):
            raise ValueError('Build capture references a source outside its staged inputs.')
    session=decode(folder,400,1,'route',[source_root/'design.sv',source_root/'timing.xdc'],True)
    if session.part!='xc7z020clg400-1' or session.stage!='routed' or set(session.summary)!={'setup','hold'}:
        raise ValueError('Expected a complete routed example capture.')
    return session


def capture_records(job,variant,prepared,source_root):
    root=job/variant;spec=EXAMPLES[prepared.example];recipe=RECIPES['default'] if variant=='baseline' else prepared.recipe
    context=BuildContext(design_key='example:'+prepared.example,mode='integrated',dfx=False,
        sources={'design.sv':digest(root/'design.sv')},constraints={'timing.xdc':digest(root/'timing.xdc')},
        directives=recipe.directives(),checkpoint_sha256=digest(root/'routed.dcp'),
        compile_context={'top':spec.top,'language':'SystemVerilog','source_order':'design.sv','defines':'none','includes':'none','parameters':'defaults'},
        notes=['Standalone example top; not a larger application or board deployment.','One build per recipe; no repeatability claim.'])
    checks=[Check(name='functional',status='passed',scope=prepared.document()['functional_scope'],evidence='Both simulation variants and validation.json.' if prepared.rtl_rewrite else 'simulation/simulation.log and validation.json; unchanged source in both variants.'),
            Check(name='source_checkpoint',status='passed',scope='Fresh controlled local build with source, script and checkpoint hashes; not independent netlist equivalence.',evidence=variant+'/build-record.json')]
    names=['plan.json','trigger.json','recipe.patch','baseline-recheck.json','simulation/validation.json','simulation/simulation.log',
           'simulation/build.log','simulation/tb.sv',variant+'/batch.tcl',variant+'/extract.tcl',variant+'/build-record.json',variant+'/primitives.tsv']
    if prepared.rtl_rewrite:
        checks.append(Check(name='equivalence',status='passed',scope=SCOPE,evidence='equivalence/result.json, equivalence.log and proof.json; exact staged source hashes.'))
        names += ['source.patch',*[f'equivalence/{n}' for n in ('baseline.sv','candidate.sv','equivalence.ys','version.log','equivalence.log','proof.json','result.json')],
                  *[f'simulation/{v}/{n}' for v in ('baseline','candidate') for n in ('design.sv','tb.sv','build.log','simulation.log')]]
    attachments={name:(job/name).read_text() for name in names if (job/name).is_file()}
    paths={}
    for population,folder in [('design',root),('register_paths',root/'internal')]:
        session=snapshot(folder,source_root)
        if session.top!=spec.top:raise ValueError('Captured top disagrees with the prepared experiment.')
        session=session.model_copy(update={'reports':{**session.reports,**{name:(root/name).read_text() for name in ('utilization.rpt','drc.rpt')}}})
        captured=from_session(session);attach=dict(attachments);timing=captured.timing
        if population=='register_paths':
            text=(root/'registers.tsv').read_text();attach[variant+'/registers.tsv']=text;timing={}
            for line in text.splitlines():
                check,wns,tns,failed,total=line.split('\t')
                timing[check]=Summary(worst_slack_ns=float(wns),total_negative_slack_ns=float(tns),failing_endpoints=int(failed),total_endpoints=int(total))
        primitive=(root/'primitives.tsv').read_text().strip().split('\t')
        if len(primitive)!=2 or primitive[0]!='LUT*':raise ValueError('Missing logical LUT primitive count.')
        run=Run.model_validate({**captured.model_dump(),'label':f'{spec.title} · {variant} · {population} · {job.name}',
            'population':population,'timing':timing,'context':context,'checks':checks,'attachments':attach,
            'artifacts':[*captured.artifacts,*[Artifact(name=n,sha256=sha256(t.encode()).hexdigest(),kind='register_timing' if n.endswith('/registers.tsv') else 'recommendation_evidence') for n,t in attach.items()]],
            'metrics':{**captured.metrics,'area.lut_cells':float(primitive[1])},
            'metric_evidence':{**captured.metric_evidence,'area.lut_cells':variant+'/primitives.tsv'},
            'change_diff':(job/('source.patch' if prepared.rtl_rewrite else 'recipe.patch')).read_text() if variant=='candidate' else '',
            'notes':[*captured.notes,*prepared.document()['limits']]})
        target=job/f'runs/{variant}.{population}.run.json';write_run(target,run)
        if load_run(target)!=run:raise ValueError('Run evidence failed public-import validation.')
        paths[population]=target
    return paths


def read_recommendation_job(directory):
    if (Path(directory)/'rtl-sweep.json').exists():
        from .rtl_sweep_runner import read_rtl_job
        return read_rtl_job(Path(directory))
    directory=Path(directory);path=directory/'result.json'
    from .sweep import _bytes
    if not path.exists():
        data=_bytes(directory/'job.json',1_000_000)
        state=json.loads(data);raise ValueError('Job '+str(state.get('status','unknown'))+': '+str(state.get('error','No completed comparison.')))
    envelope=json.loads(_bytes(path,1_000_000))
    if not isinstance(envelope,dict) or set(envelope)!={'timinglens_recommendation_result','sha256','result'} or type(envelope['timinglens_recommendation_result']) is not int or envelope['timinglens_recommendation_result']!=1:
        raise ValueError('Unsupported recommendation result.')
    data=envelope['result']
    if sha256(canonical(data)).hexdigest()!=envelope['sha256']:raise ValueError('Recommendation result integrity check failed.')
    if not isinstance(data,dict) or set(data)!={'example','plan_id','records'} or not isinstance(data['example'],str) or data['example'] not in EXAMPLES or data['plan_id'] not in EXAMPLES[data['example']].plans:
        raise ValueError('Unknown example or experiment in result.')
    if not isinstance(data['records'],dict) or set(data['records'])!={f'runs/{v}.{p}.run.json' for v in ('baseline','candidate') for p in ('design','register_paths')}:
        raise ValueError('Unexpected run record paths in recommendation result.')
    pairs={}
    for population in ('register_paths','design'):
        pair=[]
        for variant in ('baseline','candidate'):
            relative=f'runs/{variant}.{population}.run.json';target=directory/relative
            if not target.resolve().is_relative_to(directory.resolve()):raise ValueError('Run evidence points outside this job.')
            if sha256(_bytes(target,64_000_000)).hexdigest()!=data['records'].get(relative):raise ValueError('Run file digest mismatch.')
            run=load_run(target)
            if run.population!=population or run.context.design_key!='example:'+data['example']:raise ValueError('Run identity disagrees with result.')
            pair.append(target)
        pairs[population]=tuple(pair)
    return CounterResult(directory,pairs['register_paths'],pairs['design'],data['example'])


def run_recommendation(request,log=lambda _:None,progress=lambda _:None,cancel=None):
    if request.prepared.rtl_sweep:
        from .rtl_sweep_runner import run_rtl_sweep
        return run_rtl_sweep(request,log,progress,cancel)
    return _run_recommendation(request,log,progress,cancel)


def _run_recommendation(request,log=lambda _:None,progress=lambda _:None,cancel=None,*,shared_baseline=None,locked=False):
    request.validate();cancel=cancel or Event();prepared=request.prepared;spec=EXAMPLES[prepared.example]
    if prepared.rtl_sweep:raise ValueError('Use the sweep orchestrator for a multi-variant request.')
    with nullcontext() if locked else runner_lock():
        job=request.output.absolute();job.mkdir(parents=True,exist_ok=False,mode=0o700)
        state={'timinglens_recommendation_job':1,'example':prepared.example,'plan_id':prepared.plan_id,'status':'running','phase':'prepare',
               'started_utc':datetime.now(timezone.utc).isoformat(),'steps':[],'records':{},'threads':2,'timeout_seconds':request.timeout}
        def save():atomic_text(job/'job.json',json.dumps(state,indent=2)+'\n')
        def phase(name):
            if cancel.is_set():raise Cancelled('Experiment cancelled between stages.')
            state['phase']=name;save();progress(name);log('TimingLens: '+name)
        def tool(command,folder,filename,timeout=None):
            entry={'phase':state['phase'],'command':[str(c) for c in command],'directory':str(folder.relative_to(job)),
                   'log':str((folder/filename).relative_to(job)),'status':'running'}
            state['steps'].append(entry);save()
            try:
                result=execute(command,folder,folder/filename,cancel,timeout or request.timeout,log)
                entry.update(result);entry.update(status='completed',log=str((folder/filename).relative_to(job)));save();return result
            except BaseException as error:
                entry.update(status='cancelled' if isinstance(error,(Cancelled,KeyboardInterrupt)) else 'failed',error=str(error));save();raise
        try:
            phase('prepare');source,constraints,tb=bundled_inputs(prepared.example)
            (job/'plan.json').write_text(json.dumps(prepared.document(),indent=2)+'\n');(job/'trigger.json').write_text(prepared.trigger_json)
            from difflib import unified_diff
            before=build_script(prepared.example);after=build_script(prepared.example,prepared.plan_id)
            (job/'recipe.patch').write_text(''.join(unified_diff(before.decode().splitlines(True),after.decode().splitlines(True),fromfile='baseline/batch.tcl',tofile='candidate/batch.tcl')))
            inputs={}
            sources={'baseline':source,'candidate':candidate(source,prepared.variant_key) if prepared.rtl_rewrite else source}
            if prepared.rtl_rewrite:
                if before!=after:raise ValueError('RTL comparison requires byte-identical implementation scripts.')
                (job/'source.patch').write_text(source_diff(source,prepared.variant_key));(job/'source.patch').chmod(0o444);inputs['source.patch']=digest(job/'source.patch')
            for variant,script in [('baseline',before),('candidate',after)]:
                folder=job/variant;folder.mkdir()
                for name,data in [('design.sv',sources[variant]),('timing.xdc',constraints),('batch.tcl',script),('extract.tcl',files('timinglens.vivado').joinpath('extract.tcl').read_bytes())]:
                    path=folder/name;path.write_bytes(data);path.chmod(0o444);inputs[str(path.relative_to(job))]=digest(path)
            sim=job/'simulation';sim.mkdir()
            if tb.count(b'$finish;')!=1:raise ValueError('Testbench completion marker is ambiguous.')
            simulations=[(sim/v,sources[v]) for v in ('baseline','candidate')] if prepared.rtl_rewrite else [(sim,source)]
            for folder,rtl in simulations:
                folder.mkdir(exist_ok=True)
                for name,data in [('design.sv',rtl),('tb.sv',tb.replace(b'$finish;',b'$display("TIMINGLENS_EXAMPLE_SIM_PASS"); $finish;'))]:
                    path=folder/name;path.write_bytes(data);path.chmod(0o444);inputs[str(path.relative_to(job))]=digest(path)
            if prepared.rtl_rewrite:
                formal=job/'equivalence';formal.mkdir()
                for name,data in [('baseline.sv',sources['baseline']),('candidate.sv',sources['candidate']),('equivalence.ys',SCRIPT.encode())]:
                    path=formal/name;path.write_bytes(data);path.chmod(0o444);inputs[str(path.relative_to(job))]=digest(path)
            for name in ('plan.json','trigger.json','recipe.patch'):
                (job/name).chmod(0o444);inputs[name]=digest(job/name)
            state['inputs_sha256']=inputs;save()
            if prepared.rtl_rewrite:
                phase('equivalence');yosys=discover_yosys(request.yosys);verify_inputs(job,inputs)
                tool([*command_prefix(),yosys,'-V'],formal,'version.log')
                version_text=(formal/'version.log').read_text()
                if not re.search(r'\bYosys 0\.69(?:\s|$)',version_text):raise ValueError('Priority equivalence is qualified with Yosys 0.69.')
                tool([*command_prefix(),yosys,'-s','equivalence.ys'],formal,'equivalence.log')
                verify_inputs(job,inputs);proof=verify_proof(formal)
                (formal/'result.json').write_text(json.dumps(proof,indent=2)+'\n')
                for name in ('proof.json','result.json','equivalence.log','version.log'):
                    path=formal/name;path.chmod(0o444);inputs[str(path.relative_to(job))]=digest(path)
                state['equivalence']=proof;save();log('Equivalence passed · 67 matched points proven before Vivado implementation.')
            phase('tool checks')
            vivado=discover(request.vivado);verilator=Path(shutil.which(request.verilator or 'verilator') or request.verilator or 'verilator').absolute()
            if not verilator.is_file() or not os.access(verilator,os.X_OK):raise ValueError('Verilator is required for example validation.')
            tool([vivado,'-version'],job,'vivado-version.log',min(30,request.timeout))
            tool([verilator,'--version'],job,'verilator-version.log',min(30,request.timeout))
            version=re.search(r'Vivado\s+v?(\d+\.\d+)',(job/'vivado-version.log').read_text(),re.I)
            if not version or version[1]!='2024.2':raise ValueError('These experiment recipes require Vivado 2024.2.')
            state['tools']={'vivado':version[1],'verilator':(job/'verilator-version.log').read_text().strip()};save()
            nice=shutil.which('nice');prefix=[nice,'-n','10'] if nice else []
            # The pinned deep/priority vectors contain only forward bit dependencies;
            # Verilator's vector-level UNOPTFLAT diagnostic is not a logic cycle.
            warnings=['-Wno-UNOPTFLAT'] if prepared.example in {'deep','priority'} else []
            for folder,_ in simulations:
                phase('simulation build');verify_inputs(job,inputs)
                tool([*prefix,verilator,'--binary','--timing',*warnings,'--top-module','tb','--Mdir','obj','-j','2','design.sv','tb.sv'],folder,'build.log')
                phase('simulation');tool([*prefix,folder/'obj/Vtb'],folder,'simulation.log')
                if 'TIMINGLENS_EXAMPLE_SIM_PASS' not in (folder/'simulation.log').read_text():raise ProcessFailure('Simulation lacks its completion marker.')
            verify_inputs(job,inputs)
            (sim/'validation.json').write_text(json.dumps({'scope':prepared.document()['functional_scope'],'inputs_sha256':inputs,'tools':state['tools']},indent=2)+'\n')
            records={}
            for variant in ('baseline','candidate'):
                folder=job/variant;phase(variant+' implementation');verify_inputs(job,inputs)
                if variant=='candidate' and prepared.plan_id=='vivado.fanout':
                    placed=job/'baseline/placed.dcp';seed=digest(placed);placed.chmod(0o444)
                    target=folder/'placement.dcp';shutil.copyfile(placed,target);target.chmod(0o444)
                    if digest(target)!=seed:raise ValueError('Placement checkpoint copy failed its digest check.')
                    inputs['baseline/placed.dcp']=seed;inputs['candidate/placement.dcp']=seed;state['inputs_sha256']=inputs;save()
                reused=variant=='baseline' and shared_baseline is not None
                if reused:
                    phase('baseline reuse');shared_baseline.copy_to(folder)
                    built=shared_baseline.record['process'];log('Reused the shared original build; no new baseline implementation.')
                else:built=tool([*prefix,vivado,'-mode','batch','-nolog','-nojournal','-notrace','-source','batch.tcl'],folder,'vivado.log')
                verify_inputs(job,inputs)
                if (folder/'completed.txt').read_text().strip()!='TIMINGLENS_EXAMPLE_BUILD_V1':raise ValueError('Build lacks a completed capture marker.')
                recipe=RECIPES['default'] if variant=='baseline' else prepared.recipe
                record={'variant':variant,'recipe':recipe.name,'directives':recipe.directives(),'process':built,'tools':state['tools'],
                    'inputs_sha256':inputs.copy(),'checkpoint_sha256':digest(folder/'routed.dcp'),'inputs_unchanged':True,
                    'placement_parent_sha256':inputs.get('candidate/placement.dcp') if variant=='candidate' else None}
                if reused:record['baseline_reuse']={'directory':str(shared_baseline.directory),'files_sha256':shared_baseline.hashes}
                (folder/'build-record.json').write_text(json.dumps(record,indent=2)+'\n');phase(variant+' capture')
                source_root=job/'baseline' if variant=='candidate' and prepared.plan_id=='vivado.fanout' else folder
                if reused:source_root=shared_baseline.directory
                if variant=='baseline':
                    measured=analyze(snapshot(folder,source_root));plans=[p for group in measured.investigations for p in group.plans if p.id==prepared.plan_id]
                    (job/'baseline-recheck.json').write_text(json.dumps({'selected_plan':prepared.plan_id,'supported':bool(plans),'matching_plans':[p.id for p in plans]},indent=2)+'\n')
                records[variant]=capture_records(job,variant,prepared,source_root)
                state['records'].update({str(p.relative_to(job)):digest(p) for p in records[variant].values()});save()
                if variant=='baseline' and not plans:raise ValueError('Fresh baseline no longer supports this recommendation. Baseline evidence retained; candidate not run.')
            phase('compare');verify_inputs(job,inputs)
            explanations={}
            for population in ('register_paths','design'):
                comparison=compare(*[load_run(records[v][population]) for v in ('baseline','candidate')])
                export_comparison(comparison,job/'comparisons'/population);explanations[population]=explain(comparison)
            (job/'explanations.json').write_text(json.dumps(explanations,indent=2)+'\n')
            data={'example':prepared.example,'plan_id':prepared.plan_id,'records':state['records']}
            atomic_text(job/'result.json',json.dumps({'timinglens_recommendation_result':1,'sha256':sha256(canonical(data)).hexdigest(),'result':data},indent=2)+'\n')
            result=read_recommendation_job(job)
            state.update(status='completed',finished_utc=datetime.now(timezone.utc).isoformat());save();progress('completed');return result
        except BaseException as error:
            status='cancelled' if isinstance(error,(Cancelled,KeyboardInterrupt)) else 'failed'
            state.update(status=status,error=str(error),finished_utc=datetime.now(timezone.utc).isoformat());save();progress(status)
            if isinstance(error,KeyboardInterrupt):raise
            raise JobFailure(f'{error}\nEvidence retained in {job}',job,status) from error
