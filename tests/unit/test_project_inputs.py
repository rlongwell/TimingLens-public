"""Evidence gates for project-aware recommendations, not timing-success claims."""
import json
from pathlib import Path

import pytest

from timinglens import analyze, read_session
from timinglens.service import inspect_files, load, export_result
from timinglens.project import context
from timinglens.timing.models import Arc, Cell, Clock, Net, Pin, Session, Source, TimingPath
from timinglens.vivado.text_import import from_reports

FIXTURE = Path(__file__).parents[1] / 'fixtures/zybo_dfx_path.json'
LINK = 'connect_bd_intf_net [get_bd_intf_pins tx/M_AXIS] [get_bd_intf_pins rx/S_AXIS]\n'
DOMAINS = ('connect_bd_net [get_bd_ports clk] [get_bd_pins tx/aclk] [get_bd_pins rx/aclk]\n'
           'connect_bd_net [get_bd_ports resetn] [get_bd_pins tx/aresetn] [get_bd_pins rx/aresetn]\n')


def intent(**fields):
    return Source(path='intent.json', text=json.dumps({'timinglens_intent':1, **fields}))


def stream_session(*, clock='clk', missing_delay=False):
    a, b = 'tx/M_AXIS_tvalid_reg/Q', 'rx/S_AXIS_tvalid_reg/D'
    cells = {n:Cell(name=n, primitive='FDRE', sequential=True) for n in ('tx/M_AXIS_tvalid_reg','rx/S_AXIS_tvalid_reg')}
    pins = {n:Pin(name=n, cell=n.rsplit('/',1)[0]) for n in (a,b)}
    net = Net(name='stream_valid', drivers=[a], sinks=[b])
    path = TimingPath(id='P1', analysis='setup', startpoint=a,endpoint=b, start_clock='clk',end_clock=clock,
                      slack_ns=-.5, datapath_ns=2.,logic_ns=0.,routing_ns=2., pins=[a,b],cells=list(cells),nets=[net.name],
                      arcs=[Arc(source=a,sink=b,kind='net',resource=net.name,delay_ns=None if missing_delay else 2.)])
    return Session(name='stream',stage='routed',paths=[path],cells=cells,pins=pins,nets={net.name:net},
                   sources=[Source(path='bd.tcl',text=LINK+DOMAINS)],clocks=[Clock(name='clk',period_ns=10.,sources=['clk'])])


def test_literal_tcl_context_handles_comments_but_never_executes(tmp_path):
    sentinel=tmp_path/'executed'
    s=Source(path='build.tcl',text=f'''# comment with unmatched {{
set tx [create_bd_cell -type ip -vlnv xilinx.com:ip:axis_data_fifo:2.0 tx]
set_property -dict [list CONFIG.FIFO_DEPTH {{1024}}] $tx
{LINK}source unsafe.tcl
exec touch {sentinel}
if {{1}} {{ create_bd_cell -type ip -vlnv vendor:ip:unknown:1.0 dynamic }}
connect_bd_intf_net [get_bd_intf_pins $dynamic/M_AXIS] [get_bd_intf_pins rx/S_AXIS]
''')
    result=context([s]); assert not sentinel.exists()
    assert [(f.kind,f.subject,f.line) for f in result.facts]==[('bd_ip','tx',2),('bd_parameter','tx',3),('bd_link','tx/M_AXIS',4)]
    assert len(result.warnings)==3


def test_bd_json_and_invalid_intent_are_bounded():
    bd=Source(path='design.bd',text=json.dumps({'design':{'components':{'tx':{'vlnv':'xilinx.com:ip:axis_data_fifo:2.0','parameters':{'FIFO_DEPTH':{'value':'1024'}}}},'interface_nets':{'stream':{'interface_ports':['tx/M_AXIS','rx/S_AXIS']}}}}))
    assert [f.kind for f in context([bd]).facts]==['bd_ip','bd_parameter','bd_link']
    bad=intent(asynchronous_clocks=[{'source':'a','destination':'b','reason':'independent'},{}])
    assert not context([bad]).facts and context([bad]).warnings
    malformed=Source(path='partial.bd',text=json.dumps({'design':{'components':{'a':{'vlnv':'vendor:ip:a:1'}},'nets':{'n':3}}}))
    assert not context([malformed]).facts and context([malformed]).warnings


def test_bd_register_slice_requires_link_path_and_complete_delays():
    s=stream_session()
    assert [p.id for p in analyze(s).project_plans]==['bd.register_slice']
    assert not analyze(s.model_copy(update={'sources':[]})).project_plans
    assert not analyze(s.model_copy(update={'sources':[Source(path='bd.tcl',text=LINK.replace('rx/','other/'))]})).project_plans
    assert not analyze(stream_session(missing_delay=True)).project_plans
    assert [p.id for p in analyze(stream_session(clock='other')).project_plans]==['bd.cdc_review']
    p=s.paths[0].model_copy(update={'slack_ns':.1})
    assert not analyze(s.model_copy(update={'paths':[p]})).project_plans


