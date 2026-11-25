from dataclasses import replace
from hashlib import sha256
import json
from threading import Event
import pytest

from timinglens.experiments.priority_variants import VARIANTS,SWEEP_ID,candidate
from timinglens.experiments.recommendation import bundled_inputs,build_script,revalidate
from timinglens.experiments.recommendation_runner import RecommendationRequest,run_recommendation,read_recommendation_job
from timinglens.experiments.rtl_sweep_runner import BaselineReference
from timinglens.experiments.rtl_sweep import load_rtl_sweep,read_manifest,write_manifest,export_rtl_sweep,pair_paths
from timinglens.experiments.io import load_run,write_run
from timinglens.experiments.models import Artifact
from timinglens.experiments.equivalence import discover_yosys,command_prefix,SCRIPT,verify_proof,MARKER
from timinglens.experiments.process import execute,ProcessFailure


def test_catalog_preview_is_frozen_and_same_recipe(rtl_sweep_prepared):
    p=rtl_sweep_prepared
    assert p.rtl_sweep and revalidate(p)==p and len(p.selection['changes'])==3
    assert all(sha256(candidate(bundled_inputs('priority')[0],k)).hexdigest()==v.sha256 for k,v in VARIANTS.items())
    assert build_script('priority')==build_script('priority',SWEEP_ID)
    assert all(v.title in p.preview() for v in VARIANTS.values())
    for key in VARIANTS:assert revalidate(replace(p,variant=key)).variant==key
    with pytest.raises(ValueError):revalidate(replace(p,variant='injected'))


def test_four_builds_individual_gates_and_shared_baseline(tmp_path,rtl_job_factory,rtl_tools):
    job=rtl_job_factory(tmp_path/'job');_,calls,_,_=rtl_tools
    assert job.status=='completed' and read_recommendation_job(job.directory)==job
    builds=[n for n,log,_ in calls if log=='vivado.log'];assert builds==['baseline','candidate','candidate','candidate']
    assert sum(log=='simulation.log' for _,log,_ in calls)==6
    assert sum(log=='equivalence.log' for _,log,_ in calls)==3
    for pop in ('register_paths','design'):
        review=load_rtl_sweep(job.sweep_path,pop)
        assert len(review.rows)==4 and all(r.frontier=='Frontier' for r in review.rows)
        assert all(r.comparison.acceptance=='blocked' for r in review.rows)
        assert all(r.comparison.before==review.baseline for r in review.rows)
        for row in review.rows[1:]:
            assert row.proof=='passed' and row.comparison.before.context.directives==row.run.context.directives
            assert load_run(pair_paths(review,row.variant)[1])==row.run
    for key in ('grouped','mask'):
        record=json.loads((job.directory/f'variants/{key}/baseline/build-record.json').read_text())
        assert record['baseline_reuse']['directory'].endswith('/balanced/baseline')
        assert not any(s['phase']=='baseline implementation' for s in json.loads((job.directory/f'variants/{key}/job.json').read_text())['steps'])
    portable=export_rtl_sweep(job.sweep_path,tmp_path/'export',10)
    assert load_rtl_sweep(portable/'rtl-sweep.json',max_luts=10).document()==load_rtl_sweep(job.sweep_path,max_luts=10).document()
    with pytest.raises(FileExistsError):export_rtl_sweep(job.sweep_path,portable)


