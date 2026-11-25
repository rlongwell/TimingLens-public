"""Isolated counter experiments with durable lifecycle and reproducible Lab records."""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
from hashlib import sha256
from importlib.resources import files
import json
import os
from pathlib import Path
import re
import shutil
from threading import Event

from .capture import from_session
from .compare import compare
from .counters import plan_counter, COUNTERS
from .io import export_comparison, load_run, write_run
from .models import Artifact, BuildContext, Check, Run
from .process import execute, ProcessFailure
from .recipes import RECIPES, build_script, validate_recipes, variant_name
from ..timing.io import atomic_text
from ..timing.models import Summary
from ..vivado.decode import decode, read_rows
from ..vivado.runner import Cancelled, discover


def workspace_root():
    return Path(os.environ.get('TIMINGLENS_REPO_ROOT',Path(__file__).resolve().parents[3])).resolve()


@dataclass(frozen=True)
class CounterRequest:
    example: str
    output: Path
    vivado: str | None = None
    verilator: str | None = None
    timeout: float = 900.
    strategies: tuple[str,...] = ('default',)

    def validate(self):
        validate_recipes(self.strategies)
        if self.example not in COUNTERS:raise ValueError('Choose a bundled counter profile.')
        if not 1 <= self.timeout <= 7200:raise ValueError('Per-tool timeout must be 1–7200 seconds.')
        if self.output.exists() or self.output.is_symlink():raise FileExistsError('Choose a new job directory; existing evidence is never overwritten.')


@dataclass(frozen=True)
class CounterResult:
    directory: Path
    register_pair: tuple[Path,Path]
    global_pair: tuple[Path,Path]
    example: str = ''
    sweep: Path | None = None
    status: str = 'completed'


class JobFailure(RuntimeError):
    def __init__(self,message,directory,status):
        super().__init__(message);self.directory=directory;self.status=status


class InputChanged(ValueError):
    pass


@contextmanager
def runner_lock():
    directory=workspace_root()/'.settings';directory.mkdir(parents=True,exist_ok=True)
    with (directory/'counter-runner.lock').open('a') as stream:
        try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Another TimingLens experiment is running. Wait or cancel that job.') from None
        try:yield
        finally:fcntl.flock(stream,fcntl.LOCK_UN)


def digest(path):
    if path.is_symlink() or not path.is_file():raise ValueError(f'Expected a regular staged file: {path}')
    return sha256(path.read_bytes()).hexdigest()


def verify_inputs(root,expected):
    for name,expected_hash in expected.items():
        try:actual=digest(root/name)
        except (OSError,ValueError) as error:raise InputChanged('Staged input unavailable: '+name) from error
        if actual!=expected_hash:raise InputChanged('Staged input changed during the experiment: '+name)


def _snapshot_session(folder,root):
    # The decoder reads SOURCE entries; reject references outside this isolated build first.
    rows=read_rows(folder/'records.tsv')
    for filename,_ in rows['SOURCE']:
        path=Path(filename).resolve()
        if path not in {(root/'design.sv').resolve(),(root/'timing.xdc').resolve()} or not path.is_relative_to(root.resolve()):
            raise ValueError('Build capture contains a source outside its isolated directory: '+filename)
    session=decode(folder,400,1,'route',[root/'design.sv',root/'timing.xdc'],True)
    if session.part!='xc7z020clg400-1' or session.stage!='routed' or set(session.summary)!={'setup','hold'}:
        raise ValueError('Expected complete routed counter timing on the configured device.')
    reports=dict(session.reports)
    for name in ('utilization.rpt','drc.rpt'):reports[name]=(root/name).read_text()
    return session.model_copy(update={'reports':reports})


