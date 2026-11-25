from collections import Counter
import os
from pathlib import Path

import pytest

from timinglens import analyze, read_session
from timinglens.cli import main
from timinglens.demo import TOPS

pytestmark = [
    pytest.mark.vivado,
    pytest.mark.skipif(os.environ.get("TIMINGLENS_TEST_VIVADO") != "1",
                       reason="set TIMINGLENS_TEST_VIVADO=1 to build real Vivado designs"),
]


@pytest.mark.parametrize("design", TOPS)
def test_routed_example(design, tmp_path):
    output = tmp_path / "result with spaces"
    assert main(["demo", "--run-vivado", "--design", design, "--max-paths", "48", "--output", str(output)]) == 0
    session = read_session(output / "analysis.json")
    result = analyze(session)
    assert session.stage == "routed"
    assert session.vivado == "2024.2"
    assert session.part == "xc7z020clg400-1"
    assert session.summary and session.paths
    assert session.clocks[0].period_ns is not None
    assert any(arc.delay_ns is not None for path in session.paths for arc in path.arcs)
    assert (output / "report.html").is_file()
    assert (output / "diagnostics.json").is_file()
    assert "timing_summary.rpt" in session.reports
    hits = Counter(f.rule for f in result.findings)
    if design == "clean":
        assert session.summary["setup"].failing_endpoints == session.summary["hold"].failing_endpoints == 0
        assert session.summary["setup"].total_negative_slack_ns == 0
        assert result.failing_paths == 0
        assert not result.groups
    else:
        assert session.summary["setup"].worst_slack_ns < 0
        assert result.failing_paths
    if design == "deep":
        deep = [p for p in session.paths if p.analysis == "setup" and (p.levels or 0) >= 12]
        assert deep and hits["TL-A"]
        assert result.paths[deep[0].id].module == "deep_kernel"
        assert result.paths[deep[0].id].confidence.label == "Strong"
        assert result.paths[deep[0].id].first is None
        assert any(c.name.startswith("u_kernel/") for c in session.cells.values())
    if design == "priority":
        findings = [f for f in result.findings if f.rule == "TL-B"]
        assert findings and {f.module for f in findings} == {"priority_select"}
        assert any("electrically cascaded mux" in " ".join(f.evidence) for f in findings)
    if design == "fanout":
        control = session.nets["control_q"]
        assert control.fanout == 192
        assert control.drivers == ["control_q_reg/Q"]
        assert not control.sinks_complete
        assert any(f.rule == "TL-C" and f.anchors == ("control_q",) for f in result.findings)


def test_checkpoint_and_isolated_project_inputs(tmp_path):
    import subprocess
    from timinglens.demo import example_path
    from timinglens.vivado.runner import discover

    example = example_path() / "clean"
    make = tmp_path / "create.tcl"
    make.write_text(f"""create_project sample original -part xc7z020clg400-1
add_files {{{example / 'design.sv'}}}
add_files -fileset constrs_1 {{{example / 'timing.xdc'}}}
set_property top clean [current_fileset]
close_project
""")
    proc = subprocess.run([str(discover()), "-mode", "batch", "-nolog", "-nojournal", "-source", "create.tcl"],
                          cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    project = tmp_path / "original" / "sample.xpr"
    original = project.read_bytes()
    isolated = tmp_path / "isolated"
    assert main(["analyze", "--project", str(project), "--build", "route", "--max-paths", "5",
                 "--output", str(isolated)]) == 0
    assert project.read_bytes() == original
    assert not (project.parent / "sample.runs").exists()
    clone = next(isolated.glob("vivado-*/build/timinglens-build.xpr"))
    read_only = tmp_path / "read_only"
    before_clone = clone.read_bytes()
    assert main(["analyze", "--project", str(clone), "--max-paths", "5", "--output", str(read_only)]) == 0
    assert clone.read_bytes() == before_clone
    terminal = read_session(read_only / "analysis.json")
    assert terminal.run == "impl_1"
    checkpoint = next(isolated.glob("vivado-*/build/*.runs/impl_1/*_routed.dcp"))
    checkpoint_bytes = checkpoint.read_bytes()
    dcp_output = tmp_path / "checkpoint"
    assert main(["analyze", "--checkpoint", str(checkpoint), "--max-paths", "5", "--output", str(dcp_output)]) == 0
    assert checkpoint.read_bytes() == checkpoint_bytes
    assert read_session(dcp_output / "analysis.json").summary == terminal.summary


def test_cancels_real_vivado_process(tmp_path):
    from threading import Event
    from timinglens.demo import request_for
    from timinglens.vivado.runner import Cancelled, run

    cancel = Event()

    def on_log(line):
        if line == "TimingLens: synthesizing deep":
            cancel.set()

    with pytest.raises(Cancelled):
        run(request_for("deep", tmp_path, build="synth"), log=on_log, cancel=cancel)
    assert not (tmp_path / "analysis.json").exists()
    assert "TimingLens: synthesizing deep" in next(tmp_path.glob("vivado-*/vivado.log")).read_text()
