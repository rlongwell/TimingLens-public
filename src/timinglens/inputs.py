"""Assemble explicitly selected project files into one offline timing session."""
from hashlib import sha256
import json
from pathlib import Path

from .rtl.syntax import build_index
from .timing.models import Cell, Session, Source
from .vivado.decode import refresh_report_arcs
from .vivado.reports import timing_summary
from .vivado.text_import import from_reports, metadata

ALLOWED = {'.json', '.rpt', '.log', '.tcl', '.xdc', '.bd', '.sv', '.v', '.svh', '.vh', '.vhd', '.vhdl'}


def _report_hierarchy(session):
    index = build_index(session.sources)
    roots = index.modules.get(session.top or '', [])
    if len(roots) != 1:
        return session
    hierarchy = {}
    def walk(module, prefix, stack):
        if len(stack) >= 32 or module.name in stack or len(hierarchy) > 10000:return
        for name, typename in module.instances:
            modules = index.modules.get(typename, [])
            if len(modules) != 1:continue
            path = prefix + '/' + name if prefix else name
            hierarchy[path] = Cell(name=path, primitive=typename, hierarchical=True, parent=prefix or None,
                                   properties={'EVIDENCE_ORIGIN': 'RTL hierarchy inference'})
            walk(modules[0], path, (*stack, module.name))
    walk(roots[0], '', ())
    cells = dict(session.cells)
    for name, cell in list(cells.items()):
        parents = [h for h in hierarchy if name.startswith(h+'/')]
        if parents:
            parent = max(parents, key=len)
            cells[name] = cell.model_copy(update={'parent': parent})
            while parent in hierarchy:
                cells[parent] = hierarchy[parent];parent = hierarchy[parent].parent
    return session.model_copy(update={'cells':cells})


def assemble(paths: list[Path], *, top: str | None = None, base: Session | None = None) -> Session:
    if not paths and base is None:raise ValueError('Select timing reports/session and project source files.')
    sources = {}; reports = {}; warnings = []; total = 0
    for path in dict.fromkeys(p.expanduser().resolve() for p in paths):
        if path.suffix.lower() not in ALLOWED:raise ValueError(f'Unsupported project file: {path.name}')
        limit = 64_000_000 if path.suffix.lower() in {'.rpt','.log','.json','.bd'} else 4_000_000
        if path.stat().st_size > limit:raise ValueError(f'Project file exceeds capture limit: {path.name}')
        total += path.stat().st_size
        if total > 256_000_000:raise ValueError('Selected project files exceed the 256 MB total capture limit.')
        data = path.read_bytes();text = data.decode('utf-8',errors='strict')
        if path.suffix.lower() == '.json':
            document = json.loads(text)
            if isinstance(document,dict) and 'schema_version' in document and 'paths' in document and 'name' in document:
                if base is not None:raise ValueError('Select only one authoritative TimingLens session.')
                base = Session.model_validate(document);continue
        if path.suffix.lower() in {'.rpt','.log'}:
            reports[f'input-{len(reports)+1}-{path.name}'] = text
        else:
            sources[str(path)] = Source(path=str(path), file_type=path.suffix[1:].upper(), sha256=sha256(data).hexdigest(), text=text)
    report_only = base is None
    if base is None:
        base = from_reports(reports)
    else:
        for text in reports.values():
            for key, value in metadata(text).items():
                captured = getattr(base, key)
                if captured and captured != 'unknown' and captured != value:raise ValueError('Supplementary report metadata disagrees with the selected timing session.')
            for kind, total in timing_summary(text).items():
                if kind in base.summary and total != base.summary[kind]:raise ValueError('Supplementary report disagrees with the selected timing session.')
        base = refresh_report_arcs(base)
        base = base.model_copy(update={'reports':{**base.reports,**reports}})
    combined = {s.path:s for s in base.sources};changed = set()
    for path, source in sources.items():
        old = combined.get(path)
        if old and old.sha256 and old.sha256 != source.sha256:
            changed.add(path)
            warnings.append(f'{path}: selected source differs from the captured source hash; direct tags and RTL fix candidates for this file are suppressed.')
            source = source.model_copy(update={'file_type':'UNMATCHED_REVISION'})
        combined[path] = source
    cells = {k:c.model_copy(update={'source':None}) if c.source and c.source.file in changed else c for k,c in base.cells.items()}
    base = base.model_copy(update={'sources':list(combined.values()),'cells':cells,'warnings':[*base.warnings,*warnings],
                                  'top':top or base.top})
    return _report_hierarchy(base) if report_only else base
