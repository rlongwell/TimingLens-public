from hashlib import sha256
import json

import pytest

from timinglens.experiments.models import canonical
from timinglens.experiments.recipes import RECIPES, build_script, validate_recipes
from timinglens.experiments.sweep import explain, export_sweep, load_sweep, read_manifest, render_sweep


def test_recipes_follow_explicit_vivado_2024_2_mapping():
    from importlib.resources import files
    assert build_script('default')==files('timinglens.experiments').joinpath('counter_build.tcl').read_bytes()
    assert RECIPES['explore'].commands()==('opt_design -directive Explore','place_design -directive Explore','phys_opt_design -directive Explore','route_design -directive Explore')
    assert RECIPES['extra_timing'].commands()==('opt_design','place_design -directive ExtraTimingOpt','phys_opt_design -directive Explore','route_design -directive NoTimingRelaxation')
    for bad in ((),('explore',),('default','unknown'),('default','default'),('default','Explore; exit'),['default']):
        with pytest.raises(ValueError):validate_recipes(bad)
    with pytest.raises(ValueError):build_script('default; exec something')


def test_rank_prioritizes_regression_guard_over_wns_and_preserves_acceptance(tmp_path,sweep_factory):
    path=sweep_factory(tmp_path/'sweep',{'explore':{'wns':-.5,'tns':-.5,'endpoint_slack':.3},
                                      'extra_timing':{'wns':-.2,'tns':-.2,'endpoint_slack':-.1,'logic':1.3,'start':'c/Q'}})
    for population in ('register_paths','design'):
        review=load_sweep(path,population)
        assert [(r.strategy,r.rank) for r in review.rows]==[('explore',1),('default',2),('extra_timing',3)]
        bad=review.rows[-1]
        assert bad.strategy_comparison.outcome=='regressed'
        assert bad.overall_comparison.acceptance=='blocked'
        text='\n'.join(bad.explanations)
        assert 'b/D: 0.2' in text or 'b/D: 0.200' in text
        assert 'logic Δ 0.300 ns' in text and 'worst captured launch point changed' in text
        assert 'do not prove which optimization caused it' in text
        assert 'Source changed' not in text and 'Source changed' in '\n'.join(explain(bad.overall_comparison))


def test_summary_hold_and_failure_regressions_override_setup_gain(tmp_path,sweep_factory):
    path=sweep_factory(tmp_path/'sweep',{'explore':{'wns':-.1,'tns':-.1,'hold_wns':-.1,'hold_tns':-.1,'hold_fail':1},
                                      'extra_timing':{'wns':-.2,'tns':-.2,'fail':2}})
    review=load_sweep(path)
    assert [r.strategy for r in review.rows]==['default','extra_timing','explore']
    assert all(r.strategy_comparison.outcome=='regressed' for r in review.rows[1:])
    assert 'Mixed result:' in '\n'.join(review.rows[-1].explanations)
    assert 'Hold WNS' in '\n'.join(review.rows[-1].explanations)


def test_equal_metrics_tie_despite_runtime_and_area(tmp_path,sweep_factory):
    path=sweep_factory(tmp_path/'sweep',{'explore':{'seconds':800.},'extra_timing':{'seconds':.5}})
    assert [r.rank for r in load_sweep(path).rows]==[1,1,1]


def test_explanation_distinguishes_lost_margin_and_prioritizes_affected_check(tmp_path,sweep_factory):
    path=sweep_factory(tmp_path/'sweep',{'explore':{'wns':-.5,'tns':-.5,'endpoint_slack':.1,'hold_wns':.05,'hold_endpoint_slack':.05}})
    row=next(r for r in load_sweep(path).rows if r.strategy=='explore')
    text='\n'.join(row.explanations)
    assert 'that check still passes' in text and text.index('hold b/D')<text.index('setup b/D')


def test_explanation_reports_changed_implementation_population(tmp_path,sweep_factory):
    from timinglens.experiments.compare import compare
    path=sweep_factory(tmp_path/'sweep');reference=load_sweep(path,'design').reference
    timing={k:s.model_copy(update={'total_endpoints':8}) for k,s in reference.timing.items()}
    changed=reference.model_copy(update={'timing':timing,'session':reference.session.model_copy(update={'summary':timing})})
    text='\n'.join(explain(compare(reference,changed)))
    assert 'reported population: 4 → 8 pins' in text and 'changed implementation population' in text