def _records(job,variant,plan,strategy='default'):
    root=job/variant
    scoped='Finite 10,289-cycle baseline/candidate/oracle comparison: reset, load, stalls, amount 0–15 and boundaries; not formal equivalence.'
    checks=[Check(name='functional',status='passed',scope=scoped,evidence='simulation/simulation.log and successful Verilator build/run, tied to the staged source hashes.'),
            Check(name='source_checkpoint',status='passed',scope='Controlled local build provenance for this checkpoint; not independent netlist equivalence.',
                  evidence='Fresh isolated directory; fixed recipe; staged source/XDC/script hashes unchanged before and after execution; checkpoint digest retained in build-record.json.')]
    attachments={}
    for path in [job/'plan.json',job/'candidate.patch',job/'simulation/build.log',job/'simulation/simulation.log',
                 job/'simulation/validation.json',job/'simulation/before.sv',job/'simulation/after.sv',job/'simulation/tb.sv',
                 root/'build-record.json',root/'batch.tcl',root/'extract.tcl',root/'primitives.tsv']:
        attachments[str(path.relative_to(job))]=path.read_text()
    context=BuildContext(design_key=plan.name,mode='out_of_context',dfx=False,
        sources={'design.sv':digest(root/'design.sv')},constraints={'timing.xdc':digest(root/'timing.xdc')},
        checkpoint_sha256=digest(root/'routed.dcp'),
        directives=RECIPES[strategy].directives(),
        compile_context={'top':'counter','language':'SystemVerilog','source_order':'design.sv','defines':'none','includes':'none','parameters':'none'},
        notes=['Built by TimingLens counter runner v1. Recipe '+RECIPES[strategy].name+'; one implementation per variant. Compare strategy effects against the same candidate RTL with Default.'])
    output={}
    for population,folder in [('design',root),('register_paths',root/'internal')]:
        captured=from_session(_snapshot_session(folder,root))
        attach=dict(attachments);timing=captured.timing
        if population=='register_paths':
            attach[f'{variant}/registers.tsv']=(root/'registers.tsv').read_text();timing={}
            for line in attach[f'{variant}/registers.tsv'].splitlines():
                kind,wns,tns,failed,total=line.split('\t')
                timing[kind]=Summary(worst_slack_ns=float(wns),total_negative_slack_ns=float(tns),failing_endpoints=int(failed),total_endpoints=int(total))
        artifacts=[*captured.artifacts,*[Artifact(name=name,sha256=sha256(text.encode()).hexdigest(),
                    kind='register_timing' if name.endswith('/registers.tsv') else 'runner_evidence') for name,text in attach.items()]]
        primitive=(root/'primitives.tsv').read_text().strip().split('\t')
        if len(primitive)!=2 or primitive[0]!='LUT*':raise ValueError('Missing logical primitive count.')
        record=Run.model_validate({**captured.model_dump(),
            'label':f'{COUNTERS[plan.name].width}-bit counter · '+('registers' if population=='register_paths' else 'global OOC')+f' · {variant} · {job.name}',
            'population':population,'timing':timing,'context':context,'checks':checks,'artifacts':artifacts,'attachments':attach,
            'metrics':{**captured.metrics,'area.lut_cells':float(primitive[1])},
            'metric_evidence':{**captured.metric_evidence,'area.lut_cells':variant+'/primitives.tsv: logical LUT primitive cells'},
            'notes':[*captured.notes,'OOC port placement and clock-source context are incomplete; integrated signoff remains untested.'],
            'change_diff':plan.diff if variant!='baseline' else ''})
        target=job/'runs'/f'{variant}.{population}.run.json';write_run(target,record)
        # Validate the same public import path used by the desktop.
        if load_run(target)!=record:raise ValueError('Run record did not roundtrip.')
        output[population]=target
    return output


