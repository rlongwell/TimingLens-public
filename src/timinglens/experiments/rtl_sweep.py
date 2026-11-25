"""Portable verified RTL sweeps and explicit timing/LUT tradeoffs."""
from dataclasses import dataclass,replace
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import shutil
from typing import Literal
from types import SimpleNamespace
from pydantic import Field,model_validator
from .models import Record,Run,canonical
from .sweep import Reference,Population,_bytes,_load_reference,explain
from .compare import Comparison,compare,number
from .io import load_run
from .recipes import RECIPES
from .priority_variants import VARIANTS
from .priority_rewrite import SOURCE_SHA
from ..timing.io import atomic_text

POLICY=('The measured timing/LUT frontier includes the original and every comparable completed variant: higher setup WNS and fewer logical LUTs, with at least one strict gain. '
        'It ignores hold, other resources and acceptance. Review limits flag any measured regression or LUT-limit excess without hiding rows. '
        'Missing data, unproved and incomplete candidates have no frontier status. One build per variant does not establish repeatability.')

class VariantEvidence(Record):
    id:Literal['balanced','grouped','mask']
    status:Literal['pending','running','completed','failed','cancelled','not_run']
    proof:Literal['passed','not_proven','not_run']='not_run'
    records:dict[Population,Reference]=Field(default_factory=dict)
    proof_record:Reference|None=None
    seconds:float|None=Field(default=None,ge=0,allow_inf_nan=False)
    error:str=''
    @model_validator(mode='after')
    def complete(self):
        if self.status=='completed' and (self.proof!='passed' or set(self.records)!={'design','register_paths'}):raise ValueError('Completed RTL variant requires proof and both timing populations.')
        if self.status!='completed' and self.records:raise ValueError('Incomplete variants cannot claim completed records.')
        if self.status!='completed' and self.proof=='passed' and not self.proof_record:raise ValueError('An unbuilt variant requires retained proof evidence to claim a pass.')
        if self.proof_record and self.proof!='passed':raise ValueError('A proof record requires a validated pass.')
        return self

class RTLSweep(Record):
    rule_version:Literal['rtl.tradeoff.v1']='rtl.tradeoff.v1'
    job_name:str
    status:Literal['running','completed','partial','failed','cancelled']
    error:str=''
    baseline:dict[Population,Reference]=Field(default_factory=dict)
    variants:list[VariantEvidence]
    @model_validator(mode='after')
    def complete(self):
        if [v.id for v in self.variants]!=list(VARIANTS):raise ValueError('RTL sweep must list each qualified variant exactly once, in catalog order.')
        if self.baseline and set(self.baseline)!={'design','register_paths'}:raise ValueError('Shared original requires both timing populations.')
        if any(v.status=='completed' for v in self.variants) and not self.baseline:raise ValueError('Completed RTL variants require a shared original.')
        if self.status=='completed' and (any(v.status!='completed' for v in self.variants) or set(self.baseline)!={'design','register_paths'}):raise ValueError('Completed RTL sweep lacks complete evidence.')
        return self

def envelope(manifest):
    data=manifest.model_dump(mode='json');return {'timinglens_rtl_sweep':1,'sha256':sha256(canonical(data)).hexdigest(),'sweep':data}

def write_manifest(path,manifest):atomic_text(path,json.dumps(envelope(manifest),indent=2)+'\n')

def read_manifest(path):
    data=json.loads(_bytes(path,1_000_000))
    if not isinstance(data,dict) or set(data)!={'timinglens_rtl_sweep','sha256','sweep'} or type(data['timinglens_rtl_sweep']) is not int or data['timinglens_rtl_sweep']!=1:raise ValueError('Unsupported RTL sweep schema.')
    if sha256(canonical(data['sweep'])).hexdigest()!=data['sha256']:raise ValueError('RTL sweep integrity check failed.')
    return RTLSweep.model_validate_json(json.dumps(data['sweep']))

@dataclass(frozen=True)
class RTLRow:
    variant:str
    status:str
    proof:str
    run:Run|None
    comparison:Comparison|None
    frontier:str
    review_limits:str
    reason:str
    explanations:tuple[str,...]

@dataclass(frozen=True)
class RTLReview:
    path:Path
    manifest:RTLSweep
    population:str
    max_luts:int|None
    baseline:Run|None
    rows:tuple[RTLRow,...]
    def document(self):
        return {'rule_version':'rtl.tradeoff.v1','population':self.population,'max_luts':self.max_luts,'status':self.manifest.status,'policy':POLICY,
                'rows':[{'variant':r.variant,'status':r.status,'proof':r.proof,'frontier':r.frontier,'review_limits':r.review_limits,'reason':r.reason,
                         'run_id':r.run.fingerprint if r.run else None,'comparison':r.comparison.document() if r.comparison else None,'explanations':r.explanations} for r in self.rows]}