@pytest.mark.parametrize('fault',['proof','simulation','candidate','baseline','cancel','reuse_changed'])
def test_failures_continue_candidates_but_shared_failure_or_cancel_stops(tmp_path,rtl_tools,rtl_sweep_prepared,monkeypatch,fault):
    from timinglens.experiments import recommendation_runner as runner
    tool,calls,old,_=rtl_tools
    def fake(command,cwd,logfile,*args):
        key=cwd.parent.name
        if ((fault=='proof' and key=='balanced' and logfile.name=='equivalence.log') or
            (fault=='simulation' and cwd.parent.parent.name=='balanced' and logfile.name=='simulation.log') or
            (fault in {'candidate','baseline'} and key=='balanced' and cwd.name==fault and logfile.name=='vivado.log')):raise ProcessFailure('deliberate '+fault)
        if fault=='cancel' and key=='grouped' and logfile.name=='equivalence.log':raise runner.Cancelled('deliberate cancellation')
        if fault=='reuse_changed' and key=='grouped' and logfile.name=='equivalence.log':
            source=tmp_path/'job/variants/balanced/baseline/routed.dcp';source.chmod(0o644);source.write_bytes(b'changed')
        return old(command,cwd,logfile,*args)
    monkeypatch.setattr(runner,'execute',fake)
    job=run_recommendation(RecommendationRequest(rtl_sweep_prepared,tmp_path/'job',verilator=str(tool)))
    review=load_rtl_sweep(job.sweep_path)
    states=[r.status for r in review.rows[1:]]
    if fault=='cancel':assert job.status=='cancelled' and states==['completed','cancelled','not_run']
    elif fault in {'baseline','reuse_changed'}:
        assert states[-1]=='not_run' and job.status==('failed' if fault=='baseline' else 'partial')
    else:
        assert job.status=='partial' and states==['failed','completed','completed']
        assert [n for n,log,_ in calls if log=='vivado.log'].count('baseline')==1
    failed=next(r for r in review.rows if r.status in {'failed','cancelled'})
    assert failed.run is None and failed.frontier=='Not comparable' and 'deliberate' in '\n'.join(failed.explanations) if fault!='reuse_changed' else failed.run is None
    export_rtl_sweep(job.sweep_path,tmp_path/'portable')


def test_cancel_before_first_candidate_is_portable(tmp_path,rtl_sweep_prepared,rtl_tools):
    cancel=Event();cancel.set()
    job=run_recommendation(RecommendationRequest(rtl_sweep_prepared,tmp_path/'cancelled'),cancel=cancel)
    assert job.status=='cancelled' and not rtl_tools[1]
    review=load_rtl_sweep(job.sweep_path);assert all(r.run is None for r in review.rows)


def alter_record(path,key,change):
    manifest=read_manifest(path)
    ref=manifest.baseline['register_paths'] if key=='baseline' else next(v for v in manifest.variants if v.id==key).records['register_paths']
    target=path.parent/ref.path;run=load_run(target);run=change(run);target.unlink();write_run(target,run)
    refs=manifest.baseline if key=='baseline' else next(v for v in manifest.variants if v.id==key).records
    refs['register_paths']=ref.model_copy(update={'sha256':sha256(target.read_bytes()).hexdigest()});write_manifest(path,manifest)


def changed(run,wns=None,luts=None,hold=None,missing=False):
    timing=dict(run.timing);attachments=dict(run.attachments);metrics=dict(run.metrics)
    if wns is not None:timing['setup']=timing['setup'].model_copy(update={'worst_slack_ns':wns,'total_negative_slack_ns':min(0.,wns)})
    if hold is not None:timing['hold']=timing['hold'].model_copy(update={'worst_slack_ns':hold})
    if luts is not None:metrics['area.lut_cells']=float(luts)
    session=run.session
    if missing:
        metrics.pop('area.ff',None)
        session=session.model_copy(update={'reports':{k:v.replace('| Register as Flip Flop | 33 |\n','') for k,v in session.reports.items()}})
    for key in attachments:
        if key.endswith('/registers.tsv'):attachments[key]=''.join(f'{kind}\t{s.worst_slack_ns}\t{s.total_negative_slack_ns}\t{s.failing_endpoints}\t{s.total_endpoints}\n' for kind,s in timing.items())
        if key.endswith('/primitives.tsv') and luts is not None:attachments[key]=f'LUT*\t{luts}\n'
    artifacts=[a.model_copy(update={'sha256':sha256(attachments[a.name].encode()).hexdigest()}) if a.name in attachments else a for a in run.artifacts]
    return run.model_copy(update={'timing':timing,'metrics':metrics,'attachments':attachments,'artifacts':artifacts,'session':session})


