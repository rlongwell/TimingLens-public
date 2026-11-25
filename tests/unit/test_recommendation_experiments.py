from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from threading import Event

import pytest

from timinglens.analysis.engine import analyze
from timinglens.experiments import load_run
from timinglens.experiments import recommendation as catalog
from timinglens.experiments import recommendation_runner as runner
from timinglens.experiments.models import canonical
from timinglens.experiments.recommendation import EXAMPLES,build_script,eligibility,prepare_experiment,revalidate
from timinglens.experiments.recommendation_runner import RecommendationRequest,read_recommendation_job,run_recommendation
from timinglens.experiments.runner import JobFailure,runner_lock
from timinglens.timing.models import Source


@pytest.mark.parametrize('name',EXAMPLES)
def test_supported_plan_freezes_evidence_and_revalidates(name,recommendation_factory):
    result,plan,prepared=recommendation_factory(name)
    assert revalidate(prepared)==prepared and prepared.example==name
    assert prepared.document()['source_sha256']==result.session.sources[0].sha256
    result.session.sources.clear()
    assert revalidate(prepared)==prepared # the GUI result can change without changing this request
    assert 'RTL and constraint diff: none' in prepared.preview()


@pytest.mark.parametrize('change',['source','constraint','missing_source','extra_source','clock','release','device','stage','dfx','missing_detail','clean','constraint_check'])
def test_unverified_or_unsupported_evidence_cannot_launch(change,recommendation_factory):
    result,plan,_=recommendation_factory();session=result.session
    if change=='source':session=session.model_copy(update={'sources':[session.sources[0].model_copy(update={'text':'different'}),session.sources[1]]})
    elif change=='constraint':session=session.model_copy(update={'sources':[session.sources[0],session.sources[1].model_copy(update={'sha256':'a'*64})]})
    elif change=='missing_source':session=session.model_copy(update={'sources':[]})
    elif change=='extra_source':session=session.model_copy(update={'sources':[*session.sources,Source(path='/never/read/extra.sv',sha256='a'*64)]})
    elif change=='clock':session=session.model_copy(update={'clocks':[session.clocks[0].model_copy(update={'period_ns':3.})]})
    elif change=='release':session=session.model_copy(update={'vivado':'2026.1'})
    elif change=='device':session=session.model_copy(update={'part':'other'})
    elif change=='stage':session=session.model_copy(update={'stage':'unknown'})
    elif change=='dfx':session=session.model_copy(update={'cells':{k:v.model_copy(update={'properties':{'HD.RECONFIGURABLE':'1'}}) for k,v in session.cells.items()}})
    elif change=='missing_detail':session=session.model_copy(update={'paths':[p.model_copy(update={'arcs':[]}) for p in session.paths]})
    elif change=='clean':session=session.model_copy(update={'paths':[p.model_copy(update={'slack_ns':1.}) for p in session.paths]})
    else:session=session.model_copy(update={'timing_checks':{'no_clock':1}})
    changed=analyze(session)
    assert eligibility(changed,plan)[0] is None
    with pytest.raises(ValueError):prepare_experiment(changed,plan)


def test_missing_old_constraint_snapshot_is_explicit_not_a_replay(recommendation_factory):
    result,plan,_=recommendation_factory()
    session=result.session.model_copy(update={'sources':[result.session.sources[0],Source(path='/never/read/timing.xdc')]})
    changed=analyze(session);plan=next(p for g in changed.investigations for p in g.plans if p.id=='vivado.remap')
    prepared=prepare_experiment(changed,plan)
    assert 'not the comparison baseline' in prepared.preview() and 'Missing constraint bytes' in prepared.preview()


def test_tampered_plan_never_becomes_executable(tmp_path,recommendation_factory):
    result,plan,prepared=recommendation_factory()
    forged=replace(plan,commands=('exec dangerous-command',))
    with pytest.raises(ValueError):prepare_experiment(result,forged)
    with pytest.raises(ValueError):revalidate(replace(prepared,selection={**prepared.selection,'commands':['exec dangerous-command']}))
    assert not list(tmp_path.iterdir())


