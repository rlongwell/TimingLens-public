from hashlib import sha256
import json
from pathlib import Path
import shutil
from threading import Event

import pytest

from timinglens.experiments import load_run
from timinglens.experiments.counters import plan_counter
from timinglens.experiments import runner
from timinglens.experiments.runner import CounterRequest, JobFailure, run_counter, runner_lock
from timinglens.timing.models import Cell, Clock, Pin, Session, Source, Summary, TimingPath


@pytest.fixture
def fake_tools(tmp_path,monkeypatch):
    monkeypatch.setenv('TIMINGLENS_REPO_ROOT',str(tmp_path))
    executable=tmp_path/'tool';executable.write_text('fixture');executable.chmod(0o700)
    monkeypatch.setattr(runner,'discover',lambda _:executable)
    calls=[]
    def execute(command,cwd,logfile,cancel,timeout,log):
        calls.append((cwd.name,logfile.name));text='fixture tool completed\n'
        if logfile.name=='vivado-version.log':text='vivado v2024.2 (64-bit)\n'
        elif logfile.name=='verilator-version.log':text='Verilator 5.020\n'
        elif logfile.name=='simulation.log':text='PASS: 10289 sequential comparisons\n'
        elif logfile.name=='vivado.log':
            (cwd/'routed.dcp').write_bytes(b'fixture checkpoint '+cwd.name.encode())
            (cwd/'completed.txt').write_text('TIMINGLENS_COUNTER_BUILD_V1\n')
            (cwd/'registers.tsv').write_text('setup\t-1\t-2\t2\t2\nhold\t0.1\t0\t0\t2\n')
            (cwd/'primitives.tsv').write_text('LUT*\t50\n');(cwd/'internal').mkdir()
        logfile.write_text(text);log(text)
        return {'command':[str(c) for c in command],'returncode':0,'seconds':.01,'log':logfile.name}
    monkeypatch.setattr(runner,'execute',execute)
    def snapshot(folder,root):
        source=(root/'design.sv').read_text();endpoint='remaining_reg[0]/D';start='remaining_reg[0]/Q'
        cell=Cell(name='remaining_reg[0]',primitive='FDRE',sequential=True)
        paths=[TimingPath(id='P1',analysis='setup',startpoint=start,endpoint=endpoint,start_clock='clk',end_clock='clk',slack_ns=-1.,corner='Slow',path_type='Setup')]
        return Session(name='fixture',part='xc7z020clg400-1',vivado='2024.2',stage='routed',top='counter',
            summary={'setup':Summary(worst_slack_ns=-1.,total_negative_slack_ns=-2.,failing_endpoints=2,total_endpoints=2),
                     'hold':Summary(worst_slack_ns=.1,total_negative_slack_ns=0.,failing_endpoints=0,total_endpoints=2)},
            cells={cell.name:cell},pins={p:Pin(name=p,cell=cell.name) for p in (start,endpoint)},paths=paths,
            clocks=[Clock(name='clk',period_ns=2.,waveform_ns=[0.,1.],generated=False)],
            sources=[Source(path=str(root/'design.sv'),text=source,sha256=sha256(source.encode()).hexdigest())])
    monkeypatch.setattr(runner,'_snapshot_session',snapshot)
    return executable,calls,execute


def test_source_exact_plans_do_not_modify_bundles():
    for name,width,op in [('counter32',32,'>='),('counter64',64,'>')]:
        plan=plan_counter(name)
        assert plan.original==f'remaining {op} amount'
        assert f'remaining[{width-1}:4]' in plan.replacement
        assert plan.baseline[:plan.start]+plan.replacement.encode()+plan.baseline[plan.end:]==plan.candidate
        assert b'a !== expected' in plan.testbench
        assert plan_counter(name)==plan


@pytest.mark.parametrize('filename',['design.sv','timing.xdc','tb.sv'])
def test_changed_bundled_inputs_fail_closed(tmp_path,monkeypatch,filename):
    import timinglens.experiments.counters as counters
    shutil.copytree(counters.example_path()/'counter32',tmp_path/'counter32')
    path=tmp_path/'counter32'/filename;path.write_bytes(path.read_bytes()+b'\n')
    monkeypatch.setattr(counters,'example_path',lambda:tmp_path)
    with pytest.raises(ValueError,match='changed'):plan_counter('counter32')


