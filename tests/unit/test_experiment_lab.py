from hashlib import sha256
import json
from pathlib import Path

import pytest

from timinglens.experiments import compare, load_run, write_run, export_comparison
from timinglens.experiments.capture import from_session, report_metrics
from timinglens.experiments.io import render_report
from timinglens.experiments.models import Artifact, BuildContext, Check, Run, canonical
from timinglens.timing.models import Clock, Session, Source, Summary, TimingPath


def run(label='run',wns=-1.,tns=-10.,fail=10,**updates):
    session=Session(name=label,part='xc7z020clg400-1',vivado='2024.2',stage='routed',
        summary={'setup':Summary(worst_slack_ns=wns,total_negative_slack_ns=tns,failing_endpoints=fail,total_endpoints=20),
                 'hold':Summary(worst_slack_ns=.1,total_negative_slack_ns=0.,failing_endpoints=0,total_endpoints=20)},
        clocks=[Clock(name='clk',period_ns=2.,waveform_ns=[0.,1.],generated=False)])
    return from_session(session.model_copy(update=updates))


def test_failing_population_regression_overrides_better_wns_and_tns():
    result=compare(run(wns=-3.,tns=-245.,fail=18),run(wns=-2.,tns=-217.,fail=20))
    assert result.outcome=='regressed' and result.acceptance=='blocked'
    assert '18 → 20' in result.headline
    assert next(m for m in result.metrics if m.key=='setup.worst_slack_ns').delta==1.


def test_missing_metrics_are_not_zero_or_a_pass():
    result=compare(run(),run(wns=.1,tns=0.,fail=0))
    assert result.outcome=='improved' and result.acceptance=='incomplete'
    assert all(m.status=='not_tested' for m in result.metrics if m.key.startswith('drc.'))
    assert next(g for g in result.gates if g.name=='DFX compatibility').status=='not_tested'


@pytest.mark.parametrize('change',[{'part':'different'}, {'stage':'placed'}, {'clocks':[Clock(name='clk',period_ns=3.,waveform_ns=[0.,1.5],generated=False)]}])
def test_known_incompatible_context_is_inconclusive(change):
    result=compare(run(),run(wns=.1,tns=0.,fail=0,**change))
    assert result.outcome=='inconclusive' and result.acceptance=='blocked'


def test_endpoint_correspondence_does_not_use_path_id_and_collapses_worst():
    def p(id,endpoint,slack,clock='clk'):
        return TimingPath(id=id,analysis='setup',startpoint='launch/Q',endpoint=endpoint,start_clock=clock,end_clock=clock,slack_ns=slack)
    a=run(paths=[p('same-id','a/D',.2),p('other','a/D',.1),p('old','old/D',-.3)])
    b=run(paths=[p('same-id','renamed/D',-.2),p('new-id','a/D',-.1),p('newclock','old/D',.1,'different')])
    result=compare(a,b)
    matched=next(e for e in result.endpoints if e.endpoint=='a/D')
    assert matched.before_id=='other' and matched.after_id=='new-id' and matched.status=='newly_failing'
    assert result.outcome=='regressed'
    assert len(result.endpoints)==4
    assert {e.status for e in result.endpoints if e.endpoint=='old/D'}=={'baseline_only','candidate_only'}
    assert next(e for e in result.endpoints if e.endpoint=='renamed/D').status=='candidate_only'


def test_missing_clock_identity_is_not_a_match():
    path=TimingPath(id='P1',analysis='setup',endpoint='e',slack_ns=-1.)
    result=compare(run(paths=[path]),run(paths=[path]))
    assert len(result.endpoints)==2 and all(e.status=='ambiguous' for e in result.endpoints)


def test_run_digest_tampering_and_portable_roundtrip(tmp_path):
    source=Source(path='/never/read/this/source.sv',text='module m; endmodule',sha256=sha256(b'module m; endmodule').hexdigest())
    record=run(sources=[source],origin='/never/read/checkpoint.dcp')
    path=tmp_path/'a.run.json';write_run(path,record)
    assert load_run(path)==record
    with pytest.raises(FileExistsError):write_run(path,record)
    data=json.loads(path.read_text());data['run']['label']='modified';path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='integrity'):load_run(path)
    data['sha256']=sha256(canonical(data['run'])).hexdigest();data['run']['timing']['setup']['worst_slack_ns']=9.
    data['sha256']=sha256(canonical(data['run'])).hexdigest();path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='must agree'):load_run(path)