def _identity(run,key):
    from .recommendation import EXAMPLES,build_script
    expected=SOURCE_SHA if key=='baseline' else VARIANTS[key].sha256
    if run.context.design_key!='example:priority' or run.context.sources!={'design.sv':expected}:raise ValueError('RTL variant identity or source hash disagrees with its catalog entry.')
    hdl=[s for s in run.session.sources if not s.path.lower().endswith('.xdc')]
    constraints=[s for s in run.session.sources if s.path.lower().endswith('.xdc')]
    if len(hdl)!=1 or hdl[0].sha256!=expected or len(constraints)!=1 or constraints[0].sha256!=EXAMPLES['priority'].hashes[1]:raise ValueError('Captured source/constraint identity differs from the qualified RTL variant.')
    if run.context.directives!=RECIPES['default'].directives():raise ValueError('RTL sweep requires the same Default recipe in every record.')
    if run.context.constraints!={'timing.xdc':EXAMPLES['priority'].hashes[1]} or run.session.top!='priority_top' or run.session.vivado!='2024.2' or run.session.part!='xc7z020clg400-1':raise ValueError('RTL sweep context differs from the qualified priority example.')
    script=run.attachments.get(('baseline' if key=='baseline' else 'candidate')+'/batch.tcl','')
    if script.encode()!=build_script('priority'):raise ValueError('RTL sweep requires the byte-identical Default implementation script.')
    if run.metrics.get('area.lut_cells') is not None:
        primitive=run.attachments.get(('baseline' if key=='baseline' else 'candidate')+'/primitives.tsv','').strip().split('\t')
        if len(primitive)!=2 or primitive[0]!='LUT*' or int(primitive[1])!=run.metrics['area.lut_cells']:raise ValueError('Logical LUT measurement disagrees with its retained primitive count.')
    if key!='baseline':
        if not any(c.name=='equivalence' and c.status=='passed' for c in run.checks):raise ValueError('RTL variant lacks its validated equivalence pass.')
        if sha256(run.attachments.get('equivalence/candidate.sv','').encode()).hexdigest()!=expected:raise ValueError('RTL variant proof covers a different candidate.')

def validate_proof_bundle(attachments,key):
    from .equivalence import validate_attached_proof
    if not isinstance(attachments,dict) or any(not isinstance(v,str) for v in attachments.values()):raise ValueError('Invalid retained proof bundle.')
    validate_attached_proof(SimpleNamespace(attachments=attachments,context=SimpleNamespace(sources={'design.sv':VARIANTS[key].sha256})))

def _load_proof(path,reference,key):
    target=path.parent/reference.path
    if reference.path!=f'proofs/{key}.json' or not target.resolve().is_relative_to(path.parent.resolve()):raise ValueError('Unexpected RTL proof path.')
    data=_bytes(target,16_000_000)
    if sha256(data).hexdigest()!=reference.sha256:raise ValueError('RTL proof digest mismatch.')
    validate_proof_bundle(json.loads(data),key)

def _eligible(run,comparison):
    if any(c.status in {'unknown','mismatch'} for c in comparison.context):return 'Incomplete or incompatible build context.'
    if any(g.status!='passed' for g in comparison.gates if g.name in {'Routed implementation','Routing','Embedded source byte verification','Scoped functional validation','Source/checkpoint correspondence'}):return 'Required build or validation evidence did not pass.'
    for kind in ('setup','hold'):
        summary=run.timing.get(kind)
        if summary is None or any(getattr(summary,k) is None for k in ('worst_slack_ns','total_negative_slack_ns','failing_endpoints','total_endpoints')):return 'Missing timing measurements; missing is not zero.'
    if any(run.metrics.get(k) is None for k in ('area.lut_cells','area.ff','pulse.wns','pulse.failing','route.unrouted','route.errors','drc.errors','drc.critical','drc.warnings')):return 'Missing resource, pulse, route or DRC evidence.'
    return ''

