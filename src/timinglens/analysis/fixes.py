"""Evidence-scoped fix candidates. These are experiments, never automatic edits."""
from __future__ import annotations

from dataclasses import dataclass
import re

from ..rules.library import _arithmetic

OPT_PLACE = "https://docs.amd.com/r/2024.2-English/ug904-vivado-implementation/Directives-Used-by-opt_design-and-place_design-in-Implementation-Strategies"
PHYS_ROUTE = "https://docs.amd.com/r/2024.2-English/ug904-vivado-implementation/Directives-Used-by-phys_opt_design-and-route_design-in-Implementation-Strategies"
PHYS = "https://docs.amd.com/r/2024.2-English/ug835-vivado-tcl-commands/phys_opt_design"


@dataclass(frozen=True)
class Location:
    file: str
    first: int
    last: int
    text: str


@dataclass(frozen=True)
class Evidence:
    id: str
    level: str  # measured, syntax, elaborated, inferred, needs_intent, unsupported
    statement: str
    path_ids: tuple[str, ...] = ()
    objects: tuple[str, ...] = ()
    location: Location | None = None


@dataclass(frozen=True)
class ChangePreview:
    location: Location
    source_sha256: str
    start_byte: int
    end_byte: int
    original: str
    proposed: str
    status: str  # review_diff or design_hypothesis; never auto-approved
    unified_diff: str = ""
    conditions: tuple[str, ...] = ()
    preserved: tuple[str, ...] = ()


@dataclass(frozen=True)
class FixPlan:
    id: str
    title: str
    kind: str
    scope: str
    evidence: tuple[str, ...]
    reasoning: str
    action: str
    commands: tuple[str, ...] = ()
    prerequisites: tuple[str, ...] = ()
    checks: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    source_candidates: tuple[Location, ...] = ()
    references: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()
    rule_version: str = "1"
    evidence_links: tuple[Evidence, ...] = ()
    applicability: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    changes: tuple[ChangePreview, ...] = ()


CHECKS = (
    "Compare routed setup WNS/TNS and failing endpoints, hold, pulse width, DRC, routing completion, and LUT/FF/BRAM/DSP usage under unchanged clocks and exceptions.",
    "Keep the original checkpoint. Save experiment outputs to a fresh directory; accept only measured improvement without new failures.",
)
REPORTS = (
    "report_timing_summary -delay_type min_max -report_unconstrained",
    "report_route_status", "report_drc", "report_utilization",
)


def dfx_scope(result) -> tuple[str, ...]:
    native = tuple(sorted(c.name for c in result.session.cells.values()
                          if c.properties.get("HD.RECONFIGURABLE", "").lower() in {"1", "true"}))
    if native:
        return native
    # Older captures lack HD.RECONFIGURABLE. The actual report table can still
    # establish DFX, but does not establish the RP's hierarchical cell name.
    if any("Partition" in text and re.search(r"\breconfigurable\s", text)
           for key, text in result.session.reports.items() if key.endswith("-paths.rpt")):
        return ("RP instance unavailable in this capture",)
    return ()