def test_changed_bundled_bytes_are_refused(tmp_path,monkeypatch,recommendation_factory):
    import shutil
    result,plan,_=recommendation_factory()
    shutil.copytree(catalog.example_path()/'deep',tmp_path/'deep')
    (tmp_path/'deep/design.sv').write_text('changed')
    monkeypatch.setattr(catalog,'example_path',lambda:tmp_path)
    with pytest.raises(ValueError,match='changed'):prepare_experiment(result,plan)


def test_recipe_commands_preserve_inputs_and_correct_start_stage():
    baseline=build_script('deep').decode();remap=build_script('deep','vivado.remap').decode();fanout=build_script('fanout','vivado.fanout').decode()
    assert 'write_checkpoint placed.dcp' in baseline
    assert 'opt_design -directive ExploreWithRemap' in remap and 'route_design -directive NoTimingRelaxation' in remap
    assert 'open_checkpoint placement.dcp' in fanout and 'synth_design' not in fanout and 'place_design ' not in fanout
    assert 'phys_opt_design -directive AggressiveFanoutOpt' in fanout
    assert all('set_property DONT_TOUCH' not in s and 'read_xdc timing.xdc' in s for s in (baseline,remap))
    with pytest.raises(ValueError):build_script('deep','exec arbitrary')


def test_fanout_preview_records_only_commands_actually_executed(recommendation_factory):
    prepared=recommendation_factory('fanout')[2]
    assert prepared.document()['commands']==['open_checkpoint placement.dcp','phys_opt_design -directive AggressiveFanoutOpt','route_design -directive Default']


@pytest.mark.parametrize('name',['deep','fanout'])
def test_job_builds_only_pinned_copies_and_imports_portable_pair(tmp_path,recommendation_factory,recommendation_tools,name):
    tool,calls,_,_=recommendation_tools;prepared=recommendation_factory(name)[2];job=tmp_path/'job'
    result=run_recommendation(RecommendationRequest(prepared,job,verilator=str(tool)))
    assert [n for n,log,_ in calls if log=='vivado.log']==['baseline','candidate']
    assert (job/'baseline/design.sv').read_bytes()==(job/'candidate/design.sv').read_bytes()
    before,after=[load_run(p) for p in result.register_pair]
    assert before.context.sources==after.context.sources and before.context.constraints==after.context.constraints
    assert before.context.directives!=after.context.directives and 'plan.json' in after.attachments and 'trigger.json' in after.attachments
    assert after.context.checkpoint_sha256==sha256((job/'candidate/routed.dcp').read_bytes()).hexdigest()
    assert read_recommendation_job(job)==result
    if name=='fanout':
        assert (job/'baseline/placed.dcp').read_bytes()==(job/'candidate/placement.dcp').read_bytes()
        assert json.loads((job/'candidate/build-record.json').read_bytes())['placement_parent_sha256']==sha256(b'fixture placement').hexdigest()
    with pytest.raises(FileExistsError):run_recommendation(RecommendationRequest(prepared,job,verilator=str(tool)))


@pytest.mark.parametrize('failure',['simulation','baseline','candidate','tamper','cancel','unsupported_baseline'])
def test_failure_and_cancel_stop_future_work_and_keep_evidence(tmp_path,monkeypatch,recommendation_factory,recommendation_tools,failure):
    tool,calls,execute,snapshot=recommendation_tools;job=tmp_path/failure;prepared=recommendation_factory()[2]
    def fake(command,cwd,logfile,*args):
        if (failure=='simulation' and logfile.name=='simulation.log') or (failure in {'baseline','candidate'} and cwd.name==failure and logfile.name=='vivado.log'):
            raise runner.ProcessFailure('deliberate fixture failure')
        if failure=='cancel' and cwd.name=='candidate':raise runner.Cancelled('deliberate cancellation')
        result=execute(command,cwd,logfile,*args)
        if failure=='tamper' and cwd.name=='baseline' and logfile.name=='vivado.log':
            p=cwd/'design.sv';p.chmod(0o644);p.write_text('changed')
        return result
    if failure=='unsupported_baseline':
        def clean(folder,source_root):
            s=snapshot(folder,source_root);return s.model_copy(update={'paths':[p.model_copy(update={'slack_ns':1.}) for p in s.paths]})
        monkeypatch.setattr(runner,'snapshot',clean)
    monkeypatch.setattr(runner,'execute',fake)
    with pytest.raises(JobFailure) as error:run_recommendation(RecommendationRequest(prepared,job,verilator=str(tool)))
    assert error.value.status==('cancelled' if failure=='cancel' else 'failed')
    assert not (job/'result.json').exists() and (job/'trigger.json').exists()
    assert not any(n=='candidate' and log=='vivado.log' for n,log,_ in calls)
    if failure in {'candidate','cancel','unsupported_baseline'}:assert (job/'runs/baseline.design.run.json').exists()


