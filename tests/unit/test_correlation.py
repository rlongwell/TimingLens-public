from hashlib import sha256
from pathlib import Path

from timinglens import Session, analyze, read_session
from timinglens.rtl.correlate import Confidence, correlate
from timinglens.rtl.syntax import build_index, source_text
from timinglens.timing.models import Cell, Source, SourceLink

HDL = """module selector(input logic clock, a, b, output logic y);
  always_ff @(posedge clock) y <= a & b;
endmodule
module top(input logic clock, a, b, output logic y);
  selector u_select (.*);
endmodule
"""


def test_evidence_levels_and_ambiguous_import():
    source = Source(path="example.sv", text=HDL)
    scope = Cell(name="u_select", primitive="selector", hierarchical=True)
    cell = Cell(name="u_select/y_reg", primitive="FDRE", parent=scope.name)
    session = Session(name="test", top="top", sources=[source], cells={scope.name: scope, cell.name: cell})
    index = build_index(session.sources)
    association = correlate(cell, session, index)
    assert association.confidence == Confidence.STRONG
    assert association.module == "selector"
    assert association.first is None
    assert association.module_line == 1
    direct = SourceLink(file=source.path, first_line=2, last_line=2, provenance="vivado_cell_file_name_line_number")
    exact = correlate(cell.model_copy(update={"source": direct}), session, index)
    assert exact.confidence == Confidence.EXACT and exact.first == exact.last == 2
    missing = source.model_copy(update={"text": None})
    fallback = correlate(cell, session, build_index([missing]))
    assert fallback.confidence == Confidence.PARTIAL and fallback.module == "selector"
    assert fallback.first is None
    result = analyze(read_session(Path(__file__).parents[1] / "fixtures" / "ambiguous.json"))
    assert result.paths["P1"].confidence == Confidence.UNKNOWN
    assert result.paths["P1"].first is None
    assert result.findings[0].rule == "TL-H"


def test_source_reads_are_explicit_and_digest_checked(tmp_path):
    private = tmp_path / "example.sv"
    private.write_text(HDL)
    source = Source(path=str(private), sha256=sha256(private.read_bytes()).hexdigest())
    assert source_text(source) is None
    assert source_text(source, True) == HDL
    private.write_text("other revision")
    assert source_text(source, True) is None


def test_exclusive_case_only_is_not_priority():
    source = Source(path="parallel.sv", text="""module parallel(input logic [1:0] sel, input logic a,b,c, output logic y);
    always_comb unique case (sel)
     2'b00: y = a;
     2'b01: y = b;
     default: y = c;
    endcase
    endmodule
    """)
    module = build_index([source]).modules["parallel"][0]
    assert not any(c.kind == "priority selection candidate" for c in module.constructs)


def test_parsed_if_chain_and_snapshot_include_boundaries(tmp_path, monkeypatch):
    rtl = """`include "unlisted.svh"
module m(input logic a,b,c, output logic y);
  always_comb if (a) y = b; else if (b) y = c; else y = 0;
endmodule"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "unlisted.svh").write_text("module ambient_sentinel; endmodule")
    index = build_index([Source(path=str(tmp_path / "m.sv"), text=rtl)])
    assert "ambient_sentinel" not in index.modules
    assert any(item.kind == "priority selection candidate" for item in index.modules["m"][0].constructs)
