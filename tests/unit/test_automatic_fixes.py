from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from timinglens.analysis.bd_multiplier import RULE, VLNV, configurations
from timinglens.analysis.engine import analyze
from timinglens.experiments.auto_fix import choices, closure
from timinglens.experiments.auto_ip import check_edit
from timinglens.experiments.auto_project import Project
from timinglens.timing.models import Arc, Cell, Clock, Net, Pin, Session, Source, Summary, TimingPath


def bd_source(**config):
    values = dict(PortAType="Unsigned", PortBType="Unsigned", PortAWidth="12", PortBWidth="10",
                  PipeStages="2", Multiplier_Construction="Use_LUTs")
    values.update(config)
    item = dict(vlnv=VLNV, xci_name="filter_coefficient_3",
                parameters={key: {"value": val} for key, val in values.items()})
    doc = {"design": {"design_info": {"name": "filter"}, "components": {"coef": item}, "nets": {}}}
    text = json.dumps(doc)
    return Source(path="filters/filter.bd", text=text, sha256=sha256(text.encode()).hexdigest())


def ip_capture():
    cells = [Cell(name="u", primitive="filter_coefficient_3__9", original_ref="filter_coefficient_3", hierarchical=True)]
    for name, prim in (("a", "FDRE"), ("b", "LUT3"), ("c", "CARRY4"), ("d", "FDRE")):
        cells.append(Cell(name="u/" + name, parent="u", primitive=prim, sequential=prim == "FDRE"))
    pins = [Pin(name="u/"+n, cell="u/"+n[0]) for n in ("a/Q", "b/I", "b/O", "c/I", "c/O", "d/D")]
    arcs = [Arc(source=pins[i].name, sink=pins[i+1].name, kind=k, resource=n)
            for i, (k,n) in enumerate((("net","n1"),("cell","u/b"),("net","n2"),("cell","u/c"),("net","n3")))]
    path = TimingPath(id="P1", analysis="setup", pins=[p.name for p in pins], arcs=arcs,
        cells=[c.name for c in cells[1:]], startpoint=pins[0].name, endpoint=pins[-1].name,
        start_clock="sys", end_clock="sys", requirement_ns=8., slack_ns=-1., levels=2, logic_ns=6., routing_ns=3., datapath_ns=9.)
    return Session(name="filter", part="xc7z020clg400-1", vivado="2024.2", stage="routed", paths=[path],
        nets={s:Net(name=s) for s in ("n1","n2","n3")}, cells={c.name:c for c in cells}, pins={p.name:p for p in pins}, sources=[bd_source()], clocks=[Clock(name="sys", period_ns=8.)])


def test_native_hierarchy_handles_hidden_vendor_delays():
    result = analyze(ip_capture())
    plan, = choices(result)
    assert plan.id == RULE and plan.scope == "filter/coef"
    assert "6.000 ns total logic delay" in plan.evidence[0]
    assert not result.coverage["P1"].complete


@pytest.mark.parametrize("case", ["other_instance", "missing_link", "unknown_logic", "wrong_vlnv", "wrong_bytes",
                                  "no_match", "passing", "hold", "dfx", "different_clock", "signed", "ce", "duplicate"])
def test_automatic_ip_edits_require_specific_evidence(case):
    s = ip_capture()
    path = s.paths[0]
    if case == "other_instance":
        s.cells["another"] = s.cells["u"].model_copy(update={"name":"another"})
        s.cells["u/d"] = s.cells["u/d"].model_copy(update={"parent":"another"})
    elif case == "missing_link":
        path.arcs.pop()
    elif case == "unknown_logic":
        s.paths[0] = path.model_copy(update={"logic_ns":None})
    elif case == "no_match":
        s.cells.pop("u")
    elif case == "wrong_bytes":
        s.sources[0] = s.sources[0].model_copy(update={"sha256":"0"*64})
    elif case == "wrong_vlnv":
        txt = s.sources[0].text.replace(VLNV, "user:ip:similar_multiplier:1.0")
        s.sources[0] = s.sources[0].model_copy(update={"text":txt, "sha256":sha256(txt.encode()).hexdigest()})
    elif case == "dfx":
        s.cells["u"].properties["HD.RECONFIGURABLE"] = "1"
    elif case == "signed":
        s.sources[0] = bd_source(PortAType="Signed")
    elif case == "ce":
        s.sources[0] = bd_source(ClockEnable="true")
    elif case == "duplicate":
        s.sources.append(s.sources[0].model_copy(update={"path":"another.bd"}))
    else:
        update = {"passing":{"slack_ns":.01}, "hold":{"analysis":"hold"}, "different_clock":{"end_clock":"other"}}
        s.paths[0] = path.model_copy(update=update[case])
    assert list(choices(analyze(s))) == []


