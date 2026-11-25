"""Route, diagnose, validate and apply a source or IP change in an isolated project."""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import unified_diff
from hashlib import sha256
import json
import shutil
from pathlib import Path
from threading import Event

from ..analysis.bd_multiplier import RULE
from ..analysis.engine import Analysis, analyze
from ..analysis.fixes import dfx_scope
from ..service import export_result
from ..timing.io import atomic_text
from ..vivado.decode import decode
from ..vivado.runner import Cancelled, discover
from . import auto_ip, memory_check, resource_balance as balance
from ..analysis.inferred_memory import Memory
from ..timing.models import Source
from .auto_project import Project, digest
from .capture import from_session
from .compare import compare
from .io import export_comparison
from .models import Artifact, BuildContext, Check, Run
from .pipeline_proof import Candidate, compare_routed, prepare, verify
from .process import ProcessFailure, execute

RTL = "rtl.redistribute_arithmetic"
ROUTE = Path(__file__).with_name("auto_route.tcl")


@dataclass(frozen=True)
class AutoRequest:
    project: Path
    output: Path
    vivado: str | None = None
    apply_to_source: bool = False
    paths: int = 48
    resource_limit: int | None = None


@dataclass
class AutoResult:
    analysis: Analysis
    directory: Path
    status: str
    message: str


def freeze_recipe(out):
    scripts = (("experiments", ROUTE), ("experiments", ROUTE.with_name("auto_ip.tcl")),
               ("experiments", ROUTE.with_name("auto_dsp_cells.tcl")),
               ("experiments", ROUTE.with_name("resource_owners.tcl")), ("experiments", ROUTE.with_name("ram_model.tcl")), ("vivado", ROUTE.parent.parent / "vivado/extract.tcl"))
    for folder, script in scripts:
        target = out / "recipe" / folder / script.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(script, target)


def job_recipe(directory):
    return directory.parent / "recipe/experiments/auto_route.tcl"


def route(project, directory, vivado, paths, cancel, log):
    args = [vivado, "-mode", "batch", "-notrace", "-source", job_recipe(directory), "-tclargs", project, paths]
    transcript = directory / "implementation.log"
    try:
        execute(args, directory, transcript, cancel, 7200, log)
    except ProcessFailure as error:
        with transcript.open(errors="replace") as stream:
            detail = next((line.strip() for line in stream if line.startswith("ERROR:")), "")
        if detail:
            raise ProcessFailure(f"{detail} See {transcript}") from error
        raise


def collect_route(project, directory, layout, paths):
    log = directory/"implementation.log"
    lines = log.read_text().splitlines()
    constraint_error = next((line for line in lines if (line.startswith("CRITICAL WARNING:") and (".xdc" in line.lower() or "constraint" in line.lower()))
                             or (line.startswith("WARNING:") and "No sites matched" in line and ".xdc" in line.lower())), None)
    if constraint_error:
        raise ValueError(f"Vivado reported an unresolved project constraint: {constraint_error}")
    unplaced = "TIMINGLENS_UNPLACED_BASELINE" in lines
    if unplaced:
        pools = balance.capacity((directory/"utilization.rpt").read_text())
        allocation_error = any(
            line.startswith("ERROR: [DRC UTLZ-1]") or
            (line.startswith("ERROR: [Place ") and any(name in line.lower() for name in ("dsp", "ram", "lut"))
             and any(term in line.lower() for term in ("requires more", "over-utilized", "available sites",
                                                       "unplaced instances require")))
            for line in lines)
        if not allocation_error or not any(p.exceeds(100) for p in pools.values()):
            raise ValueError(f"Implementation stopped without a verified device capacity overrun. See {log}")
    if not unplaced and "TIMINGLENS_AUTO_ROUTE_COMPLETE" not in lines:
        raise ValueError(f"The route and timing capture did not complete. See {log}")
    files = [project.parent / rel for rel in layout.files]
    session = decode(directory, paths, 1, "synth" if unplaced else "route", files, True)
    # Keep the authored inputs in the portable record. Generated IP implementation
    # products are reproducible from the captured BD and remain in the project copy.
    authored = {str(p) for p in files}
    sources = [s for s in session.sources if s.path in authored]
    if session.stage != ("synthesized" if unplaced else "routed") or {s.path for s in sources} != authored or any(
            s.text is None or sha256(s.text.encode()).hexdigest() != digest(Path(s.path)) for s in sources):
        raise ValueError("The routed capture is missing reproducible project source bytes.")
    session = session.model_copy(update={"sources": sources})
    result = analyze(session)
    export_result(result, directory/"analysis")
    return result