def _strategy(result, path, identifier, title, commands, evidence, reason, *, postplace=False):
    partitions = dfx_scope(result)
    scope = ("DFX: " + ", ".join(partitions)) if partitions else "Design implementation"
    start = ("Use a copy of the current placed/routed checkpoint."
             if postplace else "Start a fresh implementation from a synthesized, unplaced checkpoint; do not run place_design directly on the routed result.")
    prerequisites = [start, "Recipe catalog verified for Vivado 2024.2, 7 series / UltraScale legacy implementation flow."]
    checks = list(CHECKS)
    if partitions:
        prerequisites.append("Preserve the accepted locked static design, partition pins and isolation. For re-placement, load the intended synthesized RM into the established locked-static DFX flow before these commands.")
        checks.append("Run full pr_verify against the accepted configuration before producing compatible partial images. Do not unlock static logic or move isolation across the partition boundary.")
    limitations = ["This snapshot contains no experiment history. Skip any recipe already tried without benefit on these exact inputs; expected gain is not predicted."]
    if any(result.session.cells[n].properties.get("DONT_TOUCH", "").lower() in {"1", "true"} for n in path.cells):
        limitations.append("The measured path contains DONT_TOUCH cells; legal movement/replication may be limited. Do not remove preservation constraints as a timing shortcut.")
    declared = [f'{f.file}:{f.line} declares {f.subject} -directive {f.values[0]} (project text, not proof of a completed run).'
                for f in result.project_context.facts if f.kind == 'build_directive']
    return FixPlan(identifier, title, "vivado_experiment", scope, (*evidence, *declared), reason,
                   "Compare this single experiment against the same baseline; retain the reports and checkpoint.",
                   (*commands, *REPORTS), tuple(prerequisites), tuple(checks), tuple(limitations),
                   references=(OPT_PLACE, PHYS_ROUTE, PHYS),
                   next_steps=(start, f'Try {title} as a separate experiment with the supplied Tcl.',
                               'Compare routed timing, resource usage and functional checks against the unchanged baseline.'),
                   evidence_links=tuple(Evidence(f'{path.id}:{identifier}:e{i}', 'measured', e, (path.id,))
                                        for i, e in enumerate(evidence)) +
                                  tuple(Evidence(f'{identifier}:script:{i}', 'syntax', e) for i, e in enumerate(declared)),
                   applicability=(f'Vivado {result.session.vivado}; device {result.session.part}; stage {result.session.stage}.',
                                  'Complete measured connectivity and delay coverage on the selected failing path.', *prerequisites),
                   unknowns=tuple(limitations))


def _enable_candidate(result, path, carry) -> FixPlan | None:
    """Native CE topology + a guarded update to a uniquely named RTL register.

    Surviving register names are a hypothesis bridge, not a formal RTL/netlist
    equivalence proof. Never infer this from a carry primitive's source tag alone.
    """
    from .rtl_fixes import compare_enable
    return compare_enable(result, path, carry)


def internal_clock_path(session, path):
    clock = path.start_clock
    if not (clock and path.end_clock == clock and path.requirement_ns and path.requirement_ns > 0
            and any(c.name == clock and c.period_ns and c.period_ns > 0 for c in session.clocks)):
        return False
    for point in (path.startpoint, path.endpoint):
        pin = session.pins.get(point)
        cell = session.cells.get(pin.cell) if pin else None
        if not cell or pin.port or not cell.sequential:
            return False
    return True


