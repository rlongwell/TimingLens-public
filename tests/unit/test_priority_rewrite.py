from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from threading import Event

import pytest

from timinglens.experiments.equivalence import SCRIPT,MARKER,discover_yosys,command_prefix,verify_proof,validate_attached_proof
from timinglens.experiments.priority_rewrite import PLAN_ID,SOURCE_SHA,CANDIDATE_SHA,candidate
from timinglens.experiments.recommendation import bundled_inputs,prepare_experiment,revalidate,build_script
from timinglens.experiments.recommendation_runner import RecommendationRequest,run_recommendation,read_recommendation_job
from timinglens.experiments.runner import JobFailure
from timinglens.experiments.io import load_run
from timinglens.experiments.compare import compare
from timinglens.experiments.process import execute,ProcessFailure


@pytest.fixture
def rewrite(recommendation_factory):
    result=recommendation_factory('priority')[0]
    plan=next(p for g in result.investigations for p in g.plans if p.id==PLAN_ID)
    return prepare_experiment(result,plan)


@pytest.fixture
def formal_tools(recommendation_tools,monkeypatch):
    """Explicit synthetic proof shape for orchestration tests; real proofs are tested below."""
    from timinglens.experiments import recommendation_runner as runner
    tool,calls,old,snapshot=recommendation_tools
    cells={f'e{i}':{'type':'$equiv','connections':{'A':[i+100],'B':[i+100],'Y':[i]}} for i in range(67)}
    proof={'modules':{'equiv':{'cells':cells,'netnames':{'result':{'bits':[0]},'u_select.req_q':{'bits':list(range(1,17))},'u_select.data_q':{'bits':list(range(17,33))}}}}}
    def fake(command,cwd,logfile,*args):
        if logfile.name in {'version.log','equivalence.log'}:
            calls.append((cwd.name,logfile.name,[str(c) for c in command]))
            logfile.write_text('Yosys 0.69 (synthetic fixture)' if logfile.name=='version.log' else 'Equivalence successfully proven!\n'+MARKER)
            if logfile.name=='equivalence.log':(cwd/'proof.json').write_text(json.dumps(proof))
            return {'seconds':.01,'returncode':0,'log':logfile.name}
        return old(command,cwd,logfile,*args)
    monkeypatch.setattr(runner,'execute',fake);monkeypatch.setattr(runner,'discover_yosys',lambda _:tool)
    return tool,calls,fake,proof


def test_source_pinned_balanced_candidate_and_same_recipe(rewrite):
    source=bundled_inputs('priority')[0];balanced=candidate(source)
    assert sha256(source).hexdigest()==SOURCE_SHA and sha256(balanced).hexdigest()==CANDIDATE_SHA
    assert b'req_q <= request;' in balanced and b'data_q <= data;' in balanced and b'result <= priority_value[1];' in balanced
    assert build_script('priority')==build_script('priority',PLAN_ID)
    assert revalidate(rewrite)==rewrite and rewrite.rtl_rewrite
    assert 'EQUIVALENCE GATE' in rewrite.preview() and '--- baseline/design.sv' in rewrite.preview()
    with pytest.raises(ValueError,match='pinned'):candidate(source+b' ')


def test_plan_is_limited_to_priority_and_measured_logic(recommendation_factory):
    from timinglens.analysis.engine import analyze
    for name in ('deep','fanout'):
        result=recommendation_factory(name)[0]
        assert not any(p.id==PLAN_ID for g in result.investigations for p in g.plans)
    result=recommendation_factory('priority')[0]
    changed=result.session.model_copy(update={'sources':[]})
    assert not any(p.id==PLAN_ID for g in analyze(changed).investigations for p in g.plans)


def test_runner_proves_before_tools_and_imports_same_recipe_comparison(tmp_path,rewrite,formal_tools):
    tool,calls,_,_=formal_tools
    result=run_recommendation(RecommendationRequest(rewrite,tmp_path/'job',verilator=str(tool)))
    names=[log for _,log,_ in calls]
    assert names.index('equivalence.log')<names.index('vivado-version.log')<names.index('vivado.log')
    assert sum(n=='simulation.log' for n in names)==2
    baseline,changed=[load_run(p) for p in result.register_pair]
    assert baseline.context.directives==changed.context.directives and baseline.context.sources!=changed.context.sources
    assert baseline.context.constraints==changed.context.constraints
    assert changed.change_diff.startswith('--- baseline/design.sv')
    comparison=compare(baseline,changed)
    assert next(g.status for g in comparison.gates if g.name=='RTL equivalence')=='passed'
    assert read_recommendation_job(result.directory)==result
    validate_attached_proof(changed)
    from timinglens.experiments.sweep import explain
    assert any('identical recorded implementation directives' in line for line in explain(comparison))
    from timinglens.experiments.models import Run
    with pytest.raises(ValueError,match='explicit passed check'):
        Run.model_validate({**changed.model_dump(),'checks':[c for c in changed.checks if c.name!='equivalence']})