def record(result, layout, project, directory, label, functional=None, evidence="", validation=None):
    run = from_session(result.session, label)
    sources, constraints = {}, {}
    for rel in layout.files:
        dest = constraints if rel.suffix.lower() == ".xdc" else sources
        dest[str(rel)] = digest(project.parent / rel)

    ancillary = {str(rel): digest(project.parent / rel) for rel in layout.tracked
                 if rel != Path(project.name) and rel not in layout.files}
    stage = result.session.stage
    checkpoint_name = "routed.dcp" if stage == "routed" else "synthesized.dcp"
    checkpoint = Artifact(name=checkpoint_name, kind=stage+"_checkpoint", sha256=digest(directory / checkpoint_name))
    context = BuildContext(
        design_key=layout.xpr.stem, mode="integrated", dfx=False, sources=sources, constraints=constraints,
        directives={"synth": "rebuilt", "opt": "Default", "place": "Default", "phys_opt": "Default", "route": "Default"},
        compile_context={
            "project_config": layout.tracked[Path(layout.xpr.name)],
            "recipe": digest(job_recipe(directory)),
            "auxiliary_inputs": json.dumps(ancillary, sort_keys=True),
            "collector": digest(directory.parent / "recipe/vivado/extract.tcl"),
            "top": result.session.top,
            "design_inputs": "\n".join(map(str, layout.files)),
        },
        checkpoint_sha256=checkpoint.sha256,
    )
    checks = [Check(name="source_checkpoint", status="passed", scope=f"Owned project copy and {stage} checkpoint.",
                    evidence="The source digests, native checkpoint and transcript were collected in the same run.")]
    artifacts = [*run.artifacts, checkpoint, Artifact(name="implementation.log", kind="build_transcript",
                                                       sha256=digest(directory / "implementation.log"))]
    attachments = {name: path.read_text() for name, path in (validation or {}).items()}
    if (directory/"resource-owners.tsv").exists():
        attachments["validation/resource-owners.tsv"] = (directory/"resource-owners.tsv").read_text()
    if functional:
        checks.append(Check(name="functional", status="passed", scope=functional, evidence=evidence))
        attachments["validation/behavior.txt"] = evidence
    for name, content in attachments.items():
        artifacts.append(Artifact(name=name, kind="validation", sha256=sha256(content.encode()).hexdigest()))
    fields = {"context": context, "checks": checks, "artifacts": artifacts, "attachments": attachments}
    return Run.model_validate(run.model_copy(update=fields).model_dump())


def choices(analysis):
    seen = set()
    for row in analysis.investigations:
        for plan in row.plans:
            if plan.id not in {RTL, RULE}:
                continue
            key = plan.id, plan.scope, plan.source_candidates[0].file
            if key not in seen:
                seen.add(key)
                yield plan


