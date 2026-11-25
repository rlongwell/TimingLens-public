"""Portable sweep evidence, conservative ranking, and measured regression explanations."""
from dataclasses import dataclass
from hashlib import sha256
from html import escape
import json
import os
from pathlib import Path
import shutil
import stat
from typing import Literal

from pydantic import Field, model_validator

from .compare import Comparison, compare, number
from .io import load_run
from .models import Record, Run, canonical
from .recipes import RECIPES, variant_name, validate_recipes
from ..timing.io import atomic_text

Population = Literal['register_paths','design']
RULE = 'sweep.rank.v1'
POLICY = ('Comparable, complete routed results only. No summary/check regressions or newly failing captured endpoints versus the same RTL with Default first; '
          'then fewer hold failures, fewer pulse failures, fewer setup failures, better setup TNS, setup WNS, '
          'hold TNS and hold WNS. Exact metric ties share a rank. Area and runtime are reported tradeoffs, not tie breakers. '
          'Rank is review priority, never acceptance. One build per recipe does not measure repeatability.')


class Reference(Record):
    path: str
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class StrategyEvidence(Record):
    id: Literal['default','explore','extra_timing']
    status: Literal['pending','running','completed','failed','cancelled','not_run']
    records: dict[Population,Reference] = Field(default_factory=dict)
    seconds: float | None = Field(default=None,ge=0,allow_inf_nan=False)
    error: str = ''

    @model_validator(mode='after')
    def complete(self):
        if self.status=='completed' and set(self.records)!={'design','register_paths'}:
            raise ValueError('Completed strategy lacks both timing populations.')
        return self


class Sweep(Record):
    rule_version: Literal['sweep.rank.v1'] = RULE
    example: Literal['counter32','counter64','counter32_250']
    job_name: str
    status: Literal['running','completed','partial','failed','cancelled']
    error: str = ''
    baseline: dict[Population,Reference] = Field(default_factory=dict)
    strategies: list[StrategyEvidence]

    @model_validator(mode='after')
    def consistency(self):
        validate_recipes(tuple(s.id for s in self.strategies))
        if self.status=='completed' and any(s.status!='completed' for s in self.strategies):
            raise ValueError('Completed sweep contains incomplete strategies.')
        if self.status=='completed' and set(self.baseline)!={'design','register_paths'}:
            raise ValueError('Completed sweep lacks the original baseline evidence.')
        return self


@dataclass(frozen=True)
class SweepRow:
    strategy: str
    status: str
    rank: int | None
    reason: str
    run: Run | None
    seconds: float | None
    strategy_comparison: Comparison | None
    overall_comparison: Comparison | None
    explanations: tuple[str,...]


@dataclass(frozen=True)
class SweepReview:
    path: Path
    manifest: Sweep
    population: str
    baseline: Run | None
    reference: Run | None
    rows: tuple[SweepRow,...]

    def document(self):
        return {'rule_version':RULE,'population':self.population,'status':self.manifest.status,'policy':POLICY,
                'rows':[{'strategy':r.strategy,'status':r.status,'rank':r.rank,'reason':r.reason,'seconds':r.seconds,
                    'run_id':r.run.fingerprint if r.run else None,'explanations':r.explanations,
                    'strategy_comparison':r.strategy_comparison.document() if r.strategy_comparison else None,
                    'overall_comparison':r.overall_comparison.document() if r.overall_comparison else None} for r in self.rows]}


def _bytes(path,limit):
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NONBLOCK),'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):raise ValueError('Sweep evidence must be a regular file.')
        data=stream.read(limit+1)
    if len(data)>limit:raise ValueError('Sweep evidence exceeds its size limit.')
    return data


def _envelope(manifest):
    data=manifest.model_dump(mode='json')
    return {'timinglens_sweep':1,'sha256':sha256(canonical(data)).hexdigest(),'sweep':data}


