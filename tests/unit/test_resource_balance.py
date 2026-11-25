from collections import Counter
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from timinglens.analysis.inferred_memory import recognize
from timinglens.analysis.bd_multiplier import Multiplier
from timinglens.experiments.resource_balance import Pool, capacity, owners, proposals, verify_move, Move
from timinglens.timing.models import Source

SOURCE = (Path(__file__).resolve().parents[2]/"examples/resource-balance/queue_store.v").read_text()


def source(text):
    return Source(path="renamed.v",text=text,sha256=sha256(text.encode()).hexdigest())


def pools(**overrides):
    return {k: Pool(overrides.get(k,0),v) for k,v in {"lut":10000,"lutram":1000,"dsp":100,"bram":100}.items()}


@pytest.mark.parametrize("style",["block","distributed"])
def test_detects_mappable_read_first_memory_without_names(style):
    s=source(SOURCE.replace('"block"',f'"{style}"').replace('queue_store','frame_delay').replace('samples','pixels'))
    m=recognize(s)
    assert (m.module,m.style,m.width,m.depth)==('frame_delay',style,8,64)
    assert s.text[m.offset:m.offset+len(style)]==style


@pytest.mark.parametrize("old,new", [('posedge','negedge'),('<= din;', '<= din+1;'),('samples[addr];','samples[addr+1];'),
    ('dout)', 'dout, input rst)'),('[0:63]','[0:64]'),('if (we)','if (!we)'),('module queue_store','`ifdef TEST\nmodule queue_store')])
def test_unqualified_interfaces_and_behavior_stay_in_review(old,new):
    assert not recognize(source(SOURCE.replace(old,new)))


def test_uses_native_remaining_availability_and_zero_denominator():
    t="""| Site Type | Used | Fixed | Prohibited | Available | Util% |
| CLB LUTs* | 90 | 1 | 5 | 95 | 94.74 |
| LUT as Memory | 0 | 0 | 0 | 50 | 0 |
| Block RAM Tile | 2.5 | 0 | 0 | 10 | 25 |
| DSPs | 2 | 0 | 100 | 0 | N/A |"""
    p=capacity(t)
    assert p['lut']==Pool(90,95) and p['bram']==Pool(2.5,10)
    assert p['dsp'].exceeds(100) and not Pool(0,0).exceeds(85)
    with pytest.raises(ValueError,match="complete"):capacity(t.replace("DSPs","URAM"))
    with pytest.raises(ValueError,match="Conflicting"):capacity(t+"\n| DSPs | 3 | 0 | 100 | 0 | N/A |")


@pytest.mark.parametrize(("style","source_key","dst","primitive"),[('block','bram','lutram','ramb18'),
                                                                  ('distributed','lutram','bram','lutram')])
def test_headroom_and_confirmed_native_memory_swap(style,source_key,dst,primitive):
    m=recognize(source(SOURCE.replace('"block"',f'"{style}"')))
    used = pools(**{source_key:950 if source_key=="lutram" else 95})
    old={m.module:{"lane":Counter({primitive:2})}}
    moves,skips=proposals([m],old,used,85)
    assert len(moves)==1 and not skips and moves[0].destination==dst
    new={m.module:{"lane":Counter({"lutram" if dst=="lutram" else "ramb18":1})}}
    verify_move(moves[0],used,pools(**{dst:1}),old,new,85)
    with pytest.raises(ValueError,match="instance"):
        verify_move(moves[0],used,pools(),old,{m.module:{"other":Counter({"lutram":8})}},85)
    with pytest.raises(ValueError,match="budget|limit"):
        verify_move(moves[0],used,pools(lut=9000),old,new,85)


def test_multiplier_pressure_can_act_with_passing_timing_and_both_directions():
    ip=Multiplier("x.bd","0"*64,"block","mul","block_mul",8,8,3,12)
    for config,src,dst in (("Use_Mults","dsp","lut"),("Use_LUTs","lut","dsp")):
        target=replace(ip,construction=config)
        o={ip.module:{"u":Counter({src:3})}}
        p=pools(**{src:90 if src=="dsp" else 9500})
        moves,_=proposals([target],o,p,85)
        assert moves==[Move(target,src,dst)]
        assert not proposals([target],o,pools(),85)[0]
        p[dst]=Pool(85,100)
        moves,why=proposals([target],o,p,85)
        assert not moves and 'headroom' in why[0]