def closure(comparison, dsp_advisories=None, *, capacity_goal=False):
    unplaced = capacity_goal and comparison.before.session.stage == "synthesized"

    failures = [g.name for g in comparison.gates if g.name != "Regression guard" and g.status not in {"passed","not_applicable"}]
    # Closing setup can redistribute already-positive hold margin. Keep the Lab's
    # numerical regression visible; reject new endpoint failures and all other regressions.
    for metric in comparison.metrics:
        if metric.status != "regressed":
            continue
        if unplaced:
            continue  # Pre-placement metrics are not routed regression measurements.
        if capacity_goal and metric.key == "setup.worst_slack_ns" and metric.after >= 0:
            continue
        if metric.key == "drc.warnings" and dsp_advisories:
            continue
        if metric.key in {"hold.worst_slack_ns", "pulse.wns"} and min(metric.before, metric.after) >= 0:
            continue
        failures.append(metric.label)
    if not unplaced and any(e.status == "newly_failing" for e in comparison.endpoints):
        failures.append("New failing captured endpoint")
    a = comparison.before.timing.get("setup")
    if not capacity_goal and (not a or a.worst_slack_ns is None or a.worst_slack_ns >= 0):
        failures.append("No baseline setup failure")
    return failures


@dataclass
class ValidatedEdit:
    files: dict[Path, tuple[bytes, bytes]]
    scope: str
    evidence: str
    logs: dict[str, Path] = field(default_factory=dict)
    rtl_candidate: Candidate | None = None
    proof: Path | None = None
    xci: Path | None = None
    ip_module: str | None = None

    @property
    def hashes(self):
        return {str(name): {"before": sha256(old).hexdigest(), "after": sha256(new).hexdigest()}
                for name, (old, new) in self.files.items()}

    @property
    def patch(self):
        return "".join(line for name, (a, b) in sorted(self.files.items())
                       for line in unified_diff(a.decode().splitlines(True), b.decode().splitlines(True),
                                                f"a/{name}", f"b/{name}"))

    def compare_runs(self, before, after):
        expected = dict(before.context.sources)
        for name, hashes in self.hashes.items():
            if expected.get(name) != hashes["before"]:
                raise ValueError("Baseline source differs from the validated change.")
            expected[name] = hashes["after"]
        if expected != after.context.sources:
            raise ValueError("Routed inputs differ from the validated change.")
        if self.rtl_candidate:
            return compare_routed(self.rtl_candidate, self.proof, before, after)
        return compare(before, after.model_copy(update={"change_diff": self.patch}))

    def publish(self, project, rel, backup):
        if self.xci:
            project.publish_block(rel, self.xci, {k:b for k, (_,b) in self.files.items()}, backup)
        else:
            project.publish(rel, self.files[rel][1], backup / rel)