def write_sweep(job,state):
    def refs(variant):
        return {population:Reference(path=f'runs/{variant}.{population}.run.json',
                    sha256=sha256((job/f'runs/{variant}.{population}.run.json').read_bytes()).hexdigest())
                for population in ('design','register_paths')}
    baseline=refs('baseline') if 'baseline_records' in state else {}
    rows=[]
    for id in state['strategies']:
        row=state['strategy_runs'][id]
        rows.append(StrategyEvidence(id=id,status=row['status'],seconds=row.get('seconds'),error=row.get('error',''),
                      records=refs(variant_name(id)) if row['status']=='completed' else {}))
    manifest=Sweep(example=state['example'],job_name=job.name,status=state['status'],error=state.get('error',''),baseline=baseline,strategies=rows)
    atomic_text(job/'sweep.json',json.dumps(_envelope(manifest),indent=2)+'\n')


def read_manifest(path):
    data=json.loads(_bytes(path,1_000_000))
    if not isinstance(data,dict) or set(data)!={'timinglens_sweep','sha256','sweep'} or type(data['timinglens_sweep']) is not int or data['timinglens_sweep']!=1:
        raise ValueError('Unsupported sweep schema.')
    if sha256(canonical(data['sweep'])).hexdigest()!=data['sha256']:raise ValueError('Sweep integrity check failed.')
    return Sweep.model_validate_json(json.dumps(data['sweep']))


def referenced_path(path,reference,variant,population):
    expected=f'runs/{variant}.{population}.run.json'
    if reference.path!=expected:raise ValueError('Unexpected run path in sweep manifest.')
    target=path.parent/expected
    if not target.resolve().is_relative_to(path.parent.resolve()):raise ValueError('Sweep run points outside its evidence directory.')
    return target


def _load_reference(path,reference,variant,population):
    target=referenced_path(path,reference,variant,population)
    if sha256(_bytes(target,64_000_000)).hexdigest()!=reference.sha256:raise ValueError('Sweep run file digest mismatch: '+reference.path)
    run=load_run(target)
    if run.population!=population:raise ValueError('Sweep timing population disagrees with the run.')
    return run


def explain(result):
    """Describe measured changes; never infer congestion or optimization causality."""
    lines=[result.headline]
    regressions=[m for m in result.metrics if m.status=='regressed']
    improvements=[m for m in result.metrics if m.status=='improved']
    if regressions and improvements:
        lines.append('Mixed result: improvements in '+', '.join(m.label for m in improvements[:3])+' do not erase the regression.')
    lines += [f'{m.label}: {number(m.before)} → {number(m.after)} {m.unit} (Δ {number(m.delta)}).' for m in regressions]
    for metric in result.metrics:
        if metric.key.endswith('.total_endpoints') and metric.status=='changed':
            lines.append(f'{metric.label}: {number(metric.before)} → {number(metric.after)} pins. Failure totals cover a changed implementation population; unmatched paths do not establish new or removed behavior.')
    if any(m.key.endswith(('worst_slack_ns','.wns')) and m.before>=0 and m.after>=0 for m in regressions):
        lines.append('The reduced nonnegative slack is lost margin; that check still passes. Regression and timing failure are separate facts.')
    endpoints=[e for e in result.endpoints if e.status in {'newly_failing','regressed'}]
    affected={m.key.split('.')[0] for m in regressions}
    endpoints.sort(key=lambda e:(e.status!='newly_failing',e.analysis not in affected,e.delta if e.delta is not None else 0.,e.endpoint))
    if endpoints:
        lines.append(f'{len(endpoints)} captured endpoint groups worsened; {sum(e.status=="newly_failing" for e in endpoints)} changed from passing to failing.')
    elif regressions:lines.append('The captured path sample does not identify matching worsened endpoints for these summary regressions.')
    before={p.id:p for p in result.before.session.paths};after={p.id:p for p in result.after.session.paths}
    for endpoint in endpoints[:6]:
        p=before.get(endpoint.before_id);q=after.get(endpoint.after_id)
        lines.append(f'{endpoint.analysis} {endpoint.endpoint}: {number(endpoint.before_slack)} → {number(endpoint.after_slack)} ns; {endpoint.before_id} → {endpoint.after_id}.')
        if p and q:
            deltas=[f'{title} Δ {number(round(getattr(q,key)-getattr(p,key),6))} ns' for key,title in
                    [('logic_ns','logic'),('routing_ns','routing'),('skew_ns','skew'),('uncertainty_ns','uncertainty')]
                    if getattr(p,key) is not None and getattr(q,key) is not None]
            if deltas:lines.append('  Measured components: '+', '.join(deltas)+'.')
            if p.startpoint!=q.startpoint:lines.append('  The worst captured launch point changed; these are different launch paths, not the same physical path moving.')
    if result.before.context.sources!=result.after.context.sources:
        if result.before.context.directives and result.before.context.directives==result.after.context.directives:
            lines.append('RTL changed under identical recorded implementation directives. This comparison measures the candidate under that shared recipe; it is not a strategy sweep.')
        else:lines.append('Source changed as well as any listed directives. This comparison cannot isolate the implementation strategy from the RTL change.')
    lines.append('Captured components may not account for the full slack change; they do not prove which optimization caused it. A single implementation per recipe cannot establish repeatability.')
    return tuple(lines)