@pytest.mark.parametrize('fault',['tool_failure','marker','incomplete','wrong_version','tampered_source','cancel','timeout'])
def test_equivalence_failure_stops_all_vivado_work(tmp_path,monkeypatch,rewrite,formal_tools,fault):
    from timinglens.experiments import recommendation_runner as runner
    tool,calls,old,_=formal_tools
    def fake(command,cwd,logfile,*args):
        if logfile.name=='equivalence.log' and fault in {'tool_failure','cancel','timeout'}:
            if fault=='cancel':raise runner.Cancelled('cancelled equivalence fixture')
            raise ProcessFailure('proof failed' if fault=='tool_failure' else 'proof timed out')
        output=old(command,cwd,logfile,*args)
        if logfile.name=='version.log' and fault=='wrong_version':logfile.write_text('Yosys 0.68')
        if logfile.name=='equivalence.log':
            if fault=='marker':logfile.write_text('incomplete')
            elif fault=='incomplete':
                p=cwd/'proof.json';doc=json.loads(p.read_bytes());doc['modules']['equiv']['cells']['e0']['connections']['B']=[999];p.write_text(json.dumps(doc))
            elif fault=='tampered_source':
                p=cwd/'candidate.sv';p.chmod(0o644);p.write_text('changed')
        return output
    monkeypatch.setattr(runner,'execute',fake)
    with pytest.raises(JobFailure):run_recommendation(RecommendationRequest(rewrite,tmp_path/'job',verilator=str(tool)))
    assert not any(name.startswith('vivado') for _,name,_ in calls)
    assert not (tmp_path/'job/result.json').exists()


@pytest.mark.parametrize('fault',['missing_proof','changed_pair','unproven_output','missing_state_point'])
def test_portable_pass_requires_proof_and_covered_source(tmp_path,rewrite,formal_tools,fault):
    tool,_,_,_=formal_tools;result=run_recommendation(RecommendationRequest(rewrite,tmp_path/'job',verilator=str(tool)))
    run=load_run(result.register_pair[1]);attachments=dict(run.attachments)
    if fault=='missing_proof':del attachments['equivalence/proof.json']
    elif fault=='changed_pair':attachments['equivalence/candidate.sv']='changed'
    else:
        data=json.loads(attachments['equivalence/proof.json'])
        if fault=='unproven_output':data['modules']['equiv']['cells']['e0']['connections']['B']=[999]
        else:data['modules']['equiv']['netnames']['u_select.req_q']['bits']=[999]*16
        attachments['equivalence/proof.json']=json.dumps(data)
    with pytest.raises(ValueError):validate_attached_proof(run.model_copy(update={'attachments':attachments}))


@pytest.mark.parametrize('mutation',['none','priority','no_request','latency','inverted'])
def test_real_yosys_accepts_correct_candidate_and_rejects_behavior_changes(tmp_path,mutation):
    try:tool=discover_yosys()
    except ValueError:pytest.skip('Install the gui/formal extra for actual Yosys checks.')
    source=bundled_inputs('priority')[0];balanced=candidate(source).decode()
    if mutation=='priority':balanced=balanced.replace('priority_valid[2*i+1] ? priority_value[2*i+1] : priority_value[2*i]','priority_valid[2*i] ? priority_value[2*i] : priority_value[2*i+1]')
    elif mutation=='no_request':balanced=balanced.replace('req_q[i] & data_q[i]','req_q[i] | data_q[i]')
    elif mutation=='latency':balanced=balanced.replace('req_q[i];','request[i];').replace('req_q[i] & data_q[i]','request[i] & data[i]')
    elif mutation=='inverted':balanced=balanced.replace('result <= priority_value[1];','result <= ~priority_value[1];')
    (tmp_path/'baseline.sv').write_bytes(source);(tmp_path/'candidate.sv').write_text(balanced);(tmp_path/'equivalence.ys').write_text(SCRIPT)
    execute([*command_prefix(),tool,'-V'],tmp_path,tmp_path/'version.log',Event(),180)
    if mutation=='none':
        execute([*command_prefix(),tool,'-s','equivalence.ys'],tmp_path,tmp_path/'equivalence.log',Event(),180)
        assert verify_proof(tmp_path)['matched_points']==67
    else:
        with pytest.raises(ProcessFailure):execute([*command_prefix(),tool,'-s','equivalence.ys'],tmp_path,tmp_path/'equivalence.log',Event(),180)
        assert MARKER not in (tmp_path/'equivalence.log').read_text()
