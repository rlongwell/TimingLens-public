from dataclasses import replace
from hashlib import sha256
import json

import pytest

from timinglens.analysis.engine import analyze
from timinglens.experiments.pipeline_proof import prepare, verify
from timinglens.rtl.pipeline import pipeline
from timinglens.timing.models import Arc, Cell, Clock, Net, Pin, Session, Source, SourceLink, TimingPath

# A different interface, source layout, operand order and word size from the Zybo design.
RTL = """module filter_word(input logic [5:0] gain, left, right, input logic clock, output logic [9:0] sample);
    logic [11:0] wide;
    logic [7:0] mixed;
    logic [9:0] t0, t1, t2;
    assign mixed = wide[9:2] - {2'b0, right};
    assign wide = left * right;
    always_ff @(posedge clock) begin
        sample <= t2;
        t1 <= t0;
        t2 <= t1;
        t0 <= (mixed * gain);
    end
endmodule
"""

REPORT = """1. checking no_clock (0)
2. checking unconstrained_internal_endpoints (0)
3. checking no_input_delay (0)
4. checking multiple_clock (0)
5. checking generated_clocks (0)
6. checking partial_output_delay (0)
7. checking no_output_delay (1)
-------------------------------
 There are 0 ports with no output delay specified.
 There are 0 ports with no output delay but user has a false path constraint
 There is 1 port with no output delay but with a timing clock defined on it or propagating through it (LOW)

clock_out
"""


def capture():
    tag = SourceLink(file="rtl/filter_word.sv", first_line=6, last_line=6, provenance="vivado_cell_file_name_line_number")
    cells = {c.name: c for c in (
        Cell(name="launch", primitive="FDRE", sequential=True),
        Cell(name="u", primitive="filter_word", hierarchical=True),
        Cell(name="u/dsp", primitive="DSP48E1", source=tag, parent="u"),
        Cell(name="u/end", primitive="FDRE", sequential=True, parent="u"))}
    pins = [Pin(name=f"{cell}/{pin}", cell=cell, ref_pin=pin, direction=direction) for cell, pin, direction in (
        ("launch", "Q", "OUT"), ("u/dsp", "A", "IN"), ("u/dsp", "P", "OUT"), ("u/end", "D", "IN"))]
    names = [p.name for p in pins]
    nets = {n: Net(name=n, drivers=[names[i]], sinks=[names[i+1]], fanout=1)
            for n, i in (("a", 0), ("p", 2))}
    arcs = [Arc(source=names[i], sink=names[i+1], kind=kind, resource=n, delay_ns=delay)
            for i, (kind, n, delay) in enumerate((("net", "a", 1.), ("cell", "u/dsp", 6.), ("net", "p", 2.)))]
    path = TimingPath(id="P1", analysis="setup", startpoint=names[0], endpoint=names[-1], start_clock="clk", end_clock="clk",
                      slack_ns=-1., requirement_ns=8., datapath_ns=9., logic_ns=6., routing_ns=3.,
                      pins=names, cells=["launch", "u/dsp", "u/end"], nets=list(nets), arcs=arcs)
    return Session(name="test", part="xc7z020clg400-1", vivado="2024.2", stage="routed", cells=cells,
                   pins={p.name: p for p in pins}, nets=nets, paths=[path], sources=[Source(path=tag.file,
                   text=RTL, sha256=sha256(RTL.encode()).hexdigest())], timing_checks={"no_output_delay": 1},
                   reports={"check_timing.rpt": REPORT}, clocks=[Clock(name="clk", period_ns=8.),
                   Clock(name="out", period_ns=8., generated=True, master="clk", sources=["clock_out"])])


def plans(session):
    return [plan for issue in analyze(session).investigations for plan in issue.plans]


def test_native_path_drives_first_recommendation():
    result = analyze(capture())
    plan = result.investigations[0].plans[0]
    assert plan.id == "rtl.redistribute_arithmetic"
    candidate = prepare(result, plan)
    assert candidate.model.stages == 4 and "sample <= (mixed_s3 * gain_s3)" in candidate.revised
    assert "wide_s2[9:2] - {2'b0, right_s2}" in candidate.revised
    assert plan.changes[0].source_sha256 == sha256(RTL.encode()).hexdigest()
    assert any(p.id == "constraints.first" for row in result.investigations for p in row.plans)