def test_full_fabric_blocks_distributed_ram_and_duplicate_counters_are_invalid():
    m=recognize(source(SOURCE))
    old={m.module:{"u":Counter(ramb18=1)}}
    moves,why=proposals([m],old,pools(bram=98,lut=8500),85)
    assert not moves and why
    moves,why=proposals([m],{},pools(bram=98),85)
    assert not moves and 'owned' in why[0]
    with pytest.raises(ValueError):owners("ram\tu\tdsp\t1\nram\tu\tdsp\t2")


def test_can_relieve_total_luts_by_moving_distributed_memory():
    m=recognize(source(SOURCE.replace('"block"','"distributed"')))
    o={m.module:{"m":Counter(lutram=192)}}
    p=pools(lut=9000,lutram=192)
    moves,_=proposals([m],o,p,85)
    assert moves[0].destination=="bram"


@pytest.mark.parametrize("hint", ["", '(* ram_style = "auto" *) '])
def test_unhinted_and_auto_memory_follow_measured_ownership(hint):
    original = SOURCE.replace('(* ram_style = "block" *) ', hint)
    ram = recognize(source(original))
    assert ram.mapped_source(original, "block") == SOURCE
    measured = {ram.module: {"a": Counter(lutram=8)}}
    moves, _ = proposals([ram], measured, pools(lutram=901), 85)
    assert moves == [Move(ram, "lutram", "bram")]
    assert ram.line == next(i for i,line in enumerate(original.splitlines(),1) if " samples " in line)


def test_unresolved_constraint_warning_blocks_implementation_acceptance(tmp_path):
    from timinglens.experiments.auto_fix import collect_route
    (tmp_path / "implementation.log").write_text(
        "CRITICAL WARNING: [Designutils 20-1307] Command is not supported in the xdc constraint file. [a.xdc:16]\n"
        "TIMINGLENS_AUTO_ROUTE_COMPLETE\n")
    with pytest.raises(ValueError, match="unresolved project constraint"):
        collect_route(None, tmp_path, None, 10)


def test_prefers_smaller_sufficient_edit_over_a_mass_migration():
    a = Multiplier("x.bd", "0"*64, "tile", "small", "small", 8, 8, 3, 1, "Use_Mults")
    b = replace(a, cell="large", module="large")
    inventory = {"small":{"s": Counter(dsp=7)}, "large":{"l": Counter(dsp=65)}}
    candidates, _ = proposals([b,a], inventory, pools(dsp=91), 85)
    assert [m.target for m in candidates] == [a,b]


def test_starred_synthesis_lut_count_is_reported_as_an_estimate():
    from timinglens.experiments.capture import report_metrics
    values, provenance, _ = report_metrics({"utilization.rpt":"Utilization\n| Slice LUTs* | 252 | 0 | 0 | 53200 |"})
    assert values["area.lut_sites"] == 252
    assert provenance["area.lut_sites"].endswith("Slice LUTs*")


def test_existing_destination_cells_cannot_prove_a_new_mapping():
    ip = Multiplier("x.bd", "0"*64, "block", "mul", "block_mul", 8, 8, 3, 3, "Use_Mults")
    row = Move(ip, "dsp", "lut")
    before = {ip.module: {"u": Counter(dsp=1, lut=2)}}
    after = {ip.module: {"u": Counter(lut=2)}}
    with pytest.raises(ValueError, match="mapping"):
        verify_move(row, pools(dsp=95), pools(), before, after, 85)


def test_candidate_budget_receipt_is_portable_even_on_rejection(tmp_path):
    import json
    from types import SimpleNamespace
    from timinglens.experiments.resource_balance import record_budget, measurements
    report = """| Site Type | Used | Available |
| Slice LUTs | 90 | 100 |
| LUT as Memory | 0 | 25 |
| Block RAM Tile | 8 | 20 |
| DSPs | 0 | 40 |"""
    candidate = SimpleNamespace(session=SimpleNamespace(reports={"utilization.rpt":report}))
    for limit,expected in ((85,"failed"),(95,"passed")):
        receipt, after, check = record_budget(tmp_path, {"limit_percent":limit}, None, capacity(report), {}, candidate)
        data = json.loads(receipt.read_text())
        assert data["after"] == after == measurements(capacity(report))
        assert check.status == expected and (data["resource_check"] == "passed") == (expected=="passed")