def suggest(result, group) -> tuple[FixPlan, ...]:
    session = result.session
    selected = [p for p in session.paths if p.id in group.path_ids]
    constraint_findings = [f for f in result.findings if f.rule == "TL-G"]
    ports = result.forwarded_clock_outputs if constraint_findings else ()
    scoped = bool(ports) and all(f.anchors == ("check_timing/no_output_delay",) for f in constraint_findings)
    if scoped and not selected:
        return (FixPlan("constraints.first", f"Review forwarded clock output {', '.join(ports)}",
                        "constraint_review", "Output interface",
                        ("Vivado classifies only the forwarded clock output as LOW. The verbose report lists zero data outputs missing a delay.",),
                        "The capture identifies a generated clock on the named output and a valid master clock.",
                        "Confirm the receiver sampling edge and the min/max delays on the accompanying data outputs.",
                        commands=("check_timing -verbose", "report_clocks")),)
    if constraint_findings and not (scoped and all(internal_clock_path(session, p) for p in selected)):
        reason = "Vivado reported clock/constraint coverage findings in this session."
        return (FixPlan("constraints.first", "Resolve timing coverage before strategy selection", "constraint_review", "Clock/constraint model",
                        (reason,),
                        "Strategy rankings depend on the validity of the timed paths.",
                        "Inspect check_timing and clock relationships first. Do not hide the path with a false-path or multicycle exception without an independent functional justification.",
                        commands=("check_timing -verbose", "report_clock_interaction")),)
    if not selected:
        return ()
    path = min(selected, key=lambda p: p.slack_ns if p.slack_ns is not None else float("inf"))
    if not result.coverage[path.id].complete:
        # Encrypted IP can hide pin delays while preserving a fully traced,
        # single-instance path and its measured total logic delay.
        if candidate := result.bd_multipliers.get(path.id):
            return (candidate,)
        return (FixPlan("evidence.first", "Recover detailed path evidence before selecting a fix", "evidence_review", path.id,
                        (result.coverage_note,), "Missing branch delays can hide the actual bottleneck.",
                        "Inspect the raw path and capture missing native connectivity/delay information. Do not rank a specific implementation recipe from incomplete detail."),)
    plans = []
    carry, _, _ = _arithmetic(path, session)
    if candidate := result.arithmetic_pipelines.get(path.id):
        plans.append(candidate)
    if candidate := result.bd_multipliers.get(path.id):
        plans.append(candidate)
    if candidate := _enable_candidate(result, path, carry):
        plans.append(candidate)
    compatible = session.vivado == "2024.2" and bool(re.match(r"(?:xc7|xa7|xq7|xcku|xcvu|xczu|xazu)", session.part or ""))
    if not compatible:
        plans.append(FixPlan("release.review", "Check strategy support for this Vivado release/device", "evidence_review", session.part or "Unknown device",
                             (f"Captured Vivado release: {session.vivado or 'unknown'}.",),
                             "The command catalog is verified for Vivado 2024.2 legacy 7 series / UltraScale flows.",
                             "Use installed command help and the release's strategy table before applying these recipes. No device-specific Tcl is emitted for an unverified flow.", references=(OPT_PLACE, PHYS_ROUTE)))
        return tuple(plans)
    if path.analysis == "hold":
        if session.stage in {"placed", "routed"}:
            plans.append(_strategy(result, path, "vivado.hold", "ExploreWithHoldFix", ("phys_opt_design -directive ExploreWithHoldFix",),
                                   (f"Measured hold slack {path.slack_ns:.3f} ns at {path.endpoint}.",),
                                   "Add delay only where the implementation hold optimizer finds a legal repair; a faster setup strategy does not repair a short hold path.", postplace=True))
        else:
            plans.append(FixPlan("hold.route_first", "Evaluate hold after placement and routing", "evidence_review", session.stage,
                                 (f"Hold slack {path.slack_ns} ns is from {session.stage} data.",),
                                 "Synthesis routing estimates do not establish a physical hold failure.", "Complete implementation and inspect routed min-delay timing before prescribing hold buffering."))
        return tuple(plans)
    if session.stage not in {"synthesized", "placed", "routed"}:
        return tuple(plans)
    route = path.routing_ns or 0
    delay = path.datapath_ns or 0
    measured = sorted((a for a in path.arcs if a.kind == "net" and a.delay_ns is not None), key=lambda a: -a.delay_ns)
    evidence = [f"{path.id}: setup slack {path.slack_ns:.3f} ns; routing {route:.3f}/{delay:.3f} ns ({route/delay:.1%})." if delay else f"{path.id}: setup slack {path.slack_ns} ns."]
    evidence += [f"{a.resource} → {a.sink}: {a.delay_ns:.3f} ns" for a in measured[:2]]
    if group.rule == "TL-C" and session.stage in {"placed", "routed"}:
        plans.append(_strategy(result, path, "vivado.fanout", "AggressiveFanoutOpt", ("phys_opt_design -directive AggressiveFanoutOpt",),
                               evidence, "A measured high-load branch, not fanout count alone, supports trying driver replication/local redistribution.", postplace=True))
    if group.rule == "TL-D":
        if session.stage == "routed":
            plans.append(_strategy(result, path, "vivado.postroute", "Post-route Explore", ("phys_opt_design -directive Explore",),
                                   evidence, "Try a bounded repair of the current route before paying for a new placement. Reopen the baseline for each experiment.", postplace=True))
        plans.append(_strategy(result, path, "vivado.extra_timing", "Performance_ExtraTimingOpt",
                               ("opt_design", "place_design -directive ExtraTimingOpt", "phys_opt_design -directive Explore", "route_design -directive NoTimingRelaxation"),
                               evidence, "A routing-dominated setup path can benefit from a fresh timing-focused placement rather than repeatedly optimizing the same route."))
        plans.append(_strategy(result, path, "vivado.net_delay", "Performance_NetDelay_high",
                               ("opt_design", "place_design -directive ExtraNetDelay_high", "phys_opt_design -directive AggressiveExplore", "route_design -directive NoTimingRelaxation"),
                               evidence, "Use as a separate alternative when long net branches remain expensive. Routing dominance alone does not prove congestion; no congestion-spreading strategy is inferred."))
    elif group.rule in {"TL-A", "TL-B", "TL-E"}:
        if not dfx_scope(result):
            from ..experiments.priority_rewrite import recommendation
            if rewrite := recommendation(result,path):
                from ..experiments.priority_variants import sweep_plan
                plans.extend((sweep_plan(rewrite),rewrite))
        plans.append(_strategy(result, path, "vivado.remap", "Performance_ExploreWithRemap",
                               ("opt_design -directive ExploreWithRemap", "place_design -directive Explore", "phys_opt_design -directive Explore", "route_design -directive NoTimingRelaxation"),
                               (f"{path.id}: {path.levels} logic levels and {path.logic_ns} ns cell delay; rule {group.rule}.",),
                               "Try legal logic remapping before placement. A strategy cannot guarantee removal of a true serial arithmetic dependency; inspect the RTL candidate and preserve functional behavior."))
    elif group.rule == "TL-F":
        plans.append(_strategy(result, path, "vivado.block_placement", "Performance_WLBlockPlacement",
                               ("opt_design", "place_design -directive WLDrivenBlockPlacement", "phys_opt_design -directive Explore", "route_design -directive Explore"),
                               evidence, "The measured path touches a mapped block RAM boundary. Try wirelength-aware block placement; separately review whether the RAM output register is enabled and whether adding a cycle is legal. Do not assume a placement directive changes memory latency."))
    return tuple(plans)


