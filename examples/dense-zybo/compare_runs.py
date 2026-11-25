"""Publish the two routed sessions and their frozen inputs to the TimingLens Lab."""
import argparse
from difflib import unified_diff
from hashlib import sha256
import json
from pathlib import Path
import re

from timinglens.experiments.capture import from_session
from timinglens.experiments import compare, export_comparison
from timinglens.experiments.models import Artifact, BuildContext, Check
from timinglens.timing.io import read_session


def digest(file):
    return sha256(file.read_bytes()).hexdigest()


def routed_run(build, session_path, simulation, label):
    reports = {name: (build / name).read_text() for name in
               ("utilization.rpt", "timing_summary.rpt", "check_timing.rpt", "drc.rpt", "route_status.rpt")}
    session = read_session(session_path)
    assert session.stage == "routed" and session.part == "xc7z020clg400-1"
    assert Path(session.origin).resolve() == (build / "routed.dcp").resolve()
    saved = dict(session.reports)
    saved.update({"build/" + k: v for k, v in reports.items()})
    run = from_session(session.model_copy(update={"reports": saved}), label)
    inputs = build / "src"
    sources = {name: digest(inputs / name) for name in ("fabric.v", "calibration.v", "build.tcl")}
    captured = {Path(s.path).resolve(): s.sha256 for s in session.sources}
    for name in (*sources, "timing.xdc"):
        assert captured[(inputs / name).resolve()] == digest(inputs / name)
    implementation = (build / "implementation.log").read_text()
    for marker in ("synth_design completed successfully", "place_design completed successfully",
                   "route_design completed successfully", "report_drc completed successfully"):
        assert marker in implementation, marker
    check = next(s for s in simulation.read_text().splitlines() if s.startswith("PASS: 2560 consecutive frames"))
    flagged = {name: number for name, number in session.timing_checks.items() if number}
    assert flagged == {"no_output_delay": 1}, flagged
    audit = reports["check_timing.rpt"]
    assert "0 ports with no output delay specified" in audit
    assert re.search(r"1 port with no output delay but with a timing clock defined on it or propagating through it \(LOW\)\s+strobe\b", audit)
    assert re.search(r'Design State\s*:\s*Fully Routed', reports["drc.rpt"])
    native = re.search(r'^\s+WNS\(ns\).*?\n[^\n]*\n([^\n]+)', reports["timing_summary.rpt"], re.M)[1].split()
    for offset, typ in ((0,"setup"), (4,"hold")):
        ref = session.summary[typ]
        assert list(map(float, native[offset:offset+4])) == [
            ref.worst_slack_ns, ref.total_negative_slack_ns, ref.failing_endpoints, ref.total_endpoints]
    context = BuildContext(design_key="Zybo Z7-20 / 104-lane distance monitor",
        mode="integrated", constraints={"timing.xdc":digest(inputs / "timing.xdc")}, sources=sources,
        directives={"synth":"rebuilt", "opt":"Default", "place":"Default","phys_opt":"Default","route":"Default"},
        compile_context={"top":"monitor_wrapper","input HDL":"fabric.v, calibration.v and generated BD wrappers",
                         "build Tcl SHA256":sources["build.tcl"], "banks":"13","lanes per bank":"8","history taps":"6"},
        checkpoint_sha256=digest(build / "routed.dcp"), dfx=False,
        notes=["Vivado's single LOW no_output_delay item is the forwarded clock output strobe. "
               "All four data outputs have min/max constraints relative to its rising edge."])
    checks = [Check(name="functional", status="passed", scope="Full design, behavioural XSim against independent stream model", evidence=check),
              Check(name="source_checkpoint", status="passed", scope="Isolated implementation workspace and reopened routed DCP",
                    evidence="The run transcript, frozen RTL/build/XDC hashes and DCP SHA-256 accompany this capture.")]
    attachments={"validation/simulation.txt":check+"\n"}
    artifacts=[*run.artifacts, Artifact(name="routed.dcp",sha256=context.checkpoint_sha256,kind="routed_checkpoint"),
               Artifact(name="implementation.log",sha256=digest(build / "implementation.log"),kind="build_transcript")]
    for name, data in attachments.items():
        artifacts.append(Artifact(name=name,sha256=sha256(data.encode()).hexdigest(),kind="validation"))
    return run.model_copy(update={"context":context,"checks":checks,"attachments":attachments,"artifacts":artifacts})


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("original","revised","original_session","revised_session","original_sim","revised_sim","output"):
        p.add_argument(name, type=Path)
    p.add_argument("--proof", required=True, type=Path, help="directory produced by prove.py")
    args=p.parse_args()
    before=routed_run(args.original, args.original_session, args.original_sim, "Original calibration")
    after=routed_run(args.revised, args.revised_session, args.revised_sim, "Pipelined calibration")
    assert before.context.constraints == after.context.constraints
    assert before.context.directives == after.context.directives and before.context.compile_context == after.context.compile_context
    changed=[f for f in before.context.sources if before.context.sources[f] != after.context.sources[f]]
    assert changed == ["calibration.v"], changed
    proof_text = (args.proof / "result.json").read_text()
    proof = json.loads(proof_text)
    assert proof["status"] == "passed" and proof["source_sha256"] == {
        "original": before.context.sources["calibration.v"], "revised": after.context.sources["calibration.v"]}
    assert (args.proof / "solver.txt").read_text().split() == ["sat", "unsat"]
    diff=''.join(unified_diff((args.original/'src/calibration.v').read_text().splitlines(True),
                              (args.revised/'src/calibration.v').read_text().splitlines(True),
                              'original/calibration.v','revised/calibration.v'))
    name = "validation/calibration-proof.json"
    after=after.model_copy(update={"change_diff":diff,
        "attachments":{**after.attachments, name:proof_text},
        "artifacts":[*after.artifacts, Artifact(name=name,kind="validation",sha256=sha256(proof_text.encode()).hexdigest())],
        "notes":[*after.notes, "Independent Yosys/Z3 proof: the revised four-stage calibration matches "
                               "the original on every output bit after pipeline fill for arbitrary two-state input streams."]})
    export_comparison(compare(before, after), args.output)
    print(json.loads((args.output/"comparison.json").read_text())["headline"])


if __name__ == "__main__":
    main()