@pytest.mark.parametrize('change,reason',[
    ({'omit_reports':['pulse']},'Missing pulse'),({'omit_checks':True},'validation checks'),
    ({'different_source':True},'source differs'),({'wrong_directives':True},'directives'),({'part':'different'},'Incompatible')])
def test_incomplete_or_incompatible_recipe_is_unranked(tmp_path,sweep_factory,change,reason):
    path=sweep_factory(tmp_path/'sweep',{'explore':change})
    row=next(r for r in load_sweep(path).rows if r.strategy=='explore')
    assert row.rank is None and reason in row.reason


def test_incomplete_default_cannot_lend_credibility(tmp_path,sweep_factory):
    path=sweep_factory(tmp_path/'sweep',{'default':{'omit_reports':['route']}})
    assert all(r.rank is None and r.reason.startswith('Default reference') for r in load_sweep(path).rows)


def test_partial_failed_cancelled_and_unstarted_rows_remain_visible(tmp_path,sweep_factory):
    path=sweep_factory(tmp_path/'sweep',{'explore':{'error':'failed <script>alert(1)</script>'}},
                       statuses={'explore':'failed','extra_timing':'not_run'},status='cancelled')
    review=load_sweep(path)
    assert review.manifest.status=='cancelled'
    assert len(review.rows)==3 and sum(r.rank is not None for r in review.rows)==1
    assert all(r.run is None and r.strategy_comparison is None for r in review.rows if r.rank is None)
    html=render_sweep([review]);assert '<script>' not in html and '&lt;script&gt;' in html
    target=export_sweep(path,tmp_path/'portable')
    assert load_sweep(target/'sweep.json').document()==review.document()
    with pytest.raises(FileExistsError):export_sweep(path,target)


def test_sweep_checks_run_and_manifest_digests_and_paths(tmp_path,sweep_factory):
    path=sweep_factory(tmp_path/'sweep');data=json.loads(path.read_bytes())
    data['sweep']['job_name']='changed';path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='integrity'):load_sweep(path)
    data['sweep']['strategies'][0]['records']['design']['path']='../outside.json'
    data['sha256']=sha256(canonical(data['sweep'])).hexdigest();path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='Unexpected run path'):load_sweep(path,'design')
    data['sweep']['strategies'][0]['records']['design']['path']='runs/candidate.design.run.json'
    data['sha256']=sha256(canonical(data['sweep'])).hexdigest();path.write_text(json.dumps(data))
    target=path.parent/'runs/candidate.design.run.json';target.write_bytes(target.read_bytes()+b' ')
    with pytest.raises(ValueError,match='digest mismatch'):load_sweep(path,'design')
    with pytest.raises(ValueError,match='digest mismatch'):export_sweep(path,tmp_path/'bad-export')
    assert not (tmp_path/'bad-export').exists()


def test_sweep_rejects_symlink_escape_nonregular_and_large_files(tmp_path,sweep_factory):
    import os
    path=sweep_factory(tmp_path/'sweep');target=path.parent/'runs/candidate.design.run.json'
    outside=tmp_path/'outside.json';target.rename(outside);target.symlink_to(outside)
    with pytest.raises(ValueError,match='outside'):load_sweep(path,'design')
    fifo=tmp_path/'fifo';os.mkfifo(fifo)
    with pytest.raises(ValueError,match='regular'):read_manifest(fifo)
    large=tmp_path/'large'
    with large.open('wb') as stream:stream.truncate(1_000_001)
    with pytest.raises(ValueError,match='size limit'):read_manifest(large)


def test_sweep_identity_and_completion_must_match_evidence(tmp_path,sweep_factory):
    path=sweep_factory(tmp_path/'sweep');data=json.loads(path.read_bytes())
    data['sweep']['example']='counter64';data['sha256']=sha256(canonical(data['sweep'])).hexdigest();path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='design identity'):load_sweep(path)
    data['sweep']['baseline']={};data['sha256']=sha256(canonical(data['sweep'])).hexdigest();path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='lacks the original baseline'):load_sweep(path)


def test_cli_sweep_preview_is_read_only(tmp_path,monkeypatch,capsys):
    from timinglens.cli import main
    monkeypatch.chdir(tmp_path)
    assert main(['experiment','--example','counter32','--sweep','--preview'])==0
    text=capsys.readouterr().out
    assert '4 routed builds' in text and 'phys_opt_design -directive Explore' in text
    assert 'NoTimingRelaxation' in text and not list(tmp_path.iterdir())