@pytest.mark.parametrize("change", ["regular_output", "extra_check", "unknown_port", "summary_only", "missing_clock",
                                    "unrelated_domain", "io_endpoint", "other_raw_check", "clock_interaction"])
def test_coverage_keeps_real_or_unresolved_findings_blocking(change):
    session = capture()
    report = REPORT
    if change == "regular_output":
        report = report.replace("0 ports with no output delay specified", "1 port with no output delay specified")
    elif change == "extra_check":
        session.timing_checks["no_clock"] = 1
    elif change == "unknown_port":
        report = report.replace("clock_out", "data_out")
    elif change == "summary_only":
        report = "7. checking no_output_delay (1)"
    elif change == "missing_clock":
        session.clocks.pop()
    elif change == "unrelated_domain":
        session.paths[0] = session.paths[0].model_copy(update={"end_clock": "out"})
    elif change == "io_endpoint":
        p = session.paths[0].endpoint
        session.pins[p] = session.pins[p].model_copy(update={"port": True})
    elif change == "other_raw_check":
        report = report.replace("no_clock (0)", "no_clock (1)")
    else:
        session.clock_interactions.append(dict(source="clk", destination="clk", classification="no common clock", constraints="Timed"))
    session.reports["check_timing.rpt"] = report
    assert {p.id for p in plans(session)} == {"constraints.first"}


@pytest.mark.parametrize("change", ["sha", "tag", "owner", "tiny_dsp", "incomplete", "hold", "passing", "DFX", "ambiguous", "nohash", "preserved"])
def test_no_patch_on_unsubstantiated_path(change):
    s = capture()
    path = s.paths[0]
    dsp = s.cells["u/dsp"]
    if change in {"sha", "nohash"}:
        s.sources[0] = s.sources[0].model_copy(update={"sha256": None if change == "nohash" else "0"*64})
    elif change == "tag":
        s.cells[dsp.name] = dsp.model_copy(update={"source": dsp.source.model_copy(update={"first_line": 3, "last_line": 3})})
    elif change == "owner":
        s.cells[dsp.name] = dsp.model_copy(update={"parent": None})
    elif change in {"tiny_dsp", "incomplete"}:
        path.arcs[1] = path.arcs[1].model_copy(update={"delay_ns": .01 if change == "tiny_dsp" else None})
    elif change == "hold":
        s.paths[0] = path.model_copy(update={"analysis": "hold"})
    elif change == "passing":
        s.paths[0] = path.model_copy(update={"slack_ns": .5})
    elif change == "DFX":
        dsp.properties["HD.RECONFIGURABLE"] = "1"
    elif change == "preserved":
        dsp.properties["DONT_TOUCH"] = "true"
    elif change == "ambiguous":
        s.sources.append(s.sources[0].model_copy(update={"path": "other/filter_word.sv"}))
    assert "rtl.redistribute_arithmetic" not in {p.id for p in plans(s)}


@pytest.mark.parametrize("old,new", [
    ("t1 <= t0;", "if (gain[0]) t1 <= t0;"), ("t2 <= t1;", "t2 <= t1 + 1'b1;"),
    ("always_ff @(posedge clock)", "always @(posedge clock or negedge gain[0])"),
    ("logic [11:0]", "logic signed [11:0]"), ("wide[9:2]", "wide[gain:2]"),
    ("assign wide = left * right;", "assign wide = mixed * right;"),
    ("logic [9:0] t0", "logic [7:0] t0"), ("t2 <= t1;", "t2 <= t0;"),
    ("assign mixed =", "assign mixed = gain; assign mixed ="), ("t1 <= t0;", "t1 <= #1 t0;"),
    ("endmodule", "endmodule\nmodule other; endmodule"), ("module filter_word", "`define W 12\nmodule filter_word"),
])
def test_declines_unsupported_or_stateful_logic(old, new):
    assert pipeline(RTL.replace(old, new)) is None


