"""Portable, escaped offline report."""
from html import escape
from pathlib import Path

from ..analysis.engine import Analysis, recommendation
from ..analysis.fixes import render
from ..rules.library import RULES
from ..timing.io import atomic_text
from ..timing.coverage import coverage_note
from ..vivado.reports import detail_blocks
from ..syntax import file_syntax
from .syntax import STYLE, code_block


def value(number, suffix="") -> str:
    if number is None:
        return "Unavailable"
    if isinstance(number, float):
        return f"{number:.3f}{suffix}"
    return f"{number}{suffix}"


def row(values) -> str:
    return "<tr>" + "".join(f"<td>{escape(str(v))}</td>" for v in values) + "</tr>"


def table(headers, rows) -> str:
    columns = "".join(f"<th scope='col'>{escape(h)}</th>" for h in headers)
    return f"<table><thead><tr>{columns}</tr></thead><tbody>{''.join(row(r) for r in rows)}</tbody></table>"


def write_html(path: Path, result: Analysis) -> None:
    s = result.session
    display_name = s.top or s.name
    metrics = ((kind.title(), value(data.worst_slack_ns, " ns"), value(data.total_negative_slack_ns, " ns"),
                value(data.failing_endpoints), value(data.total_endpoints)) for kind, data in s.summary.items())
    clocks = ((c.name, value(c.period_ns, " ns"), ", ".join(str(edge) for edge in c.waveform_ns)) for c in s.clocks)
    paths = ((p.id, p.analysis, value(p.startpoint), value(p.endpoint), value(p.slack_ns, " ns"),
              value(p.logic_ns, " ns"), value(p.routing_ns, " ns"), value(p.levels),
              f"{value(p.start_clock)} → {value(p.end_clock)}",
              value(result.paths[p.id].module), result.paths[p.id].confidence.label,
              result.graph.delay_class(p)) for p in s.paths)
    issues = []
    from urllib.parse import quote
    project_plans = ''.join(f'<details><summary>{escape(plan.title)}</summary><pre>{escape(render(plan))}</pre></details>' for plan in result.project_plans)
    groups = {g.id: g for g in result.groups}
    for item in result.investigations:
        label = (f"{item.id} · {item.title} · {len(item.path_ids)} paths · "
                 f"worst slack {value(item.worst_slack_ns, ' ns')}")
        links = ' · '.join(f'<a href="#path-{quote(i, safe="")}">{escape(i)}</a>' for i in item.path_ids)
        candidates = ''.join(f'<details><summary>{escape(plan.title)}</summary><pre>{escape(render(plan))}</pre></details>' for plan in item.plans)
        details = '\n\n'.join(recommendation(groups[g]) for g in item.group_ids)
        issues.append(f'<details id="{item.id}"><summary>{escape(label)}</summary><p>Measured paths: {links}</p>'
                      f'<p>{escape(", ".join(item.rules))} are symptoms of this same captured path set.</p>{candidates}'
                      f'<details><summary>All diagnostic evidence</summary><pre>{escape(details)}</pre></details></details>')
    arc_sections = []
    raw_paths = {}
    for kind in ("setup", "hold"):
        raw_paths.update(detail_blocks(s.reports.get(f"{kind}-paths.rpt", "")))
    findings_by_path = {}
    for finding in result.findings:
        findings_by_path.setdefault(finding.path_id, []).append(finding)
    for p in s.paths:
        details = table(("Source pin", "Sink pin", "Resource", "Kind", "Delay"),
                        ((arc.source, arc.sink, arc.resource, arc.kind, value(arc.delay_ns, " ns")) for arc in p.arcs))
        source = result.paths[p.id]
        evidence = "\n".join(f"{f.rule}  {text}" for f in findings_by_path.get(p.id, ()) for text in f.evidence)
        attribution = f"{source.confidence.label} · {source.reason}"
        if source.file:
            attribution += f"  {source.file}" + (f":{source.first}" if source.first else "")
        arc_sections.append(f'<details id="path-{quote(p.id, safe="")}"><summary>{escape(p.id)}</summary><p>{escape(attribution)}</p>'
                            f"<p>{escape(coverage_note([result.coverage[p.id]]))}</p>"
                            f"<pre>{escape(evidence)}</pre>{details}"
                            f"<details><summary>Raw Vivado path</summary>{code_block(raw_paths.get(p.id, 'Unavailable'), 'report')}</details></details>")
    warnings = "".join(f"<li>{escape(w)}</li>" for w in result.warnings)
    raw_reports = "".join(f"<details><summary>{escape(name)}</summary>{code_block(content, file_syntax(name))}</details>"
                          for name, content in sorted(s.reports.items()) if not name.endswith("-paths.rpt"))
    html = f"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>TimingLens · {escape(display_name)}</title>
<style>
:root {{color-scheme: light dark; font: 15px system-ui;}}
body {{max-width: 95rem; margin: 2rem auto; padding: 0 1rem;}}
table {{width: 100%; border-collapse: collapse; font-size: .88rem;}}
th,td {{border-bottom: 1px solid #8887; padding: .5rem; text-align: left; overflow-wrap: anywhere;}}
pre {{white-space: pre-wrap; overflow-wrap: anywhere;}}
details {{margin: .75rem 0; padding: .6rem; border: 1px solid #8887; border-radius: .35rem;}}
summary {{cursor: pointer;}}
{STYLE}
</style>
<body><h1>{escape(display_name)} · TimingLens</h1>
<p>Vivado {escape(value(s.vivado))} · {escape(value(s.part))} · {escape(s.stage)} ·
{escape(value(s.timestamp))}</p>
<p>{result.failing_paths} collected failing paths out of {len(s.paths)} collected ·
{len(result.findings)} diagnostic findings · {len(result.groups)} bottleneck groups</p>
<h2>Design timing</h2>
{table(("Analysis", "Worst slack", "Total negative slack", "Failing endpoints", "Total endpoints"), metrics) if s.summary else '<p>Unavailable</p>'}
<p>{escape(result.coverage_note)}</p>
{f'<h2>Evidence notes</h2><ul>{warnings}</ul>' if warnings else ''}
<h2>Clocks</h2>{table(("Name", "Period", "Waveform (ns)"), clocks) if s.clocks else '<p>Unavailable</p>'}
<h2>Investigations</h2>{''.join(issues) or '<p>No supported findings in this capture. Missing reports do not establish a clean design.</p>'}
<h2>Project and constraint review</h2>{project_plans or '<p>No supported project-specific candidates from the supplied files.</p>'}
<h2>Collected timing paths</h2>
{table(("Path", "Analysis", "Startpoint", "Endpoint", "Slack", "Logic", "Route", "Levels", "Clock pair", "Module", "Source", "Delay class"), paths)}
<h2>Path details</h2>{''.join(arc_sections)}
<h2>Vivado reports</h2>{raw_reports or '<p>Unavailable</p>'}
</body></html>
"""
    atomic_text(path, html)