def test_frontier_includes_original_and_regressions_and_limit_are_separate(tmp_path,rtl_job_factory):
    job=rtl_job_factory(tmp_path/'job');path=job.sweep_path
    alter_record(path,'balanced',lambda r:changed(r,wns=-.2,luts=24))
    alter_record(path,'grouped',lambda r:changed(r,wns=-.5,luts=16,hold=.05))
    alter_record(path,'mask',lambda r:changed(r,wns=-.8,luts=20))
    review=load_rtl_sweep(path,max_luts=18)
    assert [r.frontier for r in review.rows]==['Frontier','Frontier','Frontier','Dominated']
    assert review.rows[1].review_limits=='Over LUT limit' and review.rows[1].comparison.outcome=='improved'
    assert review.rows[2].review_limits=='Regression' and review.rows[2].comparison.outcome=='regressed'
    assert 'Hold WNS' in '\n'.join(review.rows[2].explanations)
    alter_record(path,'baseline',lambda r:changed(r,missing=True))
    assert all(r.frontier=='Not comparable' for r in load_rtl_sweep(path).rows)
    for limit in (0,-1,True,1.2):
        with pytest.raises(ValueError):load_rtl_sweep(path,max_luts=limit)


@pytest.mark.parametrize('fault',['manifest','digest','path','symlink','proof','identity','script'])
def test_portable_import_rejects_tampering(tmp_path,rtl_job_factory,fault):
    path=rtl_job_factory(tmp_path/'job').sweep_path;manifest=read_manifest(path)
    ref=manifest.variants[0].records['register_paths'];target=path.parent/ref.path
    if fault=='manifest':
        doc=json.loads(path.read_text());doc['sweep']['status']='partial';path.write_text(json.dumps(doc))
    elif fault=='digest':target.write_bytes(target.read_bytes()+b' ')
    elif fault=='path':manifest.variants[0].records['register_paths']=ref.model_copy(update={'path':'../outside.json'});write_manifest(path,manifest)
    elif fault=='symlink':outside=tmp_path/'outside';target.rename(outside);target.symlink_to(outside)
    else:
        run=load_run(target)
        if fault=='proof':
            attachments=dict(run.attachments);attachments.pop('equivalence/proof.json');run=run.model_copy(update={'attachments':attachments})
        elif fault=='identity':run=run.model_copy(update={'context':run.context.model_copy(update={'design_key':'wrong'})})
        else:
            attachments=dict(run.attachments);attachments['candidate/batch.tcl']='other script'
            artifacts=[a.model_copy(update={'sha256':sha256(b'other script').hexdigest()}) if a.name=='candidate/batch.tcl' else a for a in run.artifacts]
            run=run.model_copy(update={'attachments':attachments,'artifacts':artifacts})
        target.unlink();write_run(target,run);manifest.variants[0].records['register_paths']=ref.model_copy(update={'sha256':sha256(target.read_bytes()).hexdigest()});write_manifest(path,manifest)
    with pytest.raises(ValueError):load_rtl_sweep(path)


@pytest.mark.parametrize('key',list(VARIANTS))
@pytest.mark.parametrize('mutated',[False,True])
def test_real_equivalence_for_every_variant_and_wrong_result(tmp_path,key,mutated):
    try:tool=discover_yosys()
    except ValueError:pytest.skip('Install formal extra for real proof checks')
    source=bundled_inputs('priority')[0];rtl=candidate(source,key)
    if mutated:rtl=rtl.replace(b'result <= ',b'result <= ~')
    (tmp_path/'baseline.sv').write_bytes(source);(tmp_path/'candidate.sv').write_bytes(rtl);(tmp_path/'equivalence.ys').write_text(SCRIPT)
    execute([*command_prefix(),tool,'-V'],tmp_path,tmp_path/'version.log',Event(),180)
    if mutated:
        with pytest.raises(ProcessFailure):execute([*command_prefix(),tool,'-s','equivalence.ys'],tmp_path,tmp_path/'equivalence.log',Event(),180)
        assert MARKER not in (tmp_path/'equivalence.log').read_text()
    else:
        execute([*command_prefix(),tool,'-s','equivalence.ys'],tmp_path,tmp_path/'equivalence.log',Event(),180)
        assert verify_proof(tmp_path)['matched_points']==67