def validate_edit(layout, analysis, plan, project, target, rel, directory, vivado, cancel, log, *, move=None):
    source = target.parent / rel
    old = source.read_bytes()
    if move and isinstance(move.target, Memory):
        memory = move.target
        if sha256(old).hexdigest() != memory.digest or digest(project.parent / rel) != memory.digest:
            raise ValueError("Memory source changed after the baseline build.")
        style = "distributed" if move.destination == "lutram" else "block"
        revised = memory.mapped_source(old.decode(), style).encode()
        script = directory.parent / "recipe/experiments/ram_model.tcl"
        part = analysis.session.part
        baseline_log = memory_check.simulate(memory, project.parent / rel, memory.style or "auto", part,
                                             directory / "original-memory", script, vivado, cancel, log)
        source.write_bytes(revised)
        candidate_log = memory_check.simulate(memory, source, style, part, directory / "candidate-memory",
                                              script, vivado, cancel, log)
        return ValidatedEdit({rel:(old,revised)}, "Read-first RAM behavior and cycle latency in both synthesized primitive models.",
            f"Each model passed {2*memory.depth+4096} scoreboard reads including write collisions and disabled writes.",
            logs={"validation/baseline-ram.log":baseline_log,"validation/candidate-ram.log":candidate_log,
                  "validation/memory_check.sv":candidate_log.parent/"memory_check.sv"})
    if plan.id == RTL:
        candidate = prepare(analysis, plan)
        if old != candidate.source.encode():
            raise ValueError("The input no longer matches the proposed edit.")
        proof = verify(candidate, directory / "proof")
        revised = candidate.revised.encode()
        source.write_bytes(revised)
        return ValidatedEdit({rel:(old, revised)}, "Leaf RTL equivalence for arbitrary binary inputs after pipeline fill.",
                             proof.read_text(), rtl_candidate=candidate, proof=proof)

    ip = auto_ip.multiplier(analysis, plan)
    if digest(source) != ip.digest:
        raise ValueError("The block design differs from the measured revision.")
    xci = auto_ip.child_xci(layout, rel, ip)
    old_xci = (target.parent / xci).read_bytes()
    # A simulation project carries its own generated model and testbench.
    script = directory.parent / "recipe/experiments/auto_ip.tcl"
    old_mapping, new_mapping = auto_ip.mappings(ip)
    base_sim = auto_ip.simulate_copy(layout, project, rel, ip, directory / "baseline-sim",
                                     vivado, cancel, log, old_mapping, script)
    auto_ip.run_ip("apply", target, source, ip, directory / "edit", vivado, cancel, log, old_mapping, script)
    new, new_xci = source.read_bytes(), (target.parent / xci).read_bytes()
    auto_ip.check_edit(old, new, ip)
    auto_ip.check_xci(old_xci, new_xci, ip)
    new_sim = auto_ip.simulate_copy(layout, target, rel, ip, directory / "candidate-sim",
                                    vivado, cancel, log, new_mapping, script)
    logs = {"validation/original-xsim.log":base_sim, "validation/candidate-xsim.log":new_sim,
            "validation/multiplier_tb.sv":new_sim.parent / "auto_ip_tb.sv"}
    return ValidatedEdit({rel:(old, new), xci:(old_xci, new_xci)},
                         f"Xilinx {ip.module} full-width product and exact {ip.latency}-edge latency on both configurations.",
                         "Both XSim runs passed 4096 independently scored products including boundaries and changing inputs.",
                         logs=logs, xci=xci, ip_module=ip.module if new_mapping == "Use_Mults" else None)


def _check_constraints(result):
    checks = result.session.timing_checks
    if not {"no_clock", "unconstrained_internal_endpoints"} <= checks.keys():
        return False
    for finding in result.findings:
        if finding.rule == "TL-G" and finding.anchors != ("check_timing/no_output_delay",):
            return False
    return (not any(checks.values()) or
            (bool(result.forwarded_clock_outputs) and all(key == "no_output_delay" or n == 0
                                                         for key,n in result.session.timing_checks.items())))


def collect_ownership(layout, directory, *, baseline=False):
    sources = []
    for rel in layout.files:
        if rel.suffix.lower() in {".v", ".sv", ".bd"}:
            path = layout.xpr.parent / rel
            sources.append(Source(path=str(path), text=path.read_text(), sha256=layout.tracked[rel]))
    modules = sorted(t.module for t in balance.targets(sources))
    (directory/"owner-modules.txt").write_text("".join(name+"\n" for name in modules))
    if baseline:
        (directory/"allow-unplaced-baseline").touch()


def run_auto(request, log=lambda _:None, cancel=None):
    cancel = cancel or Event()
    layout = Project.read(request.project)
    out = request.output.resolve()
    if out == layout.xpr.parent or out.is_relative_to(layout.xpr.with_suffix(".srcs")):
        raise ValueError("Choose a fresh job directory outside the project source set.")
    if not 1 <= request.paths <= 1000:
        raise ValueError("Choose between 1 and 1000 captured paths per check.")
    if request.resource_limit is not None and (type(request.resource_limit) is not int or not 1 <= request.resource_limit <= 100):
        raise ValueError("Choose a resource limit between 1 and 100 percent.")
    vivado = discover(request.vivado)
    out.mkdir(parents=True, exist_ok=False)
    state = {"project":str(layout.xpr), "apply_to_source":request.apply_to_source, "attempts":[]}
    def save(status, message):
        state.update(status=status,message=message)
        atomic_text(out/"decision.json", json.dumps(state, indent=2)+"\n")
        log(message)
    try:
        save("running", "Routing the isolated baseline project.")
        freeze_recipe(out)
        frozen = Project.read(layout.clone(out / "inputs"))
        base = out / "baseline"
        project = frozen.clone(base / "project")
        if request.resource_limit is not None:
            collect_ownership(frozen, base, baseline=True)
        route(project, base, vivado, request.paths, cancel, log)
        analysis = collect_route(project, base, layout, request.paths)
        return try_fixes(request, frozen, analysis, project, base, out, vivado, state, save, cancel, log, original=layout)
    except Exception as error:
        save("cancelled" if isinstance(error, Cancelled) else "failed", str(error))
        raise