def test_success_publishes_four_verified_runs_and_both_comparisons(tmp_path,fake_tools):
    tool,calls,_=fake_tools;job=tmp_path/'new isolated job'
    result=run_counter(CounterRequest('counter32',job,verilator=str(tool)))
    state=json.loads((job/'job.json').read_text());assert state['status']=='completed'
    assert calls==[('new isolated job','vivado-version.log'),('new isolated job','verilator-version.log'),('simulation','build.log'),('simulation','simulation.log'),('baseline','vivado.log'),('candidate','vivado.log')]
    before,after=[load_run(p) for p in result.register_pair]
    assert before.context.sources!=after.context.sources
    assert before.context.constraints==after.context.constraints
    assert before.context.directives==after.context.directives
    assert len(after.checks)==2 and all(c.status=='passed' for c in after.checks)
    assert after.context.checkpoint_sha256==sha256((job/'candidate/routed.dcp').read_bytes()).hexdigest()
    assert after.change_diff and not before.change_diff
    assert state['pairs']['register_paths']['acceptance']=='blocked'
    assert (job/'comparisons/design/report.html').is_file()
    original=(job/'job.json').read_bytes()
    with pytest.raises(FileExistsError):run_counter(CounterRequest('counter32',job,verilator=str(tool)))
    assert (job/'job.json').read_bytes()==original


@pytest.mark.parametrize('stage',['simulation.log','vivado.log'])
def test_tool_failure_retains_evidence_and_never_publishes_pair(tmp_path,fake_tools,monkeypatch,stage):
    tool,calls,execute=fake_tools
    def fail(command,cwd,logfile,*args):
        if logfile.name==stage:
            logfile.write_text('deliberate tool failure')
            raise runner.ProcessFailure('exit 7')
        return execute(command,cwd,logfile,*args)
    monkeypatch.setattr(runner,'execute',fail);job=tmp_path/'failed'
    with pytest.raises(JobFailure) as error:run_counter(CounterRequest('counter32',job,verilator=str(tool)))
    assert error.value.status=='failed'
    state=json.loads((job/'job.json').read_text());assert state['status']=='failed' and not state['pairs']
    assert state['steps'][-1]['status']=='failed' and state['steps'][-1]['error']=='exit 7'
    assert not (job/'candidate/routed.dcp').exists()


def test_cancellation_between_variants_preserves_baseline_only(tmp_path,fake_tools):
    tool,_,_=fake_tools;cancel=Event();job=tmp_path/'cancelled'
    def progress(phase):
        if phase=='baseline capture':cancel.set()
    with pytest.raises(JobFailure) as error:run_counter(CounterRequest('counter64',job,verilator=str(tool)),progress=progress,cancel=cancel)
    assert error.value.status=='cancelled'
    state=json.loads((job/'job.json').read_text());assert state['status']=='cancelled' and not state['pairs']
    assert (job/'runs/baseline.register_paths.run.json').exists()
    assert not (job/'candidate/routed.dcp').exists()


def test_changed_staged_source_is_rejected_after_tool(tmp_path,fake_tools,monkeypatch):
    tool,_,execute=fake_tools
    def mutate(command,cwd,logfile,*args):
        result=execute(command,cwd,logfile,*args)
        if logfile.name=='vivado.log':
            source=cwd/'design.sv';source.chmod(0o644);source.write_bytes(source.read_bytes()+b'// changed')
        return result
    monkeypatch.setattr(runner,'execute',mutate);job=tmp_path/'mutated'
    with pytest.raises(JobFailure,match='Staged input changed'):run_counter(CounterRequest('counter32',job,verilator=str(tool)))
    assert not (job/'runs').exists();assert plan_counter('counter32')


def test_lock_prevents_second_job_without_creating_its_directory(tmp_path,fake_tools):
    tool,_,_=fake_tools;target=tmp_path/'concurrent'
    with runner_lock():
        with pytest.raises(ValueError,match='Another TimingLens'):run_counter(CounterRequest('counter32',target,verilator=str(tool)))
    assert not target.exists()


def test_missing_tool_retains_failed_manifest(tmp_path,monkeypatch):
    monkeypatch.setenv('TIMINGLENS_REPO_ROOT',str(tmp_path))
    def missing(_):raise ValueError('missing tool')
    monkeypatch.setattr(runner,'discover',missing)
    job=tmp_path/'no-tool'
    with pytest.raises(JobFailure,match='missing tool'):run_counter(CounterRequest('counter32',job))
    assert json.loads((job/'job.json').read_text())['status']=='failed'
    assert (job/'candidate.patch').is_file()


def test_invalid_recipe_timeout_and_symlink_output(tmp_path):
    for name,timeout in [('other',1.),('counter32',float('nan')),('counter64',0.)]:
        with pytest.raises(ValueError):CounterRequest(name,tmp_path/'fresh',timeout=timeout).validate()
    target=tmp_path/'link';target.symlink_to(tmp_path/'absent',target_is_directory=True)
    with pytest.raises(FileExistsError):CounterRequest('counter32',target).validate()