def test_only_construction_may_change_in_native_design():
    source = bd_source()
    ip, = configurations(source)
    revised = source.text.replace("Use_LUTs", "Use_Mults")
    check_edit(source.text, revised, ip)
    with pytest.raises(ValueError):
        check_edit(source.text, revised.replace('"nets": {}', '"nets": {"new": 1}'), ip)
    with pytest.raises(ValueError):
        check_edit(source.text, source.text, ip)


def tiny_project(tmp):
    xpr = tmp/"filter.xpr"
    source = tmp/"filter.srcs/unit.v"
    source.parent.mkdir()
    source.write_text("module unit(); endmodule")
    xpr.write_text('<Project><FileSets><FileSet Type="DesignSrcs"><File Path="$PSRCDIR/unit.v"/></FileSet></FileSets></Project>')
    return xpr, source


def test_checked_copy_publication_and_competing_run(tmp_path):
    xpr, original = tiny_project(tmp_path)
    layout = Project.read(xpr)
    copy = layout.clone(tmp_path/"job"/"candidate")
    source = original.relative_to(tmp_path)
    backup = tmp_path/"job"/"old"/source
    payload = b"module changed(); endmodule"
    (copy.parent/source).write_bytes(payload)
    assert original.read_bytes() != payload
    layout.publish(source,payload,backup)
    assert backup.read_text() == "module unit(); endmodule" and original.read_bytes() == payload
    with pytest.raises(ValueError, match="changed"):
        layout.publish(source,b"stale",tmp_path/"second-backup")
    assert original.read_bytes() == payload and not (tmp_path/"second-backup").exists()


def test_changed_dependency_prevents_publication(tmp_path):
    xpr, source = tiny_project(tmp_path)
    header = source.with_suffix(".vh")
    header.write_text("initial")
    project = Project.read(xpr)
    header.write_text("edited")
    with pytest.raises(ValueError, match="changed"):
        project.publish(source.relative_to(tmp_path),b"new",tmp_path/"original")
    assert source.read_text() == "module unit(); endmodule"


def test_external_and_symlinked_sources_are_rejected(tmp_path):
    xpr, source = tiny_project(tmp_path)
    real = tmp_path/"another.v"
    source.rename(real)
    source.symlink_to(real)
    with pytest.raises(ValueError):
        Project.read(xpr)


@pytest.mark.parametrize(("after","gate","expected"),[(.02,"passed",[]),(-.01,"failed",["Hold timing","Hold WNS"]),
                                                      (.02,"not_tested",["Hold timing"])])
def test_closure_gate_distinguishes_margin_and_violation(after,gate,expected):
    run = SimpleNamespace(timing={"setup":Summary(worst_slack_ns=-.1)})
    comparison = SimpleNamespace(before=run,endpoints=[],gates=[SimpleNamespace(name="Hold timing",status=gate)],
        metrics=[SimpleNamespace(key="hold.worst_slack_ns",label="Hold WNS",status="regressed",before=.08,after=after)])
    assert closure(comparison) == expected


def test_atomic_pair_publication_preserves_sibling_ip_and_backs_up_both_inputs(tmp_path):
    xpr = tmp_path/"filter.xpr"
    bd = Path("filter.srcs/bd/filter/filter.bd")
    xci = bd.parent/"ip/coef/coef.xci"
    other = bd.parent/"ip/coef/sibling.txt"
    (tmp_path/xci.parent).mkdir(parents=True)
    for name in (bd,xci,other):
        (tmp_path/name).write_text("original")
    xpr.write_text('<Project><FileSet Type="DesignSrcs"><File Path="$PSRCDIR/bd/filter/filter.bd"/></FileSet></Project>')
    layout = Project.read(xpr)
    backup = tmp_path/"evidence"/"original"
    layout.publish_block(bd,xci,{bd:b"block",xci:b"ip"},backup)
    assert [(tmp_path/f).read_bytes() for f in (bd,xci,other)] == [b"block",b"ip",b"original"]
    assert (backup/bd).read_bytes() == (backup/xci).read_bytes() == b"original"
    with pytest.raises(ValueError,match="changed"):
        layout.publish_block(bd,xci,{bd:b"later",xci:b"later"},tmp_path/"new-backup")


