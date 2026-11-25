"""Adversarial semantic and evidence gates; fixtures are rule-development data."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import subprocess

import pytest

from timinglens import analyze
from timinglens.analysis.rtl_fixes import factored
from timinglens.rtl.semantics import SemanticIndex
from timinglens.rtl.syntax import build_index
from timinglens.timing.models import Arc, Cell, Net, Pin, Session, Source, TimingPath


def rtl(*, kind='bit', width='32', comparison='remaining >= amount', update='remaining <= remaining - amount;',
        extra='', reset='if (rst) remaining <= 0; else ', parameters='', event='posedge clk'):
    return f'''module counter {parameters}(input bit clk, rst, accept, input {kind} [3:0] amount,
                     input {kind} [{width}-1:0] initial_value, input bit load,
                     output {kind} [{width}-1:0] remaining);
always_ff @({event}) begin
  {reset}if (load) remaining <= initial_value;
  else if (accept && ({comparison})) {update}
end
{extra}
endmodule
'''


def semantic(text, *, top='counter', module='counter', scope=None):
    index = build_index([Source(path='counter.sv', text=text)])
    return SemanticIndex(index, top).resolve(index.modules[module][0], scope, 'remaining')


def session(text=None, *, missing_delay=False, pin='CE'):
    text = text or rtl()
    cells = {f'c{i}': Cell(name=f'c{i}', primitive='CARRY4') for i in range(3)}
    cells['remaining_reg[0]'] = Cell(name='remaining_reg[0]', primitive='FDRE', sequential=True)
    pins = {'start': Pin(name='start', port=True, direction='IN')}
    nets = {}; arcs = []; ordered = ['start']; previous = 'start'
    for i in range(3):
        a, b = f'c{i}/CI', f'c{i}/CO[3]'
        pins[a] = Pin(name=a, cell=f'c{i}', ref_pin='CI')
        pins[b] = Pin(name=b, cell=f'c{i}', ref_pin='CO[3]')
        net = Net(name=f'n{i}', drivers=[previous], sinks=[a]); nets[net.name] = net
        arcs += [Arc(source=previous, sink=a, kind='net', resource=net.name, delay_ns=.4),
                 Arc(source=a, sink=b, kind='cell', resource=f'c{i}', delay_ns=.3)]
        ordered.extend([a, b]); previous = b
    end = f'remaining_reg[0]/{pin}'
    pins[end] = Pin(name=end, cell='remaining_reg[0]', ref_pin=pin)
    net = Net(name='enable', drivers=[previous], sinks=[end]); nets[net.name] = net
    arcs.append(Arc(source=previous, sink=end, kind='net', resource=net.name,
                    delay_ns=None if missing_delay else .8)); ordered.append(end)
    path = TimingPath(id='P1', analysis='setup', startpoint='start', endpoint=end, slack_ns=-.3,
                      requirement_ns=2., datapath_ns=2.9, logic_ns=.9, routing_ns=2., levels=3,
                      cells=list(cells), pins=ordered, nets=list(nets), arcs=arcs)
    return Session(name='semantic development fixture', top='counter', stage='routed', vivado='2024.2',
                   part='xc7z020clg400-1', cells=cells, pins=pins, nets=nets, paths=[path],
                   sources=[Source(path='counter.sv', text=text, sha256=sha256(text.encode()).hexdigest())])


def plans(s):
    return {p.id: p for row in analyze(s).investigations for p in row.plans}


def test_exact_two_state_preview_and_provenance():
    original = session()
    plan = plans(original)['rtl.compare_enable']
    change, = plan.changes
    assert change.original == 'remaining >= amount'
    assert change.status == 'review_diff' and change.unified_diff
    assert change.source_sha256 == original.sources[0].sha256
    assert original.sources[0].text.encode()[change.start_byte:change.end_byte].decode() == change.original
    assert {e.level for e in plan.evidence_links} == {'measured', 'inferred', 'elaborated', 'syntax'}
    assert 'source/checkpoint' in change.conditions[0]
    assert original.sources[0].text == rtl()  # analysis does not edit even in-memory inputs


@pytest.mark.parametrize('op', ['>', '>=', '<', '<=', '==', '!='])
def test_unsigned_factoring_at_every_small_operand_and_wide_boundary(op):
    reg, reason = semantic(rtl(comparison=f'amount {op} remaining'))
    assert not reason
    c = reg.enable_decisions[0].comparisons[0]
    assert factored(c)
    operations = {'>':lambda a,b:a>b, '>=':lambda a,b:a>=b, '<':lambda a,b:a<b,
                  '<=':lambda a,b:a<=b, '==':lambda a,b:a==b, '!=':lambda a,b:a!=b}
    for n in range(16):
        for w in {0,1,15,16,17,31,32,2**31,2**32-1,max(n-1,0),n,n+1}:
            low = operations[c.operator](w & 15,n)
            rewritten = bool(w >> 4) or low if c.operator in ('>', '>=', '!=') else not bool(w >> 4) and low
            assert rewritten == operations[op](n,w)


def test_four_state_preview_refuses_patch_even_with_known_width():
    plan = plans(session(rtl(kind='logic')))['rtl.compare_enable']
    assert plan.changes[0].status == 'design_hypothesis'
    assert not plan.changes[0].unified_diff
    assert 'X/Z' in plan.changes[0].conditions[0]


@pytest.mark.parametrize('text', [
    rtl(kind='bit signed'),
    rtl(comparison="remaining >= 32'(amount + 1)"),
    rtl(width='8'),
    rtl(comparison="remaining >= $signed(amount)"),
])
def test_signed_arithmetic_and_small_width_do_not_get_unsigned_diff(text):
    plan = plans(session(text))['rtl.compare_enable']
    assert not plan.changes


@pytest.mark.parametrize('text', [
    rtl(update='remaining <= remaining - amount; else remaining <= initial_value;'),
    rtl(reset='', update='remaining <= 0;'),
    rtl(event='posedge clk or posedge rst'),
    rtl(extra='always_ff @(posedge clk) remaining <= initial_value;'),
    rtl(update='remaining[3:0] <= amount;'),
])
def test_reset_data_mux_async_event_multiple_writer_and_partial_updates_are_not_enables(text):
    assert 'rtl.compare_enable' not in plans(session(text))


def test_parameterized_generate_hierarchy_elaborates_but_no_numeric_patch():
    text = rtl(width='W', parameters='#(parameter W=32)') + '''
module top;
  for (genvar i=0; i<2; i++) begin:g
    counter #(.W(64)) u();
  end
endmodule
'''
    reg, reason = semantic(text, top='top', scope='g[1]/u')
    assert not reason and reg.type.width == 64 and reg.parameterized
    plan = plans(session(rtl(width='W', parameters='#(parameter W=32)')))['rtl.compare_enable']
    assert plan.changes and not plan.changes[0].unified_diff
    assert any('parameters' in c for c in plan.changes[0].conditions)


def test_missing_context_duplicate_module_and_revision_mismatch():
    reg, reason = semantic('`include "not-supplied.svh"\n'+rtl(width='W', parameters='#(parameter W=32)'))
    assert reg is None and reason
    s = session()
    duplicate = s.model_copy(update={'sources':[*s.sources, Source(path='duplicate.sv', text=rtl())]})
    assert 'rtl.compare_enable' not in plans(duplicate)
    bad = s.model_copy(update={'sources':[s.sources[0].model_copy(update={'sha256':'0'*64})]})
    assert 'rtl.compare_enable' not in plans(bad)
    assert 'rtl.compare_enable' not in plans(session(missing_delay=True))
    assert 'rtl.compare_enable' not in plans(session(pin='R'))
    assert 'rtl.compare_enable' not in plans(session(pin='D'))


def test_no_fallback_to_other_instance_when_project_elaborates():
    text = rtl()+'\nmodule top; counter u(); endmodule\n'
    reg, reason = semantic(text, top='top', scope='wrong')
    assert reg is None and 'unique elaborated' in reason


def test_macro_source_span_cannot_become_an_edit():
    text = '`define GUARD remaining >= amount\n'+rtl(comparison='`GUARD')
    plan = plans(session(text)).get('rtl.compare_enable')
    assert plan is None or not plan.changes


def test_deduplication_preserves_all_symptoms_and_never_double_counts_paths():
    result = analyze(session())
    assert len(result.groups) > 1
    investigation, = result.investigations
    assert investigation.path_ids == ('P1',)
    assert set(investigation.rules) == {g.rule for g in result.groups}
    assert len([p for p in investigation.plans if p.id == 'rtl.compare_enable']) == 1
    assert result.failing_paths == 1


def test_actionable_investigation_precedes_unexplained_path_without_hiding_it():
    s=session();unexplained=s.paths[0].model_copy(update={'id':'P0','slack_ns':-10.,'cells':[],
        'pins':[],'nets':[],'arcs':[],'levels':0,'logic_ns':None,'routing_ns':None,'datapath_ns':None})
    r=analyze(s.model_copy(update={'paths':[unexplained,*s.paths]}))
    assert r.investigations[0].plans[0].id=='rtl.compare_enable'
    assert any(i.worst_slack_ns==-10. and 'P0' in i.path_ids for i in r.investigations)
    assert r.failing_paths==2


def test_semantic_budget_and_timeout_are_explicit(monkeypatch):
    from timinglens.rtl.bounded import BoundedSemanticIndex
    result = analyze(session())
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs['timeout'])
    monkeypatch.setattr(subprocess, 'run', timeout)
    index = BoundedSemanticIndex(result)
    module = result.source_index.modules['counter'][0]
    reg, reason = index.resolve(module, None, 'remaining')
    assert reg is None and '6-second' in reason
    large = build_index([Source(path='oversize.sv', text=' '*256_001+rtl())])
    assert not large.modules and 'budget exceeded' in large.warnings[0]


def test_exact_byte_offsets_with_unicode_comment():
    text = '// π and μ are multibyte\n'+rtl()
    change = plans(session(text))['rtl.compare_enable'].changes[0]
    assert text.encode()[change.start_byte:change.end_byte].decode() == change.original


def test_large_project_can_review_an_isolated_module_without_claiming_full_elaboration():
    s=session()
    s=s.model_copy(update={'sources':[*s.sources,Source(path='large_vendor_library.v',text=' '*2_100_000)]})
    result=analyze(s)
    plan=next(p for i in result.investigations for p in i.plans if p.id=='rtl.compare_enable')
    assert plan.changes and not plan.changes[0].unified_diff
    assert any('Project input budget exceeded' in u for u in plan.unknowns)


def test_expression_diff_applies_to_exact_original_in_scratch(tmp_path):
    text = rtl()
    change = plans(session(text))['rtl.compare_enable'].changes[0]
    (tmp_path/'counter.sv').write_text(text)
    patch = tmp_path/'change.patch'; patch.write_text(change.unified_diff)
    result = subprocess.run(['patch', '-p1', '--batch', '--fuzz=0', '-i', str(patch)], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    edited = (tmp_path/'counter.sv').read_text()
    assert change.proposed in edited and semantic(edited)[0] is not None