def _rank_key(run,result):
    setup=run.timing['setup'];hold=run.timing['hold']
    return (result.outcome=='regressed',hold.failing_endpoints,run.metrics['pulse.failing'],setup.failing_endpoints,
            -setup.total_negative_slack_ns,-setup.worst_slack_ns,-hold.total_negative_slack_ns,-hold.worst_slack_ns)


def _eligibility(run,reference,result,strategy):
    if run.context.directives!=RECIPES[strategy].directives():return 'Recorded directives do not match the named recipe.'
    if run.context.sources!=reference.context.sources:return 'Candidate source differs from the Default strategy reference.'
    if result.outcome in {'inconclusive','not_tested'}:return 'Incompatible or unavailable comparison context.'
    if any(c.status in {'unknown','mismatch'} for c in result.context):return 'Build context is incomplete or incompatible.'
    for kind in ('setup','hold'):
        summary=run.timing.get(kind)
        if summary is None or any(getattr(summary,f) is None for f in ('worst_slack_ns','total_negative_slack_ns','failing_endpoints','total_endpoints')):
            return 'Missing timing measurements; missing is not zero.'
    if any(run.metrics.get(key) is None for key in ('pulse.wns','pulse.failing','route.unrouted','route.errors','drc.errors','drc.critical','drc.warnings')):
        return 'Missing pulse, routing or DRC evidence.'
    required={'Routed implementation','Routing','DRC','Embedded source byte verification','Scoped functional validation','Source/checkpoint correspondence'}
    if any(g.status!='passed' for g in result.gates if g.name in required):return 'Required implementation or validation checks did not pass.'
    return ''


def load_sweep(path,population='register_paths'):
    path=Path(path)
    if population not in {'register_paths','design'}:raise ValueError('Unknown sweep population.')
    manifest=read_manifest(path)
    baseline=_load_reference(path,manifest.baseline[population],'baseline',population) if population in manifest.baseline else None
    runs={s.id:_load_reference(path,s.records[population],variant_name(s.id),population) for s in manifest.strategies if s.status=='completed'}
    if any(run.context.design_key!=manifest.example for run in [*runs.values(),*([baseline] if baseline else [])]):
        raise ValueError('Sweep example disagrees with a run\'s declared design identity.')
    reference=runs.get('default');rows=[];keys={}
    for evidence in manifest.strategies:
        run=runs.get(evidence.id)
        result=compare(reference,run) if reference and run else None
        overall=compare(baseline,run) if baseline and run else None
        reason=('No completed Default reference.' if run and not reference else evidence.error or manifest.error or 'No completed measurements.')
        if result:
            reason=_eligibility(run,reference,result,evidence.id)
            # An incomplete Default must not lend credibility to otherwise complete candidates.
            default_problem=_eligibility(reference,reference,compare(reference,reference),'default')
            if default_problem:reason='Default reference is not rankable: '+default_problem
            if not reason:keys[evidence.id]=_rank_key(run,result)
        explanation=explain(result) if result else (reason,)
        rows.append(SweepRow(evidence.id,evidence.status,None,reason,run,evidence.seconds,result,overall,explanation))
    ordered=sorted(rows,key=lambda row:(row.strategy not in keys,keys.get(row.strategy,()),row.strategy))
    ranked=[];last=None;rank=None
    from dataclasses import replace
    for position,row in enumerate(ordered,1):
        if row.strategy in keys:
            key=keys[row.strategy]
            if key!=last:rank=position
            last=key
            row=replace(row,rank=rank,reason='Ranked by '+RULE+'; acceptance remains a separate decision.')
        ranked.append(row)
    return SweepReview(path,manifest,population,baseline,reference,tuple(ranked))


