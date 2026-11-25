"""Scannable recommendation, evidence, and experiment views."""
from html import escape


KINDS = {'rtl_hypothesis':'RTL candidate · validation required',
         'block_design_hypothesis':'Block design candidate · validation required',
         'vivado_experiment':'Vivado experiment · benefit not yet measured',
         'rtl_experiment':'RTL experiment · equivalence required before implementation',
         'constraint_review':'Constraint review · functional justification required',
         'evidence_review':'More evidence needed'}


def paragraph(text):
    return '<p>'+escape(text)+'</p>'


def section(title, content):
    return '<h3>'+escape(title)+'</h3>'+content if content else ''


def bullets(items):
    return '<ul>'+''.join('<li>'+escape(x)+'</li>' for x in items)+'</ul>' if items else ''


def pages(plan):
    overview = '<h2>'+escape(plan.title)+'</h2>'
    overview += paragraph(KINDS.get(plan.kind,plan.kind))
    overview += section('What to try', '<ol>'+''.join('<li>'+escape(x)+'</li>' for x in plan.next_steps)+'</ol>' if plan.next_steps else paragraph(plan.action))
    overview += section('Why this fits',paragraph(plan.reasoning))
    overview += section('Where to inspect',paragraph(plan.scope))
    for i, source in enumerate(plan.source_candidates[:3]):
        overview += '<p><a href="tl-source:'+str(i)+'">'+escape(f'{source.file}:{source.first}' + (f'–{source.last}' if source.last!=source.first else ''))+'</a></p>'
        overview += '<pre>'+escape(source.text)+'</pre>'
    if len(plan.source_candidates)>3:
        overview += paragraph(f'{len(plan.source_candidates)-3} more source locations are listed in Evidence.')
    evidence = section('Supporting evidence',bullets(plan.evidence))
    if plan.evidence_links:
        evidence = section('Evidence levels',bullets(f'[{e.level.upper()}] {e.statement}' for e in plan.evidence_links))
    evidence += section('Unknowns',bullets(plan.unknowns))
    evidence += section('What this does not establish',bullets(plan.limitations))
    evidence += section('All source locations',''.join(paragraph(f'{s.file}:{s.first}') + '<pre>' + escape(s.text) + '</pre>' for s in plan.source_candidates)) if plan.source_candidates else ''
    checks = section('Before trying this',bullets(plan.prerequisites))
    checks += section('Engineering details',paragraph(plan.action))
    if plan.commands:
        checks += section('Tcl to review', '<pre>'+escape('\n'.join(plan.commands))+'</pre>')
    checks += section('How to validate',bullets(plan.checks))
    checks += section('Applicability',bullets(plan.applicability))
    checks += paragraph(f'Rule {plan.id} · version {plan.rule_version}')
    checks += section('References',bullets(plan.references))
    preview = ''
    for i, change in enumerate(plan.changes, 1):
        preview += section(f'Alternative {i} · '+('Review diff' if change.unified_diff else 'Design hypothesis · no patch'),
                           paragraph(f'{change.location.file}:{change.location.first}'))
        preview += section('Original expression', '<pre>'+escape(change.original)+'</pre>')
        preview += section('Proposed expression', '<pre>'+escape(change.proposed)+'</pre>')
        preview += section('Required conditions', bullets(change.conditions))
        preview += section('Behavior and consequences', bullets(change.preserved))
        if change.unified_diff:
            preview += section('Unified diff · review before use', '<pre>'+escape(change.unified_diff)+'</pre>')
        preview += paragraph('Input SHA-256: '+change.source_sha256)
    if plan.changes:
        overview += paragraph('Change preview contains exact expressions and conditions. Alternatives are separate; no files have been edited.')
    return overview, evidence, checks, preview