def test_cli_preview_runs_no_tools_or_writes(tmp_path,monkeypatch,capsys):
    from timinglens.cli import main
    monkeypatch.chdir(tmp_path)
    assert main(['experiment','--example','counter64','--preview'])==0
    assert '|remaining[63:4]' in capsys.readouterr().out and not list(tmp_path.iterdir())
    assert main(['experiment','--example','counter32'])==1


def test_capture_rejects_foreign_source_before_decoder_reads_it(tmp_path,monkeypatch):
    def forbidden(*args):raise AssertionError('Decoder must not read a foreign source')
    monkeypatch.setattr(runner,'decode',forbidden)
    fields=['/never/read/outside.sv','SystemVerilog']
    (tmp_path/'records.tsv').write_text('SOURCE\t'+'\t'.join(s.encode().hex() for s in fields)+'\n')
    with pytest.raises(ValueError,match='outside its isolated directory'):runner._snapshot_session(tmp_path,tmp_path)


def test_sweep_runs_four_isolated_builds_one_simulation_and_publishes(tmp_path,fake_tools):
    from timinglens.experiments.sweep import load_sweep
    tool,calls,_=fake_tools;job=tmp_path/'sweep'
    result=run_counter(CounterRequest('counter32',job,verilator=str(tool),strategies=('default','explore','extra_timing')))
    assert result.sweep==job/'sweep.json' and result.status=='completed'
    assert [folder for folder,log in calls if log=='vivado.log']==['baseline','candidate','candidate_explore','candidate_extra_timing']
    assert sum(log=='simulation.log' for _,log in calls)==1
    assert len({(job/v/'design.sv').read_bytes() for v in ('candidate','candidate_explore','candidate_extra_timing')})==1
    assert len({(job/v/'timing.xdc').read_bytes() for v in ('baseline','candidate','candidate_explore','candidate_extra_timing')})==1
    assert (job/'sweep.html').is_file() and (job/'ranking.json').is_file()
    review=load_sweep(result.sweep)
    assert all(row.status=='completed' and row.rank is None for row in review.rows) # fixture deliberately lacks DRC/pulse evidence


def test_failed_optional_recipe_continues_and_exports_partial_sweep(tmp_path,fake_tools,monkeypatch):
    from timinglens.experiments.sweep import load_sweep
    tool,calls,execute=fake_tools;job=tmp_path/'partial'
    def fail(command,cwd,logfile,*args):
        if cwd.name=='candidate_explore':raise runner.ProcessFailure('timed out fixture')
        return execute(command,cwd,logfile,*args)
    monkeypatch.setattr(runner,'execute',fail)
    result=run_counter(CounterRequest('counter64',job,verilator=str(tool),strategies=('default','explore','extra_timing')))
    assert result.status=='partial' and ('candidate_extra_timing','vivado.log') in calls
    rows={r.strategy:r for r in load_sweep(result.sweep).rows}
    assert rows['explore'].rank is None and rows['explore'].run is None and 'timed out' in rows['explore'].reason
    assert rows['extra_timing'].status=='completed'


@pytest.mark.parametrize('failure',['cancel','tamper','reference'])
def test_sweep_abort_stops_future_variants_and_preserves_completed_records(tmp_path,fake_tools,monkeypatch,failure):
    from timinglens.experiments.sweep import load_sweep
    tool,calls,execute=fake_tools;job=tmp_path/failure
    def fail(command,cwd,logfile,*args):
        if logfile.name=='vivado.log' and cwd.name==('candidate' if failure=='reference' else 'candidate_explore'):
            if failure=='reference':raise runner.ProcessFailure('reference failed')
            if failure=='cancel':raise runner.Cancelled('cancelled recipe')
            source=cwd/'design.sv';source.chmod(0o644);source.write_bytes(source.read_bytes()+b'// changed')
        return execute(command,cwd,logfile,*args)
    monkeypatch.setattr(runner,'execute',fail)
    with pytest.raises(JobFailure) as error:run_counter(CounterRequest('counter32',job,verilator=str(tool),strategies=('default','explore','extra_timing')))
    assert error.value.status==('cancelled' if failure=='cancel' else 'failed')
    assert ('candidate_extra_timing','vivado.log') not in calls
    review=load_sweep(job/'sweep.json');rows={r.strategy:r for r in review.rows}
    assert rows['extra_timing'].status=='not_run'
    assert rows['default'].status==('failed' if failure=='reference' else 'completed')
    assert not (job/'runs/candidate_explore.design.run.json').exists()
