"""Combine identical path sets or paths independently mapped to one exact source fix."""
from dataclasses import dataclass, replace
from math import log2

from .fixes import Evidence, FixPlan


@dataclass(frozen=True)
class Investigation:
    id: str
    group_ids: tuple[str, ...]
    rules: tuple[str, ...]
    path_ids: tuple[str, ...]
    worst_slack_ns: float | None
    complete_paths: int
    title: str
    plans: tuple[FixPlan, ...]
    ranking_basis: str = 'Actionable candidates first, then measured severity × endpoint breadth, detail coverage and source specificity. This is an investigation order, not a predicted gain.'


def _pipeline_key(plan):
    edit = plan.changes[0]
    return plan.scope, edit.location.file, edit.source_sha256, edit.start_byte, edit.end_byte


def _shared_pipeline(result, plan, ids):
    matches = [result.arithmetic_pipelines[key] for key in ids]
    dsps = tuple(sorted({p.evidence_links[1].objects[0] for p in matches}))
    instances = {result.cells[name].instance for name in dsps}
    statement = (f"The same source edit matches {len(ids)} distinct captured failing paths "
                 f"across {len(instances)} hardware instance{'s' if len(instances) != 1 else ''} of {plan.scope}.")
    link = Evidence("pipeline:shared-source", "measured", statement, ids, dsps)
    return replace(plan, evidence=(statement, *plan.evidence), evidence_links=(*plan.evidence_links, link))


def investigations(result):
    buckets = {}
    paths = {p.id: p for p in result.session.paths}
    for group in result.groups:
        key = group.path_ids or (group.id,)
        first = next((p for p in result.fix_plans[group.id] if p.id == "rtl.redistribute_arithmetic"), None)
        if first:
            identity = _pipeline_key(first)
            if all((p := result.arithmetic_pipelines.get(i)) and _pipeline_key(p) == identity for i in group.path_ids):
                key = ("shared_pipeline", identity)
        elif group.path_ids and any(p.id == "bd.multiplier_dsp" for p in result.fix_plans[group.id]):
            configs = [result.bd_multipliers.get(i) for i in group.path_ids]
            if all(configs):
                identities = {(p.scope, p.source_candidates[0].file) for p in configs}
                if len(identities) == 1:
                    key = ("shared_block", identities.pop())
        buckets.setdefault(key, []).append(group)
    rows = []
    for bucket, groups in buckets.items():
        groups.sort(key=lambda g: g.worst_slack_ns if g.worst_slack_ns is not None else float("inf"))
        ids = tuple(sorted({i for g in groups for i in g.path_ids}, key=lambda i: (paths[i].slack_ns if paths[i].slack_ns is not None else float('inf'), i)))
        plans = {}
        for group in groups:
            for plan in result.fix_plans[group.id]:
                key = plan.id, plan.scope, plan.commands, plan.source_candidates
                plans.setdefault(key, plan)
        if bucket[0] == "shared_pipeline" and len(ids) > 1:
            for key, plan in list(plans.items()):
                if plan.id == "rtl.redistribute_arithmetic":
                    plans[key] = _shared_pipeline(result, result.arithmetic_pipelines[ids[0]], ids)
        if bucket[0] == "shared_block" and len(ids) > 1:
            for key, plan in list(plans.items()):
                if plan.id == "bd.multiplier_dsp":
                    statement = f"The same IP configuration in {plan.scope} matches {len(ids)} captured failing paths."
                    evidence = Evidence("block-design:shared-config", "measured", statement, ids)
                    plans[key] = replace(plan, evidence=(statement, *plan.evidence),
                                         evidence_links=(*plan.evidence_links, evidence))
        ordered = tuple(sorted(plans.values(), key=lambda p: (
            0 if p.id in {'constraints.first', 'evidence.first'} else
            1 if p.changes or p.id == "bd.multiplier_dsp" else 2 if p.id == 'rtl.compare_enable' else
            3 if p.kind == 'vivado_experiment' else 4, p.id)))
        title = (ordered[0].title if ordered else result.rule_title(groups[0].rule))
        worst = min((g.worst_slack_ns for g in groups if g.worst_slack_ns is not None), default=None)
        rows.append(Investigation('', tuple(g.id for g in groups), tuple(sorted({g.rule for g in groups})), ids,
                                  worst, sum(result.coverage[i].complete for i in ids), title, ordered))
    def priority(row):
        endpoints = len({paths[i].endpoint for i in row.path_ids})
        severity = abs(min(row.worst_slack_ns or 0, 0)) * (1 + log2(max(1, endpoints)))
        actionable = any(p.kind in {'rtl_hypothesis','vivado_experiment'} or p.id == 'bd.multiplier_dsp' for p in row.plans)
        return (-int(actionable), -severity, -row.complete_paths / max(1, len(row.path_ids)),
                -int(any(p.changes for p in row.plans)), row.path_ids, row.group_ids)
    return tuple(replace(row, id=f'I{i:03d}') for i, row in enumerate(sorted(rows, key=priority), 1))