def test_xci_requires_matching_identity_and_only_the_expected_generated_values():
    from timinglens.experiments.auto_ip import check_xci
    ip, = configurations(bd_source())
    item = {"cell_name":ip.cell, "xci_name":ip.module,"component_reference":VLNV,"parameters":{
        "component_parameters":{"Multiplier_Construction":[{"value":"Use_LUTs"}]},
        "model_parameters":{"C_MULT_TYPE":[{"value":"0"}]}}}
    old = json.dumps({"ip_inst":item})
    new = old.replace("Use_LUTs","Use_Mults").replace('"0"','"1"')
    check_xci(old,new,ip)
    for bad in (new.replace(ip.cell,"other",1),new.replace('"1"','"0"'),new.replace('"parameters":','"extra":true,"parameters":')):
        with pytest.raises(ValueError):
            check_xci(old,bad,ip)


def test_classifies_only_full_drc_detail_on_the_reconfigured_native_dsp():
    from timinglens.experiments.auto_ip import pipeline_advisories

    def run(warnings):
        report = "\n".join(f"{rule}#{i} Warning\nInput pipelining\nDSP {cell} input is not pipelined."
                           for i,(rule,cell) in enumerate(warnings,1))
        return SimpleNamespace(session=SimpleNamespace(reports={"drc.rpt":report}),metrics={"drc.warnings":len(warnings)})
    base = run([])
    after = run([("DPIP-1","a/dsp"),("DPIP-1","a/dsp"),("DPOP-2","a/dsp")])
    assert pipeline_advisories(base,after,{"a/dsp"}) == {"DPIP-1":2,"DPOP-2":1}
    with pytest.raises(ValueError,match="outside"):
        pipeline_advisories(base,after,{"b/dsp"})
    with pytest.raises(ValueError,match="require review"):
        pipeline_advisories(base,run([("OTHER-1","a/dsp")]),{"a/dsp"})
    after.metrics["drc.warnings"] += 1
    with pytest.raises(ValueError,match="Incomplete"):
        pipeline_advisories(base,after,{"a/dsp"})


@pytest.mark.parametrize("setting", ['<Option Name="PR_FLOW" Val="true"/>', '<Step><Option Id="TclPre" Val="hook.tcl"/></Step>'])
def test_custom_run_hooks_and_dfx_never_reach_the_automatic_router(tmp_path,setting):
    xpr, _ = tiny_project(tmp_path)
    xpr.write_text(xpr.read_text().replace("</Project>",setting+"</Project>"))
    with pytest.raises(ValueError):
        Project.read(xpr)


def test_absolute_reference_is_not_a_portable_project_copy(tmp_path):
    xpr,source = tiny_project(tmp_path)
    xpr.write_text(xpr.read_text().replace("$PSRCDIR/unit.v",str(source)))
    with pytest.raises(ValueError,match="project-relative"):
        Project.read(xpr)


def test_reports_first_native_route_failure(tmp_path,monkeypatch):
    from timinglens.experiments import auto_fix
    from timinglens.experiments.process import ProcessFailure
    from threading import Event

    def failed(command,cwd,logfile,*args):
        logfile.write_text("Phase 2\nERROR: [Place 30-487] Not enough slices.\nERROR: [Common 17-69] Command failed.\n")
        raise ProcessFailure("exit 1")
    monkeypatch.setattr(auto_fix,"execute",failed)
    with pytest.raises(ProcessFailure,match="Place 30-487"):
        auto_fix.route(tmp_path/"d.xpr",tmp_path,"vivado",12,Event(),lambda _:None)


def test_shared_native_ip_parameter_has_one_recommendation_for_multiple_paths():
    s = ip_capture()
    s.paths.append(s.paths[0].model_copy(update={"id":"P2","slack_ns":-.2}))
    a = analyze(s)
    ranked = [r for r in a.investigations if any(p.id == RULE for p in r.plans)]
    assert len(ranked)==1 and set(ranked[0].path_ids)=={"P1","P2"}
    assert "2 captured failing paths" in ranked[0].plans[0].evidence[0]