def test_fifo_uses_explicit_capacity_bound_and_connected_link():
    s=stream_session()
    def with_capacity(capacity,source='tx/M_AXIS'):
        return analyze(s.model_copy(update={'sources':s.sources+[intent(stream_links=[dict(source=source,sink='rx/S_AXIS',max_burst_beats=64,buffer_capacity_beats=capacity,reason='unthrottled acquisition burst')])]}))
    fifo=next(p for p in with_capacity(8).project_plans if p.id=='bd.fifo')
    assert '64 beats' in fifo.action and 'sustained input rate' in fifo.reasoning
    assert not any(p.id=='bd.fifo' for p in with_capacity(64).project_plans)
    assert not any(p.id=='bd.fifo' for p in with_capacity(8,'unrelated/M_AXIS').project_plans)


def test_slice_requires_declared_domains_and_rejects_conflicts():
    s=stream_session()
    for text in (LINK, LINK+DOMAINS.replace('rx/aresetn','other/aresetn'),
                 LINK+DOMAINS+'connect_bd_net [get_bd_ports other_clk] [get_bd_pins tx/aclk]\n'):
        r=analyze(s.model_copy(update={'sources':[Source(path='bd.tcl',text=text)]}))
        assert [p.id for p in r.project_plans]==['bd.domain_review']
        assert r.project_plans[0].unknowns
    no_source=s.model_copy(update={'clocks':[Clock(name='clk')]})
    assert analyze(no_source).project_plans[0].id=='bd.domain_review'


def test_slice_does_not_claim_to_split_internal_receiver_logic():
    s=stream_session();p=s.paths[0]
    # Same named interface, but the boundary branch itself is short.
    p=p.model_copy(update={'arcs':[a.model_copy(update={'delay_ns':.1}) for a in p.arcs],
                          'logic_ns':4.,'routing_ns':.1,'datapath_ns':4.1})
    plan=analyze(s.model_copy(update={'paths':[p]})).project_plans[0]
    assert plan.id=='bd.boundary_review'
    assert 'cannot split' in plan.action


def test_slack_is_never_a_reason_for_false_path():
    r=load(FIXTURE)
    assert not r.project_plans
    assert not any(c.startswith(('set_false_path','set_clock_groups','set_multicycle_path'))
                   for plans in r.fix_plans.values() for p in plans for c in p.commands)


def test_async_intent_checks_clock_model_and_templates_are_comments():
    i=intent(asynchronous_clocks=[dict(source='a',destination='b',reason='independent oscillators')])
    s=Session(name='async', sources=[i],clocks=[Clock(name='a'),Clock(name='b')])
    p=analyze(s).project_plans[0]
    assert any(c.startswith('# set_clock_groups') for c in p.commands)
    assert 'overrides that bound' in p.action
    assert not any(c.startswith(('set_false_path','set_clock_groups')) for c in p.commands)
    related=s.model_copy(update={'clocks':[Clock(name='a'),Clock(name='b',master='a',generated=True)]})
    p=analyze(related).project_plans[0]
    assert 'common root' in p.reasoning and not any('set_clock_groups' in c for c in p.commands)
    assert not any('set_clock_groups' in c for c in analyze(s.model_copy(update={'clocks':[]})).project_plans[0].commands)


def test_existing_exceptions_are_reviewed_even_if_paths_all_disappear():
    s=Session(name='empty',sources=[Source(path='timing.xdc',text='set_false_path -to [get_cells *]\nset_multicycle_path 4 -setup -from [get_clocks a] -to [get_clocks a]\n')])
    p=analyze(s).project_plans[0]
    assert p.id=='constraints.audit' and len(p.source_candidates)==2
    assert 'empty failure list cannot validate' in p.reasoning
    assert 'hold relationship' in p.action


def test_multicycle_requires_explicit_intent_and_same_clock_edge_evidence():
    r=load(FIXTURE);s=r.session;p=s.paths[0]
    declared=intent(multicycle_paths=[dict(source=p.startpoint,destination=p.endpoint,cycles=4,reason='destination enabled only on every fourth launch')])
    candidate=analyze(s.model_copy(update={'sources':s.sources+[declared]})).project_plans[0]
    assert any(c.startswith('# set_multicycle_path 4 -setup') for c in candidate.commands)
    assert any(c.startswith('# set_multicycle_path 3 -hold') for c in candidate.commands)
    no_edge=analyze(s.model_copy(update={'sources':s.sources+[declared],'reports':{}})).project_plans[0]
    assert not any('set_multicycle_path' in c for c in no_edge.commands)