def test_unbuilt_pass_claim_requires_its_portable_proof(tmp_path,rtl_tools,rtl_sweep_prepared,monkeypatch):
    from timinglens.experiments import recommendation_runner as runner
    tool,calls,old,_=rtl_tools
    def fail(command,cwd,logfile,*args):
        if cwd.parent.name=='balanced' and cwd.name=='candidate' and logfile.name=='vivado.log':raise ProcessFailure('deliberate implementation failure')
        return old(command,cwd,logfile,*args)
    monkeypatch.setattr(runner,'execute',fail)
    job=run_recommendation(RecommendationRequest(rtl_sweep_prepared,tmp_path/'job',verilator=str(tool)))
    manifest=read_manifest(job.sweep_path);failed=manifest.variants[0]
    assert failed.status=='failed' and failed.proof=='passed' and failed.proof_record
    exported=export_rtl_sweep(job.sweep_path,tmp_path/'export')
    assert load_rtl_sweep(exported/'rtl-sweep.json').rows[1].proof=='passed'
    target=exported/failed.proof_record.path;target.write_bytes(target.read_bytes()+b' ')
    with pytest.raises(ValueError,match='proof digest'):load_rtl_sweep(exported/'rtl-sweep.json')
    manifest.variants[0]=failed.model_copy(update={'proof_record':None});write_manifest(job.sweep_path,manifest)
    with pytest.raises(ValueError,match='retained proof'):load_rtl_sweep(job.sweep_path)


def test_nonregular_manifest_and_shared_lock_are_rejected(tmp_path,rtl_sweep_prepared,monkeypatch):
    import os
    from timinglens.experiments.runner import runner_lock
    fifo=tmp_path/'fifo';os.mkfifo(fifo)
    with pytest.raises(ValueError,match='regular'):read_manifest(fifo)
    monkeypatch.setenv('TIMINGLENS_REPO_ROOT',str(tmp_path))
    with runner_lock():
        with pytest.raises(ValueError,match="Another TimingLens"):run_recommendation(RecommendationRequest(rtl_sweep_prepared,tmp_path/'job'))
    assert not (tmp_path/'job').exists()


def test_cli_sweep_preview_does_not_run_tools(tmp_path,rtl_sweep_prepared,monkeypatch,capsys):
    from timinglens.cli import main
    from timinglens.experiments import recommendation_runner as runner
    path=tmp_path/'session.json';path.write_text(rtl_sweep_prepared.trigger_json)
    monkeypatch.setattr(runner,'execute',lambda *_:pytest.fail('Preview must not run tools'))
    assert main(['try-experiment','--session',str(path),'--plan',SWEEP_ID,'--preview'])==0
    text=capsys.readouterr().out
    assert all(v.title in text for v in VARIANTS.values()) and 'one shared' in text.lower() or 'one fresh original' in text.lower()
    assert list(tmp_path.iterdir())==[path]


@pytest.mark.parametrize('fault',['embedded_source','lut_count','missing_hold'])
def test_native_identity_and_missing_timing_are_consistent(tmp_path,rtl_job_factory,fault):
    job=rtl_job_factory(tmp_path/'job')
    def change(run):
        if fault=='embedded_source':
            sources=[s.model_copy(update={'text':'changed source','sha256':sha256(b'changed source').hexdigest()}) if s.path.endswith('design.sv') else s for s in run.session.sources]
            return run.model_copy(update={'session':run.session.model_copy(update={'sources':sources})})
        if fault=='lut_count':return run.model_copy(update={'metrics':{**run.metrics,'area.lut_cells':999}})
        timing={'setup':run.timing['setup']};attachments={k:'\n'.join(line for line in v.splitlines() if not line.startswith('hold\t'))+'\n' if k.endswith('/registers.tsv') else v for k,v in run.attachments.items()}
        artifacts=[a.model_copy(update={'sha256':sha256(attachments[a.name].encode()).hexdigest()}) if a.name in attachments else a for a in run.artifacts]
        return run.model_copy(update={'timing':timing,'attachments':attachments,'artifacts':artifacts})
    alter_record(job.sweep_path,'grouped',change)
    if fault!='missing_hold':
        with pytest.raises(ValueError):load_rtl_sweep(job.sweep_path)
    else:
        row=load_rtl_sweep(job.sweep_path).rows[2]
        assert row.frontier=='Not comparable' and 'Missing timing' in row.reason
        destination=export_rtl_sweep(job.sweep_path,tmp_path/'export')
        assert 'Not tested' in (destination/'report.html').read_text()