def test_two_stage_budget_and_name_collision():
    rtl = RTL.replace("t0, t1, t2", "t0").replace("sample <= t2;", "sample <= t0;")
    rtl = rtl.replace("        t1 <= t0;\n", "").replace("        t2 <= t1;\n", "")
    assert pipeline(rtl) is None  # Three dependent named expressions cannot fit into two cycles.
    two_stage = rtl.replace("assign mixed = wide[9:2] - {2'b0, right};", "").replace("logic [7:0] mixed;", "")
    two_stage = two_stage.replace("(mixed * gain)", "wide[9:2] * gain")
    model = pipeline(two_stage)
    assert model.stages == 2 and "wide_s1 <= left * right;" in model.body
    assert "sample <= wide_s1[9:2] * gain_s1;" in model.body
    renamed = pipeline(RTL.replace("input logic clock", "input logic wide_s2, input logic clock"))
    assert "wide_s2_ <= left_s1 * right_s1" in renamed.body


def test_formal_accepts_candidate_and_rejects_misaligned_input(tmp_path):
    from timinglens.experiments.equivalence import discover_yosys
    from timinglens.experiments.pipeline_proof import solve
    try:
        discover_yosys()
        assert solve("(check-sat)") == "sat"
    except (ValueError, OSError):
        pytest.skip("Optional Yosys/Z3 tools unavailable")
    result = analyze(capture())
    candidate = prepare(result, result.investigations[0].plans[0])
    path = verify(candidate, tmp_path / "good")
    assert json.loads(path.read_text())["status"] == "passed"
    assert (path.parent / "solver.txt").read_text().split() == ["sat", "unsat"]
    with pytest.raises(FileExistsError):
        verify(candidate, path.parent)
    bad = replace(candidate, revised=candidate.revised.replace("mixed_s3 * gain_s3", "mixed_s3 * gain_s2"))
    with pytest.raises(ValueError, match="output mismatch"):
        verify(bad, tmp_path / "bad")
    assert json.loads((tmp_path / "bad/proof.json").read_text())["status"] == "counterexample"


def test_shared_fix_counts_distinct_paths_and_keeps_unrelated_failures_separate():
    s = capture()
    base = s.paths[0]
    # Different endpoints and DSPs in a second hardware instance of the same source.
    def rename(key):
        return "v" + key[1:] if key == "u" or key.startswith("u/") else key
    for name, cell in list(s.cells.items()):
        if rename(name) != name:
            s.cells[rename(name)] = cell.model_copy(update={"name": rename(name), "parent": rename(cell.parent or "") or None})
    pins = [rename(key) for key in base.pins]
    for old, new in zip(base.pins, pins):
        pin = s.pins[old]
        s.pins[new] = pin.model_copy(update={"name": new, "cell": rename(pin.cell)})
    for name in ("a", "p"):
        net = s.nets[name]
        s.nets[name+"2"] = net.model_copy(update={"name": name+"2", "drivers": [rename(n) for n in net.drivers],
                                                  "sinks": [rename(n) for n in net.sinks]})
    arcs = [arc.model_copy(update={"source": rename(arc.source), "sink": rename(arc.sink),
                                   "resource": rename(arc.resource) if arc.kind == "cell" else arc.resource+"2"})
            for arc in base.arcs]
    s.paths.append(base.model_copy(update={"id": "P2", "slack_ns": -2., "endpoint": pins[-1], "pins": pins,
                                           "arcs": arcs, "nets": ["a2", "p2"], "cells": [rename(n) for n in base.cells]}))
    rows = analyze(s).investigations
    assert len(rows) == 2  # One shared edit and the standalone forwarded clock review.
    shared = rows[0].plans[0]
    assert rows[0].path_ids == ("P2", "P1") and shared.evidence_links[0].path_ids == ("P2",)
    assert shared.evidence_links[-1].objects == ("u/dsp", "v/dsp")
    assert "2 hardware instances" in shared.evidence[0]
    s.cells["v/dsp"] = s.cells["v/dsp"].model_copy(update={"source": None})
    rows = analyze(s).investigations
    assert all(set(row.path_ids) != {"P1", "P2"} for row in rows)