def test_native_session_does_not_follow_source_or_origin_paths(tmp_path,monkeypatch):
    source=Source(path='/missing/source.sv',sha256='a'*64)
    native=run(sources=[source],origin='/missing/checkpoint.dcp').session
    path=tmp_path/'native.json';path.write_text(native.model_dump_json())
    record=load_run(path)
    assert record.session.sources[0].text is None and record.context.mode=='unknown'


def test_source_digest_mismatch_and_lossy_capture():
    with pytest.raises(ValueError,match='Source bytes disagree'):
        run(sources=[Source(path='x.sv',text='changed',sha256='a'*64)])
    lossy=run(sources=[Source(path='x.sv',text='\ufffd',sha256='a'*64)])
    # Even deleting the diagnostic note cannot turn byte verification into a pass.
    lossy=lossy.model_copy(update={'notes':[]})
    assert next(g for g in compare(lossy,lossy).gates if g.name=='Embedded source byte verification').status=='not_tested'


def test_nonregular_and_oversize_imports(tmp_path):
    import os
    fifo=tmp_path/'fifo';os.mkfifo(fifo)
    with pytest.raises(ValueError,match='regular'):load_run(fifo)
    large=tmp_path/'large';
    with large.open('wb') as stream:stream.truncate(64_000_001)
    with pytest.raises(ValueError,match='64 MB'):load_run(large)


def test_report_parsers_missing_malformed_conflicting():
    assert report_metrics({'unknown':'No design data'})[0]=={}
    bad='Design Timing Summary\nWNS(ns) TNS(ns) WPWS(ns) TPWS Total Endpoints\n------------\n0 0 0 0 0 0 0 0 0 BAD 0 1\n'
    assert report_metrics({'broken':bad})[0]=={}
    rpt='Utilization\n| Slice LUTs | 50 |\n| Register as Flip Flop | 32 |\n| Block RAM Tile | 0.5 |\n| DSPs | 0 |'
    values,_,_=report_metrics({'util':rpt})
    assert values=={'area.lut_sites':50.,'area.ff':32.,'area.bram_tiles':.5,'area.dsp':0.}
    with pytest.raises(ValueError,match='Conflicting'):report_metrics({'a':rpt,'b':rpt.replace('| 50 |','| 60 |')})
    assert report_metrics({'drc':'Report DRC\nChecks found: 2\n| X | Warning | description | 1 |'})[0]=={}


def test_html_escapes_evidence_and_export_refuses_existing_directory(tmp_path):
    a=run(label='<script>alert(1)</script>');b=run(label='candidate')
    result=compare(a,b)
    assert '<script>' not in render_report(result)
    assert '&lt;script&gt;' in render_report(result)
    output=tmp_path/'comparison';export_comparison(result,output)
    assert {p.name for p in output.iterdir()}=={'baseline.run.json','candidate.run.json','comparison.json','report.html'}
    restored=compare(load_run(output/'baseline.run.json'),load_run(output/'candidate.run.json'))
    assert restored.document()==result.document()
    with pytest.raises(FileExistsError):export_comparison(result,output)


def test_area_tradeoffs_do_not_hide_missing_checks():
    before=run(wns=.1,tns=0.,fail=0).model_copy(update={'metrics':{'area.lut_cells':97.,'area.lut_sites':50.}})
    after=before.model_copy(update={'metrics':{'area.lut_cells':73.,'area.lut_sites':42.}})
    result=compare(before,after)
    assert result.outcome=='unchanged' and result.acceptance=='incomplete'
    assert next(m for m in result.metrics if m.key=='area.lut_cells').delta==-24.
    assert next(m for m in result.metrics if m.key=='area.lut_sites').delta==-8.


def test_only_complete_positive_evidence_reaches_review_ready():
    record=run(wns=.1,tns=0.,fail=0,sources=[Source(path='x.sv',text='source',sha256=sha256(b'source').hexdigest())],
               paths=[TimingPath(id='p',analysis='setup',corner='Slow',path_type='Setup')])
    record=record.model_copy(update={
        'context':BuildContext(design_key='x',mode='integrated',dfx=False,constraints={'x.xdc':'a'*64},sources={'x.sv':sha256(b'source').hexdigest()},compile_context={'defines':'none'},directives={'place':'Default'}),
        'metrics':{'pulse.wns':.5,'pulse.failing':0.,'route.unrouted':0.,'route.errors':0.,'drc.errors':0.,'drc.critical':0.},
        'checks':[Check(name='functional',status='passed',scope='finite simulation',evidence='test log'),Check(name='source_checkpoint',status='passed',scope='specific checkpoint',evidence='build record')]})
    assert compare(record,record).acceptance=='review_ready'
    incomplete=record.model_copy(update={'checks':[]})
    assert compare(record,incomplete).acceptance=='incomplete'
    failed=record.model_copy(update={'checks':[Check(name='functional',status='failed',scope='finite simulation',evidence='mismatch at cycle 3')]})
    assert compare(record,failed).acceptance=='blocked'