def render_sweep(reviews):
    e=lambda value:escape(str(value))
    parts=['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>TimingLens strategy sweep</title>',
           '<style>body{font:15px system-ui;line-height:1.5;background:#252525;color:#eee;max-width:1400px;margin:32px auto;padding:0 24px}table{border-collapse:collapse;width:100%}th,td{padding:10px;border-bottom:1px solid #505050;text-align:left;vertical-align:top}.table{overflow:auto}pre{white-space:pre-wrap;background:#303030;padding:16px}h2{margin-top:36px}</style>',
           '<h1>Strategy sweep · '+e(reviews[0].manifest.example)+'</h1><p>Status: '+e(reviews[0].manifest.status)+'</p><p>'+e(reviews[0].manifest.error)+'</p><p>'+e(POLICY)+'</p>']
    for review in reviews:
        parts+=['<h2>'+e(review.population)+'</h2><p>Strategy reference: factored candidate with Default. Overall reference: original RTL with Default.</p>',
                '<div class="table"><table><tr><th>Rank</th><th>Recipe</th><th>Status</th><th>Setup WNS</th><th>Setup TNS</th><th>Setup failures</th><th>Hold WNS</th><th>LUTs</th><th>Seconds</th><th>Versus Default</th><th>Overall acceptance</th></tr>']
        for row in review.rows:
            s=row.run.timing.get('setup') if row.run else None;h=row.run.timing.get('hold') if row.run else None
            values=[row.rank or 'Unranked',RECIPES[row.strategy].name,row.status,number(s.worst_slack_ns if s else None),number(s.total_negative_slack_ns if s else None),
                    number(s.failing_endpoints if s else None),number(h.worst_slack_ns if h else None),number(row.run.metrics.get('area.lut_sites') if row.run else None),number(row.seconds),
                    row.strategy_comparison.outcome if row.strategy_comparison else 'Not tested',row.overall_comparison.acceptance if row.overall_comparison else 'Not tested']
            parts.append('<tr>'+''.join('<td>'+e(v)+'</td>' for v in values)+'</tr>')
        parts.append('</table></div>')
        for row in review.rows:
            parts.append('<h3>'+e(RECIPES[row.strategy].name)+'</h3><p>'+e(row.reason)+'</p><pre>'+e('\n'.join(row.explanations))+'</pre>')
            if row.overall_comparison:parts.append('<p>Overall change: '+e(row.overall_comparison.headline)+' Acceptance: '+e(row.overall_comparison.acceptance)+'.</p>')
    return ''.join(parts)+'</html>'


def export_sweep(path,destination):
    path=Path(path);destination=Path(destination)
    reviews=[load_sweep(path,p) for p in ('register_paths','design')]
    if reviews[0].manifest!=reviews[1].manifest:raise ValueError('Sweep changed while reading; retry after the current build.')
    destination.mkdir(parents=True,exist_ok=False)
    try:
        manifest=reviews[0].manifest
        for refs in [manifest.baseline,*[s.records for s in manifest.strategies if s.status=='completed']]:
            for population,ref in refs.items():
                source=path.parent/ref.path
                # Revalidate raw bytes at copy time, including concurrent evidence changes.
                data=_bytes(source,64_000_000)
                if sha256(data).hexdigest()!=ref.sha256:raise ValueError('Sweep evidence changed during export.')
                target=destination/ref.path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        (destination/'sweep.json').write_text(json.dumps(_envelope(manifest),indent=2)+'\n')
        (destination/'ranking.json').write_text(json.dumps([r.document() for r in reviews],indent=2)+'\n')
        (destination/'report.html').write_text(render_sweep(reviews))
    except BaseException:
        shutil.rmtree(destination);raise
    return destination