def try_fixes(request, layout, analysis, project, base, out, vivado, state, save, cancel, log, *, original=None):
    original = original or layout
    if dfx_scope(analysis):
        message = "Reconfigurable partition compatibility requires engineering review."
        save("review", message)
        return AutoResult(analysis, out, "review", message)
    before = record(analysis,layout,project,base, "Unplaced baseline (synthesis)" if analysis.session.stage=="synthesized" else "Baseline")
    setup = analysis.session.summary.get("setup")
    hold = analysis.session.summary.get("hold")
    if not _check_constraints(analysis):
        message = "Resolve the baseline clock and timing coverage findings before automatic changes."
        save("review", message)
        return AutoResult(analysis, out, "review", message)
    limit = request.resource_limit
    moves = []
    pressured = False
    if limit is not None:
        pools = balance.capacity(analysis.session.reports["utilization.rpt"])
        ownership = balance.owners((base/"resource-owners.tsv").read_text())
        pressured = any(p.exceeds(limit) for p in pools.values())
        moves, skipped = balance.proposals(balance.targets(analysis.session.sources), ownership, pools, limit)
        state["resource_budget"] = {"limit_percent":limit, "baseline_stage":analysis.session.stage,
                                    "before":balance.measurements(pools), "skipped":skipped}
    if (not pressured and setup and hold and setup.failing_endpoints == hold.failing_endpoints == 0 and
            all(s.worst_slack_ns is not None and s.worst_slack_ns >= 0 for s in (setup, hold))
            and before.metrics.get("pulse.wns", -1) >= 0
            and all(before.metrics.get(k) == 0 for k in ("pulse.failing", "route.errors", "route.unrouted", "drc.errors", "drc.critical"))):
        message = "The baseline already meets routed setup, hold and pulse-width requirements."
        if limit is not None:
            message += f" All monitored resources are within the {limit}% budget."
        save("already_closed", message)
        return AutoResult(analysis, out, "already_closed", message)
    proposals = [(m.plan,m) for m in moves]
    if analysis.session.stage == "routed" and setup and setup.worst_slack_ns is not None and setup.worst_slack_ns < 0:
        proposals.extend((p,None) for p in choices(analysis)
                         if not any(p.scope == m.plan.scope and p.source_candidates[0].file == m.target.file for m in moves))
    for index, (plan,move) in enumerate(proposals, 1):
        if cancel.is_set():
            raise Cancelled("Automatic fix run cancelled.")
        if index > 3:
            break
        directory = out/f"candidate-{index}"
        target = layout.clone(directory/"project")
        rel = Path(plan.source_candidates[0].file).relative_to(project.parent)
        if rel not in layout.files:
            raise ValueError("The recommendation does not target an authored project input.")
        attempt = {"rule":plan.id, "title":plan.title, "file":str(rel), "project":str(target.relative_to(out))}
        if move:
            attempt["resource_move"] = move.description
        state["attempts"].append(attempt)
        save("validating", plan.title)
        try:
            edit = validate_edit(layout, analysis, plan, project, target, rel, directory, vivado, cancel, log, move=move)
            (directory / "change.patch").write_text(edit.patch)
            save("routing_candidate", f"Routing {plan.scope} with the baseline recipe.")
            if limit is not None:
                collect_ownership(layout, directory)
            route(target,directory,vivado,request.paths,cancel,log)
            after_result = collect_route(target,directory,layout,request.paths)
            if edit.ip_module:
                edit.logs["validation/dsp-ownership.txt"] = auto_ip.routed_dsps(directory, vivado, edit.ip_module, cancel, log)
            budget_check = None
            if limit is not None:
                receipt, measured, budget_check = balance.record_budget(
                    directory, state["resource_budget"], move, pools, ownership, after_result)
                attempt["resources_after"] = measured
                edit.logs["validation/resource-budget.json"] = receipt
            after = record(after_result, layout, target, directory, "Candidate", edit.scope, edit.evidence, edit.logs)
            if budget_check:
                after = after.model_copy(update={"checks": [*after.checks, budget_check]})
            advisories = {}
            warning_check = None
            if edit.ip_module or limit is not None:
                warning_check, advisories = auto_ip.warning_check(before, after)
                attempt["drc_warning_review"] = {"status": warning_check.status, "detail": warning_check.evidence}
                if advisories or edit.ip_module:
                    attempt["dsp_pipelining_warnings"] = advisories
                after = after.model_copy(update={"checks": [*after.checks, warning_check]})
            comparison = edit.compare_runs(before, after)
            export_comparison(comparison,directory/"comparison")
            state["comparison"] = str((directory / "comparison").relative_to(out))
            attempt["comparison"] = state["comparison"]
            attempt["lab_acceptance"] = comparison.acceptance
            attempt["margin_reductions"] = {m.key: [m.before, m.after] for m in comparison.metrics
                if m.status == "regressed" and m.key in {"setup.worst_slack_ns", "hold.worst_slack_ns", "pulse.wns"}}
            failures = closure(comparison, advisories, capacity_goal=move is not None)
            if budget_check and budget_check.status == "failed":
                failures.append(budget_check.evidence)
            if warning_check and warning_check.status == "failed":
                failures.append(warning_check.evidence)
            if not _check_constraints(after_result):
                failures.append("Unresolved timing constraints")
            if failures:
                raise ValueError("Closure checks require review: " + ", ".join(failures))
            if cancel.is_set():
                raise Cancelled("Automatic fix run cancelled before publication.")
            if any(digest(target.parent / name) != hashes["after"] for name, hashes in edit.hashes.items()):
                raise ValueError("Candidate inputs changed after verification.")
            attempt.update(status="verified", changed_files=edit.hashes)
            state.update(working_project=str(target.relative_to(out)),
                         old_sha256=edit.hashes[str(rel)]["before"], new_sha256=edit.hashes[str(rel)]["after"])
            if request.apply_to_source:
                save("publishing", f"Publishing verified {rel} to the selected project.")
                try:
                    edit.publish(original, rel, out / "original")
                except (OSError, ValueError) as error:
                    message = f"The verified project copy is ready. Source publication stopped: {error}"
                    save("verified_copy", message)
                    return AutoResult(after_result, out, "verified_copy", message)
            message = (f"Applied and routed in {target}. " +
                       (f"Updated {original.xpr.name}. Original files in {out/'original'}." if request.apply_to_source else ""))
            save("applied",message)
            return AutoResult(after_result,out,"applied",message)
        except (OSError, ValueError, ProcessFailure) as error:
            attempt.update(status="review",reason=str(error))
            save("review", str(error))
    message = ("No supported source or Xilinx IP edit matched the captured failure." if not state["attempts"]
               else "Candidate evidence retained for review. " + state["attempts"][-1]["reason"])
    if pressured and not state["attempts"]:
        message = f"Resource budget exceeded for {', '.join(balance.LABELS[k] for k,p in pools.items() if p.exceeds(limit))}. " + (" ".join(skipped) if skipped else "No supported, attributable remap was found.")
    save("review",message)
    return AutoResult(analysis,out,"review",message)