def test_shared_lock_stops_other_experiment_before_staging(tmp_path,recommendation_factory,monkeypatch):
    monkeypatch.setenv('TIMINGLENS_REPO_ROOT',str(tmp_path))
    prepared=recommendation_factory()[2]
    with runner_lock():
        with pytest.raises(ValueError,match='Another TimingLens'):run_recommendation(RecommendationRequest(prepared,tmp_path/'blocked'))
    assert not (tmp_path/'blocked').exists()


def test_snapshot_rejects_foreign_source_before_decoder(tmp_path,monkeypatch):
    def forbidden(*_):raise AssertionError('Must not read a foreign source')
    monkeypatch.setattr(runner,'decode',forbidden)
    (tmp_path/'records.tsv').write_text('SOURCE\t'+'/never/read/source.sv'.encode().hex()+'\t'+b'SystemVerilog'.hex()+'\n')
    with pytest.raises(ValueError,match='outside'):runner.snapshot(tmp_path,tmp_path)


def test_completed_job_rejects_changed_or_redirected_records(tmp_path,recommendation_factory,recommendation_tools):
    tool,_,_,_=recommendation_tools;job=tmp_path/'job'
    result=run_recommendation(RecommendationRequest(recommendation_factory()[2],job,verilator=str(tool)))
    file=result.register_pair[1];file.write_bytes(file.read_bytes()+b' ')
    with pytest.raises(ValueError,match='digest mismatch'):read_recommendation_job(job)
    file.unlink();file.symlink_to(tmp_path/'outside')
    with pytest.raises(ValueError,match='outside'):read_recommendation_job(job)


@pytest.mark.parametrize('filename',['job.json','result.json'])
def test_restoring_fifo_cannot_hang_the_worker(tmp_path,filename):
    import os
    os.mkfifo(tmp_path/filename)
    with pytest.raises(ValueError,match='regular file'):read_recommendation_job(tmp_path)


@pytest.mark.parametrize('failure',['version','simulation_marker','build_marker'])
def test_success_exit_without_valid_tool_evidence_is_not_success(tmp_path,monkeypatch,recommendation_factory,recommendation_tools,failure):
    tool,calls,execute,_=recommendation_tools
    def fake(command,cwd,logfile,*args):
        result=execute(command,cwd,logfile,*args)
        if failure=='version' and logfile.name=='vivado-version.log':logfile.write_text('Vivado v2023.1')
        elif failure=='simulation_marker' and logfile.name=='simulation.log':logfile.write_text('early exit')
        elif failure=='build_marker' and logfile.name=='vivado.log':(cwd/'completed.txt').write_text('early exit')
        return result
    monkeypatch.setattr(runner,'execute',fake)
    with pytest.raises(JobFailure):run_recommendation(RecommendationRequest(recommendation_factory()[2],tmp_path/'job',verilator=str(tool)))
    assert not any(name=='candidate' for name,_,_ in calls) and not (tmp_path/'job/result.json').exists()


def test_cli_preview_no_writes_or_tools(tmp_path,recommendation_factory,capsys,monkeypatch):
    from timinglens.cli import main
    result,_,_=recommendation_factory();session=tmp_path/'analysis.json';session.write_text(result.session.model_dump_json())
    monkeypatch.setattr(runner,'execute',lambda *_:pytest.fail('preview cannot execute'))
    assert main(['try-experiment','--session',str(session),'--plan','vivado.remap','--preview'])==0
    assert 'ExploreWithRemap' in capsys.readouterr().out and len(list(tmp_path.iterdir()))==1
    assert main(['try-experiment','--session',str(session),'--plan','vivado.fanout','--preview'])==1