def test_real_report_only_import_recovers_printed_dfixed_arcs_and_deduplicates():
    original=read_session(FIXTURE)
    report=original.reports['setup-paths.rpt']
    result=analyze(from_reports({'first.rpt':report,'duplicate.rpt':report}))
    assert len(result.session.paths)==1
    p=result.session.paths[0]
    assert result.coverage[p.id].complete
    assert len(p.arcs)==34
    assert sum(a.delay_ns for a in p.arcs if a.kind=='net')==pytest.approx(6.523,abs=.003)
    assert sum(a.delay_ns for a in p.arcs if a.kind=='cell')==pytest.approx(3.026,abs=.003)
    assert result.session.stage=='unknown' and not result.session.vivado
    assert any('Report-only import' in w for w in result.warnings)
    hidden=report.replace(p.endpoint,'<hidden>')
    assert not analyze(from_reports({'hidden.rpt':hidden})).coverage['P00001'].complete


def test_offline_inspect_full_native_context_exports_and_revision_gate(tmp_path):
    original=load(FIXTURE).session
    source=next(s for s in original.sources if s.path.endswith('axis_bytes.sv'))
    local=tmp_path/'axis_bytes.sv';local.write_text(source.text)
    # Give the fixture the absolute path the real capture uses.
    new_sources=[s.model_copy(update={'path':str(local)}) if s.path==source.path else s for s in original.sources]
    cells={k:c.model_copy(update={'source':c.source.model_copy(update={'file':str(local)})}) if c.source and c.source.file==source.path else c for k,c in original.cells.items()}
    baseline=original.model_copy(update={'sources':new_sources,'cells':cells})
    project=tmp_path/'design.tcl';project.write_text(LINK)
    r=inspect_files([project],base=baseline)
    plans=[p for ps in r.fix_plans.values() for p in ps]
    assert any(p.id=='rtl.compare_enable' for p in plans)
    export_result(r,tmp_path/'export')
    doc=json.loads((tmp_path/'export/diagnostics.json').read_text())
    assert doc['project_context']['facts'][0]['kind']=='bd_link'
    assert 'project_plans' in doc and doc['fix_plans']
    local.write_text(source.text+'\n// changed revision\n')
    changed=inspect_files([local],base=baseline)
    assert any('differs from the captured source hash' in w for w in changed.warnings)
    assert not any(p.id=='rtl.compare_enable' for ps in changed.fix_plans.values() for p in ps)


def test_input_errors_and_conflicting_designs(tmp_path):
    file=tmp_path/'only.sv';file.write_text('module m; endmodule')
    with pytest.raises(ValueError,match='No supported Vivado'):inspect_files([file])
    with pytest.raises(ValueError,match='different designs'):
        from_reports({'a':'| Design : a\n','b':'| Design : b\n'})
    with pytest.raises(ValueError,match='authoritative'):
        inspect_files([FIXTURE],base=read_session(FIXTURE))
    report=tmp_path/'wrong.rpt';report.write_text('| Design : another_design\n')
    with pytest.raises(ValueError,match='metadata disagrees'):
        inspect_files([report],base=read_session(FIXTURE).model_copy(update={'top':'expected_design'}))


def test_specific_strategies_and_compare_enable_match_actual_guard():
    r=load(FIXTURE)
    plans={p.id:p for ps in r.fix_plans.values() for p in ps}
    assert plans['vivado.extra_timing'].commands[:4]==('opt_design','place_design -directive ExtraTimingOpt','phys_opt_design -directive Explore','route_design -directive NoTimingRelaxation')
    assert plans['vivado.net_delay'].commands[1]=='place_design -directive ExtraNetDelay_high'
    assert plans['vivado.remap'].commands[0]=='opt_design -directive ExploreWithRemap'
    assert any('pr_verify' in c for c in plans['vivado.extra_timing'].checks)
    rtl=plans['rtl.compare_enable']
    assert '64 bits' in rtl.title
    assert [(x.first,x.last) for x in rtl.source_candidates]==[(46,47)]
    assert all(x.first!=23 for x in rtl.source_candidates)
    incompatible=analyze(r.session.model_copy(update={'vivado':'2020.1'}))
    assert not any(p.kind=='vivado_experiment' for ps in incompatible.fix_plans.values() for p in ps)
    incomplete=analyze(read_session(FIXTURE))
    assert all(p.id=='evidence.first' for ps in incomplete.fix_plans.values() for p in ps)
