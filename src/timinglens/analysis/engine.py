"""Public, GUI-independent deterministic analysis API."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from math import log2
from functools import cached_property

from ..netlist.graph import Graph
from ..rtl.correlate import Association, Confidence, UNKNOWN, correlate
from ..rtl.syntax import SourceIndex, build_index
from ..rules.library import RULES, Finding, Thresholds, configuration_checks, diagnose
from ..timing.models import Session, TimingPath
from ..timing.coverage import path_coverage, coverage_note
from ..vivado.reports import detail_blocks


@dataclass(frozen=True)
class Bottleneck:
    id: str
    rule: str
    anchor: str
    path_ids: tuple[str, ...]
    endpoints: int
    worst_slack_ns: float | None
    score: float
    confidence: Confidence
    modules: tuple[str, ...]
    findings: tuple[Finding, ...]


@dataclass
class Analysis:
    session: Session
    graph: Graph
    source_index: SourceIndex
    cells: dict[str, Association]
    paths: dict[str, Association]
    findings: tuple[Finding, ...]
    groups: tuple[Bottleneck, ...]
    thresholds: Thresholds

    @property
    def failing_paths(self) -> int:
        return sum(path.slack_ns is not None and path.slack_ns < 0 for path in self.session.paths)

    @cached_property
    def coverage(self):
        return {path.id: path_coverage(path) for path in self.session.paths}

    @property
    def coverage_note(self) -> str:
        return coverage_note(list(self.coverage.values()))

    @cached_property
    def forwarded_clock_outputs(self):
        from ..vivado.reports import forwarded_clock_outputs
        return forwarded_clock_outputs(self.session)

    @cached_property
    def bd_multipliers(self):
        from .bd_multiplier import candidates
        return candidates(self)

    @cached_property
    def arithmetic_pipelines(self):
        from .arithmetic_pipeline import candidates
        return candidates(self)

    @cached_property
    def fix_plans(self):
        from .fixes import suggest, Evidence
        plans = {}
        for group in self.groups:
            plans[group.id] = tuple(
                plan if plan.evidence_links else replace(plan,
                    evidence_links=tuple(Evidence(f'{group.id}:e{i}', 'inferred', e, group.path_ids,
                                                  (group.anchor,)) for i, e in enumerate(plan.evidence)),
                    applicability=plan.prerequisites,
                    unknowns=plan.limitations)
                for plan in suggest(self, group))
        return plans

    @cached_property
    def semantic_index(self):
        from ..rtl.bounded import BoundedSemanticIndex
        return BoundedSemanticIndex(self)

    @cached_property
    def investigations(self):
        from .investigations import investigations
        return investigations(self)

    @staticmethod
    def rule_title(rule):
        return RULES[rule].title

    @cached_property
    def project_context(self):
        from ..project import context
        return context(self.session.sources)

    @cached_property
    def project_plans(self):
        from .project_fixes import suggest_project
        from .fixes import Evidence
        return tuple(replace(plan, evidence_links=plan.evidence_links or tuple(
            Evidence(f'{plan.id}:source:{i}', 'syntax', location.text, location=location)
            for i, location in enumerate(plan.source_candidates)),
            applicability=plan.applicability or plan.prerequisites,
            unknowns=plan.unknowns or plan.limitations) for plan in suggest_project(self))

    @property
    def warnings(self) -> tuple[str, ...]:
        incomplete = [key for key, c in self.coverage.items() if not c.complete]
        notes = []
        if incomplete:
            notes.append(f"Detailed timing evidence is incomplete on {len(incomplete)} paths "
                         f"({', '.join(incomplete[:5])}{', …' if len(incomplete) > 5 else ''}). "
                         "Missing delays are unknown, not zero. Branch rankings may omit the slowest connection; inspect raw Vivado reports.")
            blocks = {}
            for kind in ("setup", "hold"):
                blocks.update(detail_blocks(self.session.reports.get(f"{kind}-paths.rpt", "")))
            hidden = sum("<hidden>" in blocks.get(key, "") for key in incomplete)
            if hidden:
                notes.append(f"Vivado hides resource names in {hidden} incomplete paths. "
                             "Those unnamed report rows cannot be safely assigned to individual hardware arcs.")
        return tuple((*notes, *self.session.warnings, *self.source_index.warnings, *self.project_context.warnings))


def _path_source(path: TimingPath, graph: Graph, links: dict[str, Association]) -> Association:
    relevant = graph.logic_cells(path) or tuple(path.cells)
    # Prefer fabric on internal paths over pad buffers with broad top-level attribution.
    fabric = [name for name in relevant if graph.session.cells[name].primitive not in {"IBUF", "OBUF", "IOBUF"}]
    names = fabric or relevant
    if not names:
        return UNKNOWN
    votes = Counter((links[name].module, links[name].instance) for name in names if links[name].module)
    best = max((links[name] for name in names), key=lambda a: (
        votes[a.module, a.instance], a.confidence, a.first is not None
    ))
    if not best.module:
        return UNKNOWN
    owners = sorted({links[name].module for name in names if links[name].module})
    return Association(min(best.confidence, Confidence.STRONG),
                       f"Module-level path association across {', '.join(owners)}. "
                       "No single RTL line represents this path; inspect individual cell source tags and connectivity.",
                       best.instance, best.module, best.file, module_line=best.module_line)


def cluster(findings: list[Finding], paths: dict[str, TimingPath]) -> tuple[Bottleneck, ...]:
    population: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for finding in findings:
        if finding.path_id:
            analysis = paths[finding.path_id].analysis
            for anchor in finding.anchors:
                population[finding.rule, analysis, anchor].add(finding.path_id)
    buckets: dict[tuple[str, str, str], list[Finding]] = defaultdict(list)
    for finding in findings:
        analysis = paths[finding.path_id].analysis if finding.path_id else "design"
        # An actual common resource is required, with no transitive joining through unrelated paths.
        anchor = max(finding.anchors, key=lambda key: len(population[finding.rule, analysis, key]))
        buckets[finding.rule, analysis, anchor].append(finding)
    ranked = []
    for (rule, analysis, anchor), entries in buckets.items():
        ids = tuple(sorted({entry.path_id for entry in entries if entry.path_id}))
        affected = [paths[path_id] for path_id in ids]
        endpoints = len({path.endpoint for path in affected if path.endpoint is not None})
        worst = min((p.slack_ns for p in affected if p.slack_ns is not None), default=None)
        modules = tuple(sorted({entry.module for entry in entries if entry.module}))
        confidence = min((entry.confidence for entry in entries), default=Confidence.UNKNOWN)
        portion = max(entry.portion for entry in entries)
        score = (abs(worst or 0) * (1 + log2(max(1, endpoints))) *
                 (1 + portion) * (1 + int(confidence) * .1))
        ranked.append(Bottleneck("", rule, anchor, ids, endpoints, worst, score,
                                 confidence, modules, tuple(entries)))
    ranked.sort(key=lambda g: (-g.score, g.rule, g.anchor, g.path_ids))
    return tuple(Bottleneck(f"G{i:03d}", g.rule, g.anchor, g.path_ids, g.endpoints,
                            g.worst_slack_ns, g.score, g.confidence, g.modules, g.findings)
                 for i, g in enumerate(ranked, 1))


def analyze(session: Session, thresholds: Thresholds | None = None, *,
            trust_manifest_paths: bool = False) -> Analysis:
    cfg = thresholds or Thresholds.model_validate(session.rule_thresholds)
    graph = Graph(session)
    source_index = build_index(session.sources, trust_manifest_paths)
    cells = {name: correlate(cell, session, source_index) for name, cell in session.cells.items()}
    paths = {path.id: _path_source(path, graph, cells) for path in session.paths}
    findings = configuration_checks(session)
    for path in session.paths:
        findings.extend(diagnose(path, graph, cells, paths[path.id], cfg))
    return Analysis(session, graph, source_index, cells, paths, tuple(findings),
                    cluster(findings, {path.id: path for path in session.paths}), cfg)


def recommendation(group: Bottleneck, plans=()) -> str:
    rule = RULES[group.rule]
    lines = [rule.title, rule.description, f"Hardware or report evidence: {group.anchor}",
             f"Source correlation: {group.confidence.label}", "", "Measured evidence"]
    distinct = dict.fromkeys(evidence for finding in group.findings for evidence in finding.evidence)
    lines.extend(f"• {evidence}" for evidence in list(distinct)[:30])
    if len(distinct) > 30:
        lines.append(f"• {len(distinct) - 30} more evidence entries in the affected paths.")
    lines.extend(["", "Corrective action", rule.action, "", "Why it may help", rule.why,
                  "", "Tradeoffs", rule.tradeoffs, "", "Verification", rule.verify])
    if plans:
        from .fixes import render
        lines.extend(["", "Specific fix candidates (not yet validated)"])
        lines.extend("\n" + render(plan) for plan in plans)
    return "\n".join(lines)