def test_routed_assessment_binds_the_exact_edit_and_preserves_lab_gates(tmp_path):
    from timinglens.experiments.models import Run, BuildContext, Check
    from timinglens.experiments.pipeline_proof import compare_routed
    result = analyze(capture())
    candidate = prepare(result, result.investigations[0].plans[0])
    baseline_digest = sha256(candidate.source.encode()).hexdigest()
    candidate_digest = sha256(candidate.revised.encode()).hexdigest()
    from timinglens.experiments.equivalence import discover_yosys
    from timinglens.experiments.pipeline_proof import solve
    try:
        discover_yosys()
        solve("(check-sat)")
    except (OSError, ValueError):
        pytest.skip("Optional formal tools unavailable")
    proof = verify(candidate, tmp_path / "proof")

    def record(text, digest):
        source = Source(path=candidate.filename, sha256=digest, text=text)
        ctx = BuildContext(design_key="filter", mode="integrated", checkpoint_sha256="a"*64,
                           sources={"filter.sv": digest}, directives={"route": "Default"})
        return Run(label="run", session=result.session.model_copy(update={"sources": [source]}), context=ctx,
                   checks=[Check(name="source_checkpoint", status="passed", scope="fixture", evidence="same build")])
    before = record(candidate.source, baseline_digest)
    after = record(candidate.revised, candidate_digest)
    comparison = compare_routed(candidate, proof, before, after)
    assert comparison.acceptance != "review_ready"  # No design-wide summaries or implementation checks.
    assert any(g.name == "RTL equivalence" and g.status == "passed" for g in comparison.gates)
    from timinglens.experiments.io import write_run, load_run
    portable = tmp_path / "portable.run.json"
    write_run(portable, comparison.after)
    restored = load_run(portable)
    assert restored.fingerprint == comparison.after.fingerprint
    assert restored.attachments["pipeline-proof/solver.txt"].split() == ["sat", "unsat"]
    attachments = dict(restored.attachments)
    attachments.pop("pipeline-proof/check.smt2")
    with pytest.raises(ValueError, match="missing check.smt2"):
        Run.model_validate(restored.model_copy(update={"attachments": attachments}).model_dump())
    other_trigger = before.model_copy(update={"session": before.session.model_copy(update={"top": "different"})})
    with pytest.raises(ValueError, match="triggered"):
        compare_routed(candidate, proof, other_trigger, after)
    for bad in (before, after.model_copy(update={"population": "register_paths"}),
                after.model_copy(update={"context": after.context.model_copy(update={"directives": {"route": "Explore"}})}),
                after.model_copy(update={"checks": [Check(name="equivalence", status="failed", scope="design", evidence="counterexample")]})):
        with pytest.raises(ValueError):
            compare_routed(candidate, proof, before, bad)


def test_source_comments_and_directives_preserve_offsets_and_unsupported_hints_decline():
    rtl = "`timescale 1ns/1ps\n`default_nettype none\n" + RTL.replace(
        "    assign wide =", "    // Keep the low guard bits.\n    assign wide =") + "`default_nettype wire\n"
    model = pipeline(rtl)
    assert model and model.multiply_lines == (9, 14)
    assert "// Keep the low guard bits." in model.body
    assert rtl[:model.start].startswith("`timescale")
    assert pipeline(rtl.replace("Keep the low guard bits.", "synthesis translate_off")) is None
    assert pipeline(rtl.replace("assign wide =", "`default_nettype wire\n    assign wide =")) is None


def test_gui_verifier_uses_current_edit_and_keeps_constraint_review_separate(monkeypatch, tmp_path):
    import time
    from PySide6.QtWidgets import QApplication, QFileDialog
    from timinglens.gui.pages import Issues
    from timinglens.gui import pipeline_proof as worker

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(tmp_path))
    seen = []
    def proof(candidate, output):
        seen.append((candidate, output))
        return output / "proof.json"
    monkeypatch.setattr(worker, "verify", proof)
    app = QApplication.instance() or QApplication([])
    page = Issues()
    page.load(analyze(capture()))
    assert page.try_experiment.isEnabled() and page.try_experiment.text() == "Verify RTL fix…"
    page.try_experiment.click()
    deadline = time.monotonic() + 5
    while page.proof_worker and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert seen[0][0].source == RTL and seen[0][1].parent == tmp_path
    assert "Equivalence passed after 4 clock edges" in page.experiment_note.text()
    page.tree.setCurrentItem(page.tree.topLevelItem(1))
    assert page.current_plan.id == "constraints.first" and not page.try_experiment.isEnabled()
    assert "Equivalence passed" not in page.experiment_note.text()
    page.close()