def load_rtl_sweep(path,population='register_paths',max_luts=None):
    path=Path(path)
    if population not in {'register_paths','design'}:raise ValueError('Unknown RTL timing population.')
    if max_luts is not None and (type(max_luts) is not int or not 1<=max_luts<=1_000_000):raise ValueError('LUT limit must be a positive integer or unset.')
    manifest=read_manifest(path);baseline=_load_reference(path,manifest.baseline[population],'baseline',population) if population in manifest.baseline else None
    for evidence in manifest.variants:
        if evidence.proof_record:_load_proof(path,evidence.proof_record,evidence.id)
    if baseline:_identity(baseline,'baseline')
    rows=[];points={};base_problem=_eligible(baseline,compare(baseline,baseline)) if baseline else 'No completed original baseline.'
    for key,evidence in [('baseline',None),*[(v.id,v) for v in manifest.variants]]:
        run=baseline if key=='baseline' else _load_reference(path,evidence.records[population],key,population) if evidence.status=='completed' else None
        if run:_identity(run,key)
        comparison=compare(baseline,run) if baseline and run else None
        reason=(evidence.error or 'No completed measurements.') if evidence and not run else base_problem or (_eligible(run,comparison) if comparison else 'No completed original baseline.')
        if not reason and run:points[key]=(run.timing['setup'].worst_slack_ns,run.metrics['area.lut_cells'])
        limits='Not tested'
        if comparison and not reason:
            flags=[]
            if comparison.outcome=='regressed':flags.append('Regression')
            if max_luts is not None and run.metrics['area.lut_cells']>max_luts:flags.append('Over LUT limit')
            limits='; '.join(flags) if flags else 'Within limits'
        explanations=explain(comparison) if comparison else (reason or 'No completed comparison.',)
        if run and baseline:
            explanations += (f"Logical LUTs: {number(baseline.metrics.get('area.lut_cells'))} → {number(run.metrics.get('area.lut_cells'))}; FFs: {number(baseline.metrics.get('area.ff'))} → {number(run.metrics.get('area.ff'))}.",)
        rows.append(RTLRow(key,'completed' if key=='baseline' and run else 'not_run' if key=='baseline' else evidence.status,
            'reference' if key=='baseline' else evidence.proof,run,comparison,'Not comparable',limits,reason,explanations))
    for i,row in enumerate(rows):
        if row.variant in points:
            wns,luts=points[row.variant]
            dominated=any(w>=wns and l<=luts and (w>wns or l<luts) for key,(w,l) in points.items() if key!=row.variant)
            rows[i]=replace(row,frontier='Dominated' if dominated else 'Frontier',reason='Measured timing/LUT tradeoff; acceptance and review limits remain separate.')
    return RTLReview(path,manifest,population,max_luts,baseline,tuple(rows))

def pair_paths(review,key):
    if key not in VARIANTS or not any(r.variant==key and r.comparison for r in review.rows):raise ValueError('This RTL variant has no completed comparison.')
    return tuple(review.path.parent/f'runs/{v}.{review.population}.run.json' for v in ('baseline',key))

def export_rtl_sweep(path,destination,max_luts=None):
    path=Path(path);destination=Path(destination);reviews=[load_rtl_sweep(path,p,max_luts) for p in ('register_paths','design')]
    if reviews[0].manifest!=reviews[1].manifest:raise ValueError('RTL sweep changed while reading; retry when the job is idle.')
    destination.mkdir(parents=True,exist_ok=False)
    try:
        manifest=reviews[0].manifest
        for refs in [manifest.baseline,*[v.records for v in manifest.variants if v.status=='completed']]:
            for ref in refs.values():
                if not (path.parent/ref.path).resolve().is_relative_to(path.parent.resolve()):raise ValueError('Run evidence points outside this sweep.')
                data=_bytes(path.parent/ref.path,64_000_000)
                if sha256(data).hexdigest()!=ref.sha256:raise ValueError('RTL evidence changed during export.')
                target=destination/ref.path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        for evidence in manifest.variants:
            if evidence.proof_record:
                ref=evidence.proof_record;_load_proof(path,ref,evidence.id);data=_bytes(path.parent/ref.path,16_000_000)
                if sha256(data).hexdigest()!=ref.sha256:raise ValueError('RTL proof changed during export.')
                target=destination/ref.path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        write_manifest(destination/'rtl-sweep.json',manifest)
        (destination/'tradeoffs.json').write_text(json.dumps([r.document() for r in reviews],indent=2)+'\n')
        parts=['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Priority RTL variants</title>',
            '<style>body{font:15px system-ui;line-height:1.6;background:#252525;color:#eee;max-width:1400px;margin:32px auto;padding:0 24px}table{border-collapse:collapse;width:100%}th,td{padding:9px;border-bottom:1px solid #555;text-align:left}.table{overflow:auto}pre{white-space:pre-wrap;background:#303030;padding:16px}</style>',
            '<h1>Priority RTL variants</h1><p>'+escape(manifest.status)+' · Default recipe throughout · LUT limit: '+str(max_luts or 'unset')+'</p><p>'+escape(POLICY)+'</p>']
        for review in reviews:
            parts+=['<h2>'+escape(review.population)+'</h2><div class="table"><table><tr><th>Variant</th><th>Build</th><th>Proof</th><th>Setup WNS</th><th>Hold WNS</th><th>LUTs</th><th>FFs</th><th>Tradeoff</th><th>Review limits</th><th>Acceptance</th></tr>']
            for row in review.rows:
                r=row.run;values=[VARIANTS[row.variant].title if row.variant in VARIANTS else 'Original',row.status,row.proof,number(getattr(r.timing.get('setup'),'worst_slack_ns',None) if r else None),number(getattr(r.timing.get('hold'),'worst_slack_ns',None) if r else None),number(r.metrics.get('area.lut_cells') if r else None),number(r.metrics.get('area.ff') if r else None),row.frontier,row.review_limits,row.comparison.acceptance if row.comparison else 'not tested']
                parts.append('<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in values)+'</tr>')
            parts.append('</table></div>')
            for row in review.rows:parts+=['<h3>'+escape(row.variant)+'</h3><p>'+escape(row.reason)+'</p><pre>'+escape('\n'.join(row.explanations))+'</pre>']
        (destination/'report.html').write_text(''.join(parts)+'</html>')
    except BaseException:shutil.rmtree(destination);raise
    return destination