def test_changed_corner_and_duplicate_clock_identity_are_rejected():
    a=run(paths=[TimingPath(id='p',analysis='setup',corner='Slow',path_type='Setup')])
    b=run(paths=[TimingPath(id='p',analysis='setup',corner='Fast',path_type='Setup')])
    assert compare(a,b).outcome=='inconclusive'
    with pytest.raises(ValueError,match='Clock names must be unique'):
        run(clocks=[Clock(name='clk'),Clock(name='clk')])


def test_vivado_io_and_register_spelling_of_the_same_process_corner():
    def at(kind):
        return run(paths=[TimingPath(id="p",analysis="setup",corner="Slow",path_type=kind)])
    result = compare(at("Max at Slow Process Corner"), at("Setup (Max at Slow Process Corner)"))
    assert next(row for row in result.context if row.name=="Captured timing corners").status=="matched"
    distinct = compare(at("Max at Slow Process Corner"), at("Recovery (Max at Slow Process Corner)"))
    assert next(row for row in distinct.context if row.name=="Captured timing corners").status=="mismatch"


def test_register_population_is_tied_to_embedded_measurements(tmp_path):
    text='setup\t-1.0\t-10.0\t10\t20\nhold\t0.1\t0\t0\t20\n'
    artifact=Artifact(name='registers.tsv',kind='register_timing',sha256=sha256(text.encode()).hexdigest())
    data={**run().model_dump(),'population':'register_paths','artifacts':[artifact],'attachments':{'registers.tsv':text}}
    record=Run.model_validate(data);write_run(tmp_path/'run.json',record)
    assert load_run(tmp_path/'run.json')==record
    with pytest.raises(ValueError,match='embedded register_timing'):
        Run.model_validate({**data,'attachments':{}})
    with pytest.raises(ValueError,match='artifact digest'):
        Run.model_validate({**data,'attachments':{'registers.tsv':text+'changed'}})
    with pytest.raises(ValueError,match='agree with its embedded TSV'):
        Run.model_validate({**data,'timing':{'setup':Summary(worst_slack_ns=1.)}})


def test_run_measurements_cannot_contradict_embedded_reports(tmp_path):
    record=run(reports={'util':'Utilization\n| Slice LUTs | 50 |'})
    tampered=record.model_copy(update={'metrics':{'area.lut_sites':10.}})
    write_run(tmp_path/'run.json',tampered)
    with pytest.raises(ValueError,match='disagree with their embedded native reports'):
        load_run(tmp_path/'run.json')


def test_cli_comparison(tmp_path,capsys):
    from timinglens.cli import main
    a=tmp_path/'a.json';b=tmp_path/'b.json';write_run(a,run());write_run(b,run(wns=.1,tns=0.,fail=0))
    assert main(['compare','--baseline',str(a),'--candidate',str(b),'--output',str(tmp_path/'out')])==0
    assert 'IMPROVED' in capsys.readouterr().out
    assert main(['compare','--baseline',str(a),'--candidate',str(b),'--output',str(tmp_path/'out')])==1


def test_exported_diff_preserves_evidence_and_escapes_token_contents():
    from html.parser import HTMLParser
    from timinglens.export.syntax import code_block

    class Text(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []

        def handle_data(self, data):
            self.parts.append(data)

    diff = '--- old.sv\r\n+++ new.sv\r\n-/* comment\n-context */\n+assign ready = (n >= 4); // <script> & 😀'
    rendered = code_block(diff, 'diff')
    original = Text()
    original.feed(rendered)
    assert ''.join(original.parts) == diff
    assert '<script>' not in rendered and '&lt;script&gt;' in rendered
    assert all('t-' + role in rendered for role in ('keyword', 'operator', 'comment', 'diff_remove_bg', 'diff_add_bg'))


def test_resource_move_blocked_by_domain_specific_drc_review_is_visible_in_lab():
    candidate = run().model_copy(update={"checks":[Check(name="drc_warning_review", status="failed",
        scope="Native warning families", evidence="Additional DRC warnings require review: PDRC-136")]})
    comparison = compare(run(), candidate)
    gate = next(g for g in comparison.gates if g.name=="Native DRC warning review")
    assert gate.status=="failed" and "PDRC-136" in gate.detail and comparison.acceptance=="blocked"
