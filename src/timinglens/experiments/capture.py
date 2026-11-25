"""Extract only recognized report measurements; missing evidence stays absent."""
from hashlib import sha256
import re

from .models import Artifact, BuildContext, Run
from ..timing.models import Session


def report_metrics(reports):
    values, evidence, warnings = {}, {}, []

    def put(key, value, source):
        if key in values and values[key] != value:
            raise ValueError(f'Conflicting {key} measurements in supplied reports.')
        values[key], evidence[key] = float(value), source

    for name, text in reports.items():
        if 'Design Timing Summary' in text:
            tail = text.split('Design Timing Summary', 1)[1]
            header = re.search(r'WNS\(ns\).*WPWS\(ns\).*TPWS Total Endpoints[^\n]*\n[^\n]*\n([^\n]+)', tail)
            if header:
                fields = header[1].split()
                if len(fields) == 12:
                    try:
                        parsed = [float(value) for value in fields[8:]]
                        for key, value in zip(('pulse.wns', 'pulse.tns', 'pulse.failing', 'pulse.total'), parsed):
                            put(key, value, name + ': Design Timing Summary (clock pulse checks)')
                    except ValueError as error:
                        if str(error).startswith('Conflicting'): raise
                        warnings.append(name + ': pulse-width summary could not be parsed.')
        if 'Design Route Status' in text:
            def count(label):
                found = re.search(r'# of '+label+r'\.+\s*:\s*(\d+)\s*:', text)
                return int(found[1]) if found else None
            total, routed, errors = count('routable nets'), count('fully routed nets'), count('nets with routing errors')
            if errors is not None: put('route.errors', errors, name)
            if total is not None and routed is not None and 0 <= routed <= total:
                put('route.unrouted', total-routed, name)
        if 'Report DRC' in text and (found := re.search(r'Checks found:\s*(\d+)', text)):
            rows = re.findall(r'^\|\s*[\w-]+\s*\|\s*(Critical Warning|Error|Warning|Advisory|Info)\s*\|[^\n]*\|\s*(\d+)\s*\|\s*$', text, re.M)
            if sum(int(n) for _, n in rows) == int(found[1]):
                for key, severity in [('drc.errors', 'Error'), ('drc.critical', 'Critical Warning'), ('drc.warnings', 'Warning')]:
                    put(key, sum(int(n) for level, n in rows if level == severity), name + ': default ruledeck report')
        if 'Utilization' in text:
            for key, labels in [('area.lut_sites', ['Slice LUTs', 'CLB LUTs']), ('area.ff', ['Register as Flip Flop']),
                                ('area.lutram', ['LUT as Memory']), ('area.bram_tiles', ['Block RAM Tile']), ('area.dsp', ['DSPs'])]:
                for label in labels:
                    match = re.search(r'^\|\s*'+re.escape(label)+r'(\*?)\s*\|\s*([\d.]+)\s*\|', text, re.M)
                    if match: put(key, float(match[2]), name + ': '+label+match[1])
    return values, evidence, warnings


def from_session(session: Session, label=None, input_sha=None):
    if len({s.path for s in session.sources}) != len(session.sources):
        raise ValueError('Source paths must be unique within a run capture.')
    if len({c.name for c in session.clocks}) != len(session.clocks):
        raise ValueError('Clock names must be unique within a run capture.')
    metrics, provenance, notes = report_metrics(session.reports)
    sources, constraints = {}, {}
    for source in session.sources:
        digest = sha256(source.text.encode()).hexdigest() if source.text is not None else source.sha256
        if source.sha256 and digest != source.sha256:
            if source.text is not None and '\ufffd' in source.text:
                notes.append(f'Unverified source snapshot: {source.path}; text contains decoding replacements and cannot reproduce the recorded byte digest.')
                digest = source.sha256
            else:
                raise ValueError(f'Source bytes disagree with their captured hash: {source.path}')
        if digest:
            (constraints if source.path.lower().endswith('.xdc') else sources)[source.path] = digest
    artifacts = [Artifact(name=name, sha256=sha256(text.encode()).hexdigest(), kind='embedded_report')
                 for name, text in sorted(session.reports.items())]
    if input_sha: artifacts.insert(0, Artifact(name='selected timing session', sha256=input_sha, kind='session'))
    dfx = True if any(c.properties.get('HD.RECONFIGURABLE', '').lower() in {'true','1'} for c in session.cells.values()) else None
    return Run(label=(label or session.top or session.name)[:200], session=session, timing=session.summary,
               metrics=metrics, metric_evidence=provenance,
               context=BuildContext(sources=sources, constraints=constraints, dfx=dfx), artifacts=artifacts,
               notes=[*notes, 'Source hashes describe captured bytes; they do not prove source/checkpoint correspondence.',
                      'A capped path list cannot establish that an unmatched endpoint was removed or is newly created.'])
