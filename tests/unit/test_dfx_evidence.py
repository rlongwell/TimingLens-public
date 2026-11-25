"""Real Vivado 2024.2 DFX path, captured before the report-column parser fix."""
from pathlib import Path

import pytest

from timinglens import analyze, read_session
from timinglens.service import load, export_result
from timinglens.vivado.decode import refresh_report_arcs
from timinglens.vivado.reports import detail_blocks, detail_rows

FIXTURE = Path(__file__).parents[1] / "fixtures/zybo_dfx_path.json"


def test_real_dfx_detail_rejoins_all_delays_and_capped_sink():
    original = read_session(FIXTURE)
    assert all(a.delay_ns is None for a in original.paths[0].arcs)
    result = load(FIXTURE)
    p = result.session.paths[0]
    coverage = result.coverage[p.id]
    assert coverage.complete and coverage.measured_delays == coverage.captured_links == 34
    assert p.slack_ns == -.011 and p.logic_ns == 3.026 and p.routing_ns == 6.523
    reset = next(a for a in p.arcs if a.resource == "rp_resetn")
    assert reset.delay_ns == 1.052
    assert reset.sink == "u_shell/rp_tkeep[7]_INST_0/I1"
    # The full report identifies this sink even though the capped net snapshot omits it.
    assert reset.sink not in result.session.nets[reset.resource].sinks
    slow = sorted((a for a in p.arcs if a.kind == "net"), key=lambda a: -a.delay_ns)
    assert [a.delay_ns for a in slow[:3]] == [1.058, 1.052, .870]
    assert slow[0].resource == "rp_tkeep[7]"
    for kind, total in (("net", p.routing_ns), ("cell", p.logic_ns)):
        assert sum(a.delay_ns for a in p.arcs if a.kind == kind) == pytest.approx(total, abs=.003)
    routing = next(f for f in result.findings if f.rule == "TL-D")
    assert any("1.058 ns" in e and "SLICE_X51Y58" in e for e in routing.evidence)
    assert not result.warnings
    assert result.session.reports == original.reports
    assert refresh_report_arcs(result.session) == result.session


def test_dfixed_columns_keep_resource_names_and_wrapped_carry_rows():
    session = read_session(FIXTURE)
    text = detail_blocks(session.reports["setup-paths.rpt"])["P00001"]
    rows = detail_rows(text)
    assert ("net", "u_shell/rp_resetn", 1.052) in rows
    assert ("pin", "u_hash/engine/input_buffer/error_reg_i_36/CO[3]", .550) in rows
    # Resource names can contain spaces; splitting off the final word is unsafe.
    spaced = text.replace("u_shell/rp_resetn", "escaped name/rp_resetn")
    assert ("net", "escaped name/rp_resetn", 1.052) in detail_rows(spaced)


def test_missing_detail_is_visible_and_never_becomes_zero(tmp_path):
    original = read_session(FIXTURE)
    result = analyze(original)
    assert "0/33 arc delays measured" in result.coverage_note
    assert "33/34 consecutive pin links" in result.coverage_note
    assert "incomplete" in result.warnings[0]
    assert "unknown, not zero" in result.warnings[0]
    export_result(result, tmp_path)
    html = (tmp_path / "report.html").read_text()
    assert "Detailed timing evidence is incomplete" in html
    assert "Raw Vivado path" in html and "Partition" in html
    assert "Unavailable" in html


def test_bad_report_labels_do_not_invent_measured_arcs():
    original = read_session(FIXTURE)
    reports = {k: v.replace("Partition", "Unknown  ") for k, v in original.reports.items()}
    result = analyze(refresh_report_arcs(original.model_copy(update={"reports": reports})))
    assert not result.coverage["P00001"].complete
    assert all(a.delay_ns is None for a in result.session.paths[0].arcs)
    assert result.warnings


def test_hidden_vivado_resources_remain_unassigned():
    original = read_session(FIXTURE)
    text = original.reports["setup-paths.rpt"].replace("u_shell/reset_count_reg[2]/Q", "<hidden>")
    result = analyze(refresh_report_arcs(original.model_copy(update={"reports": {"setup-paths.rpt": text}})))
    assert not result.coverage["P00001"].complete
    assert any("Vivado hides resource names" in note for note in result.warnings)


def test_source_tag_is_not_promoted_to_a_causal_path_line():
    result = load(FIXTURE)
    source = result.paths["P00001"]
    assert source.module == "axis_bytes" and source.first is None and not source.constructs
    assert "hash_shell" in source.reason and "No single RTL line" in source.reason
    tag = result.cells["u_hash/engine/input_buffer/error_reg_i_36"]
    assert tag.first == 23  # Vivado's tag is a popcount for-loop, not the comparator.
    assert tag.confidence.label == "Vivado source tag"
    assert "not a proven critical expression" in tag.reason
