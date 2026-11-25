"""Bounded, self-contained run import and portable comparison exports."""
from hashlib import sha256
from html import escape
import json
import os
from pathlib import Path
import shutil
import stat
from tempfile import TemporaryDirectory

from .capture import from_session
from .compare import Comparison, number
from .models import Run, canonical
from ..timing.models import Session

LIMIT = 64_000_000


def load_run(path: Path) -> Run:
    # Nonblocking open also rejects FIFOs/devices without hanging the UI worker.
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('Choose a regular JSON evidence file.')
        data = stream.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError('Run evidence exceeds the 64 MB limit.')
    document = json.loads(data)
    if not isinstance(document, dict):
        raise ValueError('Expected a TimingLens run or native session object.')
    if 'timinglens_run' not in document:
        return from_session(Session.model_validate_json(data), input_sha=sha256(data).hexdigest())
    if set(document) != {'timinglens_run', 'sha256', 'run'} or type(document['timinglens_run']) is not int or document['timinglens_run'] != 1:
        raise ValueError('Unsupported run record schema.')
    if sha256(canonical(document['run'])).hexdigest() != document['sha256']:
        raise ValueError('Run integrity check failed: recorded bytes have changed.')
    run = Run.model_validate_json(json.dumps(document['run']))
    # Validate embedded source bytes even for a signed-by-digest record.
    derived = from_session(run.session)
    # Older v1 records predate the distributed-RAM metric. Keep their original
    # content and fingerprint while still checking every value they recorded.
    derived_metrics = dict(derived.metrics)
    if "area.lutram" not in run.metrics and "validation/resource-budget.json" not in run.attachments:
        derived_metrics.pop("area.lutram", None)
    if "area.lut_sites" not in run.metrics and derived.metric_evidence.get("area.lut_sites","").endswith("*"):
        # Older records omitted Vivado's starred synthesis-stage LUT estimate.
        derived_metrics.pop("area.lut_sites", None)
    if any(run.metrics.get(key)!=value for key,value in derived_metrics.items()):
        raise ValueError('Run metrics disagree with their embedded native reports.')
    return run


def run_bytes(run: Run) -> bytes:
    return canonical({'timinglens_run': 1, 'sha256': run.fingerprint, 'run': run.model_dump(mode='json')}) + b'\n'


def write_run(path: Path, run: Run):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(run_bytes(run))


def render_report(result: Comparison) -> str:
    from ..export.syntax import STYLE, code_block
    from ..syntax import file_syntax
    def e(value): return escape(str(value))
    def table(headers, rows):
        return '<div class="table"><table><thead><tr>'+''.join('<th>'+e(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+e(c)+'</td>' for c in row)+'</tr>' for row in rows)+'</tbody></table></div>'
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>TimingLens · Experiment Lab</title>',
             '<style>body{font:15px system-ui;background:#191b1e;color:#e6e7e9;max-width:1440px;margin:40px auto;padding:0 28px}h1{font-size:32px}h2{margin-top:36px}p{line-height:1.6}.table{overflow:auto}table{border-collapse:collapse;width:100%}th,td{text-align:left;vertical-align:top;padding:10px;border-bottom:1px solid #45484c;overflow-wrap:anywhere}th{color:#b9c5ce}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#24272b;padding:18px}small{color:#bec1c5}a{color:#9ecbff}'+STYLE+'</style>',
             '<p>TimingLens / Experiment Lab</p><h1>'+e(result.outcome.replace('_',' ').title())+'</h1>',
             '<p>'+e(result.before.label)+' → '+e(result.after.label)+'</p><p>'+e(result.headline)+'</p>',
             '<p><strong>Acceptance: '+e(result.acceptance.replace('_',' '))+'</strong></p>',
             '<p>'+e(' '.join(result.notes))+'</p>',
             '<h2>Measured changes</h2>', table(('Metric','Baseline','Candidate','Δ candidate − baseline','Result','Evidence'),
                ((m.label+' ('+m.unit+')',number(m.before),number(m.after),number(m.delta),m.status,m.evidence) for m in result.metrics)),
             '<h2>Acceptance checks</h2>',table(('Check','Status','Scope / evidence'),((g.name,g.status,g.detail) for g in result.gates)),
             '<h2>Comparison context</h2>',table(('Context','Status','Baseline','Candidate','Meaning'),((c.name,c.status,c.before,c.after,c.detail) for c in result.context)),
             '<h2>Captured endpoint changes</h2>',table(('Check','Endpoint / clocks','Baseline ns','Candidate ns','Δ ns','Result','Matching basis'),
                ((r.analysis,r.endpoint+' / '+r.clocks,number(r.before_slack),number(r.after_slack),number(r.delta),r.status,r.basis) for r in result.endpoints)),
             '<h2 id="recorded-change">Recorded change</h2>'+ (code_block(result.after.change_diff, 'diff') if result.after.change_diff else '<p>No patch or directive diff supplied.</p>')]
    for title,run in [('Baseline',result.before),('Candidate',result.after)]:
        parts += ['<h2>'+title+' provenance</h2><p>'+e(' '.join(run.notes+run.context.notes))+'</p>',
                  '<p>Run SHA-256: '+e(run.fingerprint)+'</p><p>Checkpoint SHA-256: '+e(run.context.checkpoint_sha256 or 'Not supplied')+'</p>',
                  table(('Artifact','SHA-256','Kind','Scope'),((a.name,a.sha256,a.kind,a.note) for a in run.artifacts))]
        for name,text in run.attachments.items():
            parts.append('<details><summary>'+e(name)+'</summary>'+code_block(text, file_syntax(name))+'</details>')
    parts += ['<p><small>Rule version lab.compare.v1. Digests detect byte changes, not authenticity or build correspondence. Reopen baseline.run.json and candidate.run.json to inspect embedded paths, sources and reports offline.</small></p></html>']
    return ''.join(parts)


def export_comparison(result: Comparison, destination: Path):
    """Publish an entire new directory, never replace existing evidence."""
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError('Choose a new export directory; existing evidence is never overwritten.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.timinglens-lab-', dir=destination.parent) as temp:
        stage=Path(temp)
        write_run(stage/'baseline.run.json',result.before)
        write_run(stage/'candidate.run.json',result.after)
        (stage/'comparison.json').write_text(json.dumps(result.document(),indent=2)+'\n')
        (stage/'report.html').write_text(render_report(result),encoding='utf-8')
        # mkdir is the no-clobber reservation, including for concurrent exports.
        destination.mkdir()
        try:
            for item in stage.iterdir(): os.replace(item,destination/item.name)
        except BaseException:
            shutil.rmtree(destination)
            raise
    return destination
