"""Exercise an unplaceable Vivado baseline and a verified, publishable native BD edit."""
import json
import os
from pathlib import Path
import subprocess

import pytest

from timinglens.experiments.auto_fix import AutoRequest, run_auto
from timinglens.experiments.auto_project import Project
from timinglens.experiments.io import load_run
from timinglens.vivado.runner import discover


@pytest.mark.vivado
@pytest.mark.skipif(os.environ.get("TIMINGLENS_TEST_VIVADO") != "1",reason="requires a local Vivado run")
def test_auto_publish_rescues_actual_dsp_allocation_failure(tmp_path):
    vivado = discover()
    create = Path(__file__).resolve().parents[2] / "examples/resource-balance/create.tcl"
    project = tmp_path / "input" / "banks.xpr"
    subprocess.run([vivado, "-mode", "batch", "-notrace", "-source", str(create), "-tclargs",
                    str(project.parent), "small-region"], cwd=tmp_path, check=True, capture_output=True, text=True)
    original = Project.read(project)
    out = tmp_path / "verified"
    result = run_auto(AutoRequest(project, out, vivado, apply_to_source=True, paths=12, resource_limit=85))
    decision = json.loads((out / "decision.json").read_text())
    assert result.status == "applied", decision
    budget = decision["resource_budget"]
    assert budget["baseline_stage"] == "synthesized"
    assert budget["before"]["dsp"]["used"] == 8 and budget["before"]["dsp"]["available"] == 4
    attempt, = decision["attempts"]
    assert attempt["resources_after"]["dsp"]["used"] == 0
    comparison = out / attempt["comparison"]
    candidate = load_run(comparison / "candidate.run.json")
    assert candidate.session.stage == "routed" and candidate.timing["setup"].worst_slack_ns >= 0
    assert json.loads(candidate.attachments["validation/resource-budget.json"])["resource_check"] == "passed"
    assert any(c.name == "resource_budget" and c.status == "passed" for c in candidate.checks)
    assert any(c.name == "drc_warning_review" and c.status == "passed" for c in candidate.checks)
    metrics = json.loads((comparison / "comparison.json").read_text())["metrics"]
    assert all(row["before"] is None and row["delta"] is None for row in metrics if row["key"].startswith(("setup.", "hold.")))
    published = Project.read(project)
    assert {str(rel) for rel in original.tracked if original.tracked[rel] != published.tracked[rel]} == set(attempt["changed_files"])
    assert all((out / "original" / name).is_file() for name in attempt["changed_files"])