def run_counter(request: CounterRequest,log=lambda _:None,progress=lambda _:None,cancel=None):
    request.validate();cancel=cancel or Event()
    with runner_lock():
        job=request.output.absolute();job.mkdir(parents=True,exist_ok=False,mode=0o700)
        state={'timinglens_job':1,'recipe':'unsigned-comparison-factor.v1','example':request.example,
               'status':'running','phase':'prepare','started_utc':datetime.now(timezone.utc).isoformat(),
               'steps':[],'pairs':{},'timeout_seconds':request.timeout,'threads':2}
        variants=[('baseline','default'),*[(variant_name(s),s) for s in request.strategies]]
        state['strategies']=list(request.strategies)
        state['strategy_runs']={s:{'status':'pending','variant':variant_name(s)} for s in request.strategies}
        records={}
        def publish_sweep():
            if len(request.strategies)>1:
                from .sweep import write_sweep
                write_sweep(job,state)
        def save():atomic_text(job/'job.json',json.dumps(state,indent=2)+'\n')
        def phase(name):
            if cancel.is_set():raise Cancelled('Experiment cancelled between stages.')
            state['phase']=name;save();progress(name);log('TimingLens: '+name)
        def tool(command,folder,name,timeout=None):
            entry={'phase':state['phase'],'command':[str(c) for c in command],'directory':str(folder.relative_to(job)),
                   'log':str((folder/name).relative_to(job)),'status':'running'}
            state['steps'].append(entry);save()
            try:
                result=execute(command,folder,folder/name,cancel,timeout or request.timeout,log)
                entry.update(result);entry['log']=str((folder/name).relative_to(job));entry['status']='completed';save();return result
            except BaseException as error:
                entry.update(status='cancelled' if isinstance(error,(Cancelled,KeyboardInterrupt)) else 'failed',error=str(error));save();raise
        try:
            save();phase('prepare');plan=plan_counter(request.example)
            (job/'plan.json').write_text(json.dumps(plan.document(),indent=2)+'\n')
            (job/'candidate.patch').write_text(plan.diff)
            inputs={}
            for variant,strategy in variants:
                data=plan.baseline if variant=='baseline' else plan.candidate
                folder=job/variant;folder.mkdir()
                for name,content in [('design.sv',data),('timing.xdc',plan.constraints),
                    ('batch.tcl',build_script(strategy)),
                    ('extract.tcl',files('timinglens.vivado').joinpath('extract.tcl').read_bytes())]:
                    path=folder/name;path.write_bytes(content);path.chmod(0o444);inputs[str(path.relative_to(job))]=digest(path)
            sim=job/'simulation';sim.mkdir()
            for name,content in [('before.sv',plan.baseline.replace(b'module counter(',b'module counter_before(',1)),
                                 ('after.sv',plan.candidate.replace(b'module counter(',b'module counter_after(',1)),('tb.sv',plan.testbench)]:
                path=sim/name;path.write_bytes(content);path.chmod(0o444);inputs[str(path.relative_to(job))]=digest(path)
            state['inputs_sha256']=inputs;save();publish_sweep()
            phase('tool checks');vivado=discover(request.vivado)
            verilator=Path(shutil.which(request.verilator or 'verilator') or request.verilator or 'verilator').absolute()
            if not verilator.is_file() or not os.access(verilator,os.X_OK):raise ValueError('Verilator is required for the counter validation stage.')
            tool([vivado,'-version'],job,'vivado-version.log',min(30,request.timeout))
            tool([verilator,'--version'],job,'verilator-version.log',min(30,request.timeout))
            v=re.search(r'Vivado\s+v?(\d+\.\d+)',(job/'vivado-version.log').read_text(),re.I)
            if not v or v[1]!='2024.2':raise ValueError('Counter runner recipe is validated for Vivado 2024.2.')
            versions={'vivado':v[1],'verilator':(job/'verilator-version.log').read_text().strip()};state['tools']=versions;save()
            nice=shutil.which('nice')
            prefix=[nice,'-n','10'] if nice else []
            phase('simulation build');verify_inputs(job,inputs)
            build=tool([*prefix,verilator,'--binary','--timing','-Wno-WIDTHEXPAND','-j','2','--top-module','tb','--Mdir','obj','before.sv','after.sv','tb.sv'],sim,'build.log')
            phase('simulation');simulation=tool([*prefix,sim/'obj/Vtb'],sim,'simulation.log')
            if 'PASS: 10289 sequential comparisons' not in (sim/'simulation.log').read_text():raise ProcessFailure('Simulation exited without the expected completion evidence.')
            verify_inputs(job,inputs)
            validation={'scope':'10289 finite baseline/candidate/oracle cycles; not formal equivalence','build':build,'run':simulation,
                        'source_hashes':{k:v for k,v in inputs.items() if k.endswith('.sv')},'versions':versions}
            (sim/'validation.json').write_text(json.dumps(validation,indent=2)+'\n')
            for variant,strategy in variants:
                folder=job/variant;phase(variant+' implementation');verify_inputs(job,inputs)
                if variant!='baseline':state['strategy_runs'][strategy]['status']='running';save();publish_sweep()
                try:
                    built=tool([*prefix,vivado,'-mode','batch','-nolog','-nojournal','-notrace','-source','batch.tcl'],folder,'vivado.log')
                    verify_inputs(job,inputs)
                    if (folder/'completed.txt').read_text().strip()!='TIMINGLENS_COUNTER_BUILD_V1':raise ValueError('Implementation did not complete its capture stage.')
                    checkpoint_hash=digest(folder/'routed.dcp')
                    build_record={'variant':variant,'strategy':strategy,'directives':RECIPES[strategy].directives(),
                                  'source_sha256':inputs[variant+'/design.sv'],'constraint_sha256':inputs[variant+'/timing.xdc'],
                                  'inputs_sha256':{k:v for k,v in inputs.items() if k.startswith(variant+'/')},
                                  'checkpoint_sha256':checkpoint_hash,'process':built,'versions':versions,'inputs_unchanged':True}
                    (folder/'build-record.json').write_text(json.dumps(build_record,indent=2)+'\n')
                    phase(variant+' capture');records[variant]=_records(job,variant,plan,strategy)
                    state[variant+'_records']={k:str(p.relative_to(job)) for k,p in records[variant].items()}
                    if variant!='baseline':state['strategy_runs'][strategy].update(status='completed',records=state[variant+'_records'],seconds=built['seconds'])
                    save();publish_sweep()
                except (OSError,ValueError,ProcessFailure) as error:
                    if variant!='baseline':state['strategy_runs'][strategy].update(status='failed',error=str(error));save();publish_sweep()
                    if variant in {'baseline','candidate'} or isinstance(error,InputChanged):raise
                    log(f'TimingLens: {strategy} failed; retaining evidence and continuing other recipes.')
            phase('compare');verify_inputs(job,inputs)
            for population in ('register_paths','design'):
                before,after=(records[v][population] for v in ('baseline','candidate'))
                result=compare(load_run(before),load_run(after));export_comparison(result,job/'comparisons'/population)
                state['pairs'][population]={'baseline':str(before.relative_to(job)),'candidate':str(after.relative_to(job)),
                                             'outcome':result.outcome,'acceptance':result.acceptance,'headline':result.headline}
            phase('publish')
            status='partial' if any(s['status']=='failed' for s in state['strategy_runs'].values()) else 'completed'
            state.update(status=status,finished_utc=datetime.now(timezone.utc).isoformat());save();publish_sweep();progress(status)
            if len(request.strategies)>1:
                from .sweep import load_sweep, render_sweep
                reviews=[load_sweep(job/'sweep.json',population) for population in ('register_paths','design')]
                atomic_text(job/'ranking.json',json.dumps([review.document() for review in reviews],indent=2)+'\n')
                atomic_text(job/'sweep.html',render_sweep(reviews))
            return CounterResult(job,tuple(records[v]['register_paths'] for v in ('baseline','candidate')),
                                  tuple(records[v]['design'] for v in ('baseline','candidate')),request.example,
                                  job/'sweep.json' if len(request.strategies)>1 else None,status)
        except BaseException as error:
            status='cancelled' if isinstance(error,(Cancelled,KeyboardInterrupt)) else 'failed'
            for row in state['strategy_runs'].values():
                if row['status']=='running':row.update(status=status,error=str(error))
                elif row['status']=='pending':row['status']='not_run'
            state.update(status=status,error=str(error),finished_utc=datetime.now(timezone.utc).isoformat());save();publish_sweep();progress(status)
            if isinstance(error,KeyboardInterrupt):raise
            raise JobFailure(f'{error}\nEvidence retained in {job}',job,status) from error