def render(plan: FixPlan) -> str:
    lines = [plan.title, f"Type: {plan.kind} · Scope: {plan.scope}", "Measured evidence / source hypothesis"]
    lines += ["• " + e for e in plan.evidence]
    lines += ["Reasoning: " + plan.reasoning, "Action: " + plan.action]
    if plan.next_steps:
        lines += ['Next steps', *(f'{i}. {step}' for i,step in enumerate(plan.next_steps,1))]
    if plan.source_candidates:
        lines += [f"RTL candidate {s.file}:{s.first}: {s.text}" for s in plan.source_candidates]
    lines += [f"Rule: {plan.id} v{plan.rule_version}"]
    lines += [f"[{e.level}] {e.id}: {e.statement}" for e in plan.evidence_links]
    for change in plan.changes:
        lines += [f"Change preview ({change.status}) · SHA-256 {change.source_sha256}",
                  "Original: " + change.original, "Proposed: " + change.proposed,
                  *change.conditions, *change.preserved]
        if change.unified_diff:
            lines.append(change.unified_diff)
    for label, values in (("Prerequisites", plan.prerequisites), ("Vivado Tcl experiment", plan.commands),
                          ("Acceptance checks", plan.checks), ("Applicability", plan.applicability),
                          ("Unknowns", plan.unknowns), ("Limits", plan.limitations), ("AMD references", plan.references)):
        if values:
            lines += [label, *values]
    return "\n".join(lines)
