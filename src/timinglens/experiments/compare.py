"""Deterministic comparisons: observed changes and acceptance evidence differ."""
from dataclasses import dataclass, asdict
from hashlib import sha256

from .models import Run
from ..timing.coverage import path_coverage


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    unit: str
    before: float | int | None
    after: float | int | None
    delta: float | None
    status: str
    evidence: str


@dataclass(frozen=True)
class ContextCheck:
    name: str
    status: str
    before: str
    after: str
    detail: str


@dataclass(frozen=True)
class Gate:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class EndpointChange:
    analysis: str
    endpoint: str
    clocks: str
    before_id: str | None
    after_id: str | None
    before_slack: float | None
    after_slack: float | None
    delta: float | None
    status: str
    basis: str
    before_start: str | None
    after_start: str | None


@dataclass(frozen=True)
class Comparison:
    before: Run
    after: Run
    outcome: str
    headline: str
    acceptance: str
    metrics: tuple[Metric, ...]
    context: tuple[ContextCheck, ...]
    gates: tuple[Gate, ...]
    endpoints: tuple[EndpointChange, ...]
    notes: tuple[str, ...]

    def document(self):
        return {'timinglens_comparison': 1, 'rule_version': 'lab.compare.v1',
                'baseline': {'id': self.before.fingerprint, 'label': self.before.label},
                'candidate': {'id': self.after.fingerprint, 'label': self.after.label},
                **{k: getattr(self, k) for k in ('outcome','headline','acceptance','notes')},
                **{k: [asdict(row) for row in getattr(self,k)] for k in ('metrics','context','gates','endpoints')}}


def _change(a, b, higher=True):
    if a is None or b is None: return None, 'not_tested'
    delta = round(b-a, 9)
    if abs(delta) < 1e-9: return delta, 'unchanged'
    return delta, 'improved' if (delta > 0) == higher else 'regressed'


def _metrics(a, b):
    rows=[]
    for check in ('setup','hold'):
        for field,label,unit,higher in [('worst_slack_ns','WNS','ns',True),
                                      ('total_negative_slack_ns','TNS','ns',True),
                                      ('failing_endpoints','failing endpoints','pins',False),
                                      ('total_endpoints','reported population','pins',False)]:
            x=getattr(a.timing.get(check),field,None);y=getattr(b.timing.get(check),field,None)
            delta,status=_change(x,y,higher)
            if field=='total_endpoints' and status in {'improved','regressed'}:status='changed'
            rows.append(Metric(check+'.'+field,check.title()+' '+label,unit,x,y,delta,status,
                               f'{a.population} → {b.population}; authoritative summaries, not the capped path list.'))
    specifications=[('pulse.wns','Pulse width WNS','ns',True),('pulse.failing','Pulse failing endpoints','pins',False),
                    ('route.unrouted','Unrouted routable nets','nets',False),('route.errors','Routing errors','nets',False),
                    ('drc.errors','DRC errors','checks',False),('drc.critical','DRC critical warnings','checks',False),
                    ('drc.warnings','DRC warnings','checks',False),('area.lut_sites','Physical LUT use','LUTs',False),
                    ('area.lut_cells','Logical LUT primitives','cells',False),('area.ff','Flip-flops','FFs',False),
                    ('area.lutram','Memory-capable LUTs used','LUTs',False),('area.bram_tiles','Block RAM tiles','tiles',False),('area.dsp','DSPs','blocks',False)]
    for key,label,unit,higher in specifications:
        x,y=a.metrics.get(key),b.metrics.get(key);delta,status=_change(x,y,higher)
        if key.startswith('area.') and status in {'improved','regressed'}:
            status='decreased' if delta<0 else 'increased'
        evidence=f'Baseline: {a.metric_evidence.get(key,"Not supplied")}. Candidate: {b.metric_evidence.get(key,"Not supplied")}.'
        rows.append(Metric(key,label,unit,x,y,delta,status,evidence))
    return tuple(rows)


def _context(a,b):
    rows=[]
    def check(name,x,y,detail='',hard=True):
        missing=x is None or y is None or x=={} or y=={} or x=='' or y==''
        status='unknown' if missing else 'matched' if x==y else 'mismatch' if hard else 'changed'
        def display(value):
            if value is None or value=={}:return 'Not supplied'
            return str(value)
        rows.append(ContextCheck(name,status,display(x),display(y),detail))
    check('Metric population',a.population,b.population,'Design-wide and register-only summaries are separate populations.')
    check('Declared design identity',a.context.design_key,b.context.design_key,'A declared identity is not netlist equivalence.')
    check('Device',a.session.part,b.session.part)
    check('Vivado release',a.session.vivado,b.session.vivado)
    check('Implementation stage',a.session.stage if a.session.stage!='unknown' else None,
          b.session.stage if b.session.stage!='unknown' else None)
    check('Integration mode',a.context.mode if a.context.mode!='unknown' else None,
          b.context.mode if b.context.mode!='unknown' else None)
    def clocks(run):
        if not run.session.clocks or any(c.period_ns is None or not c.waveform_ns or c.generated is None for c in run.session.clocks):return None
        return sorted((c.name,c.period_ns,tuple(c.waveform_ns),c.master,c.generated,tuple(sorted(c.sources))) for c in run.session.clocks)
    check('Captured clock model',clocks(a),clocks(b),'Clock names, periods, waveforms, sources and generated/master relationships; CDC safety is not inferred.')
    def corners(run):
        if not run.session.paths or any(not p.corner or not p.path_type for p in run.session.paths):return None
        def kind(path):
            # Vivado omits the outer Setup/Hold label on I/O paths at the same
            # process corner. Keep distinct timing checks, e.g. recovery/removal.
            prefix = {"setup": ("Setup (", "Max at "), "hold": ("Hold (", "Min at ")}.get(path.analysis)
            if prefix:
                wrapper, direction = prefix
                bare = path.path_type.removeprefix(wrapper).removesuffix(")")
                if bare.startswith(direction) and bare.endswith(" Process Corner"):
                    return bare
            return path.path_type
        return sorted({(p.analysis, p.corner, kind(p)) for p in run.session.paths})
    check('Captured timing corners',corners(a),corners(b),'Corners and check types represented in the captured paths; unobserved corners remain outside the evidence.')
    check('Constraint file hashes',a.context.constraints,b.context.constraints,
          'Only supplied constraint files are covered. Equal clock periods do not establish equal exceptions.')
    check('Compile context',a.context.compile_context,b.context.compile_context,
          'Macros, includes, parameters and source order require an explicit build capture.')
    check('Implementation directives',a.context.directives,b.context.directives,
          'A changed directive can be the intended experiment; declarations alone do not prove execution.',hard=False)
    check('Source file hashes',a.context.sources,b.context.sources,
          'Changed source is expected for an RTL experiment. Hashes do not prove which source built a checkpoint.',hard=False)
    return tuple(rows)


def _eligible(run,path):
    if run.population!='register_paths':return True
    cells=[]
    for endpoint in (path.startpoint,path.endpoint):
        pin=run.session.pins.get(endpoint or '')
        cell=run.session.cells.get(pin.cell or '') if pin else None
        cells.append(bool(cell and cell.sequential))
    return all(cells)


def _endpoints(a,b):
    def index(run):
        found={};unknown=[]
        for p in run.session.paths:
            if not _eligible(run,p):continue
            if not p.endpoint or not p.start_clock or not p.end_clock:
                unknown.append(p);continue
            key=(p.analysis,p.endpoint,p.start_clock,p.end_clock)
            old=found.get(key)
            order=lambda q:(q.slack_ns if q.slack_ns is not None else float('inf'),q.id)
            if old is None or order(p)<order(old):found[key]=p
        return found,unknown
    left,unknown_a=index(a);right,unknown_b=index(b);rows=[]
    for key in sorted(left.keys()|right.keys()):
        p,q=left.get(key),right.get(key)
        x=p.slack_ns if p else None;y=q.slack_ns if q else None;delta,status=_change(x,y)
        basis='Same captured endpoint name and launch/capture clocks; compares the worst captured path, not netlist equivalence.'
        if p is None:status='candidate_only';basis='Not captured in baseline; cannot establish that this endpoint is new.'
        elif q is None:status='baseline_only';basis='Not captured in candidate; cannot establish that this endpoint was removed or fixed.'
        elif x is not None and y is not None and x>=0>y:status='newly_failing'
        elif x is not None and y is not None and x<0<=y:status='now_passing'
        if p and q and p.startpoint!=q.startpoint:basis+=' The worst captured launch point changed.'
        rows.append(EndpointChange(key[0],key[1],key[2]+' → '+key[3],p.id if p else None,q.id if q else None,
                                   x,y,delta,status,basis,p.startpoint if p else None,q.startpoint if q else None))
    for side,paths in [('baseline',unknown_a),('candidate',unknown_b)]:
        for p in paths:
            rows.append(EndpointChange(p.analysis,p.endpoint or 'Unknown endpoint','Unknown clock identity',
                p.id if side=='baseline' else None,p.id if side=='candidate' else None,
                p.slack_ns if side=='baseline' else None,p.slack_ns if side=='candidate' else None,None,
                'ambiguous','Endpoint or clock identity is missing; no correspondence inferred.',
                p.startpoint if side=='baseline' else None,p.startpoint if side=='candidate' else None))
    rank={'newly_failing':0,'regressed':1,'candidate_only':2,'ambiguous':3,'baseline_only':4,'now_passing':5,'improved':6,'unchanged':7,'not_tested':8}
    return tuple(sorted(rows,key=lambda r:(rank[r.status],r.after_slack if r.after_slack is not None else float('inf'),r.endpoint,r.analysis)))


def _gates(after,context):
    gates=[]
    incompatible=[c.name for c in context if c.status=='mismatch']
    missing=[c.name for c in context if c.status=='unknown']
    gates.append(Gate('Comparison context','failed' if incompatible else 'not_tested' if missing else 'passed',
                      'Mismatch: '+', '.join(incompatible) if incompatible else 'Unknown: '+', '.join(missing) if missing else 'Supplied comparison context matches; intentional source/directive changes are listed separately.'))
    gates.append(Gate('Routed implementation','passed' if after.session.stage=='routed' else 'not_tested',
                      'Candidate capture stage: '+after.session.stage+'.'))
    for name in ('setup','hold'):
        s=after.timing.get(name)
        vals=(s.worst_slack_ns,s.total_negative_slack_ns,s.failing_endpoints) if s else (None,)*3
        if any(v is not None and (v<0 if i<2 else v>0) for i,v in enumerate(vals)):
            state='failed'
        elif any(v is None for v in vals):state='not_tested'
        else:state='passed'
        gates.append(Gate(name.title()+' timing',state,f'Candidate {after.population}: WNS / TNS / failing endpoints = {vals}.'))
    for title,keys in [('Pulse width',('pulse.wns','pulse.failing')),('Routing',('route.unrouted','route.errors')),
                       ('DRC',('drc.errors','drc.critical'))]:
        vals=[after.metrics.get(k) for k in keys]
        failed=any(v is not None and (v<0 if k=='pulse.wns' else v>0) for k,v in zip(keys,vals))
        gates.append(Gate(title,'failed' if failed else 'not_tested' if any(v is None for v in vals) else 'passed',
                          ', '.join(f'{k}={v if v is not None else "not supplied"}' for k,v in zip(keys,vals))))
    checks={c.name:c for c in after.checks}
    if 'equivalence' in checks:
        c=checks['equivalence'];gates.append(Gate('RTL equivalence',c.status if c.status!='not_applicable' else 'not_tested',c.scope+' '+c.evidence))
    verified=bool(after.session.sources) and all(s.text is not None and s.sha256==sha256(s.text.encode()).hexdigest() for s in after.session.sources)
    gates.append(Gate('Embedded source byte verification','passed' if verified else 'not_tested',
                      'Embedded text reproduces recorded source digests; this does not prove checkpoint correspondence.' if verified else 'Some source bytes are missing or cannot reproduce their digest.'))
    for key,label in [('functional','Scoped functional validation'),('source_checkpoint','Source/checkpoint correspondence')]:
        c=checks.get(key)
        gates.append(Gate(label,c.status if c and c.status!='not_applicable' else 'not_tested',c.scope+' '+c.evidence if c else 'No validation evidence supplied.'))
    c=checks.get('dfx_compatibility')
    gates.append(Gate('DFX compatibility','not_applicable' if after.context.dfx is False else c.status if c else 'not_tested',
                      'Recorded design is not DFX.' if after.context.dfx is False else c.scope+' '+c.evidence if c else 'No pr_verify compatibility result supplied; missing DFX metadata is not a pass.'))
    gates.append(Gate('Integrated design validation','passed' if after.context.mode=='integrated' and after.population=='design' else 'not_tested',
                      'Integrated capture scope; other checks still apply.' if after.context.mode=='integrated' and after.population=='design' else 'OOC/register-only or unknown integration scope does not establish full-design signoff.'))
    for name, title in (("resource_budget", "Resource budget"), ("drc_warning_review", "Native DRC warning review")):
        if name in checks:
            check = checks[name]
            gates.append(Gate(title, check.status, check.scope + " " + check.evidence))
    return tuple(gates)


def compare(before:Run,after:Run):
    metrics=_metrics(before,after);context=_context(before,after);gates=_gates(after,context)
    recovery = (before.session.stage == "synthesized" and after.session.stage == "routed"
                and "validation/resource-owners.tsv" in before.attachments
                and "validation/resource-budget.json" in after.attachments)
    if recovery:
        # No paired timing comparison is possible, but the candidate can meet
        # independent signoff with the same device, inputs and implementation recipe.
        comparable = all(row.status == "matched" or (row.name == "Source file hashes" and row.status == "changed")
                         for row in context
                         if row.name not in {"Implementation stage", "Captured timing corners"})
        if comparable:
            gates = tuple(Gate(g.name, "passed", "Matched project context. Baseline stopped before placement; "
                               "only the candidate supplies routed timing.") if g.name == "Comparison context"
                          else g for g in gates)
        metrics = tuple(m if m.key.startswith("area.") else Metric(m.key, m.label, m.unit, None, m.after,
                        None, "not_tested", "Baseline stopped before placement. "+m.evidence) for m in metrics)
    endpoints=() if recovery else _endpoints(before,after)
    newly_failing=[e for e in endpoints if e.status=='newly_failing']
    primary=[m for m in metrics if not m.key.startswith('area.')]
    regressions=[m for m in primary if m.status=='regressed'];improvements=[m for m in primary if m.status=='improved']
    gates += (Gate('Regression guard','failed' if regressions or newly_failing else 'passed' if any(m.before is not None and m.after is not None for m in primary) else 'not_tested',
                   '; '.join([m.label for m in regressions]+([f'{len(newly_failing)} newly failing captured endpoint groups'] if newly_failing else [])) or 'No worsening in comparable summary checks or passing-to-failing transitions in the captured sample. Other endpoint changes and missing checks still require review.'),)
    if recovery:
        gates = tuple(Gate(g.name, "not_applicable", "The baseline could not be placed. "
                           "Routed candidate checks appear separately.") if g.name == "Regression guard"
                      else g for g in gates)
        outcome = "inconclusive"
        headline = "Placement failed on the baseline. The candidate has routed measurements; a timing delta is unavailable."
    elif any(c.status=='mismatch' for c in context):
        outcome='inconclusive';headline='Build context differs; the measurements are not a controlled comparison.'
    elif regressions:
        outcome='regressed';headline='Regression observed: '+'; '.join(f'{m.label} {number(m.before)} → {number(m.after)} {m.unit}' for m in regressions[:2])+'.'
    elif newly_failing:
        outcome='regressed';headline=f'Regression observed: {len(newly_failing)} matched captured endpoint groups changed from passing to failing.'
    elif improvements:
        outcome='improved';headline='Measured improvement: '+'; '.join(f'{m.label} {number(m.before)} → {number(m.after)} {m.unit}' for m in improvements[:2])+'.'
    elif not any(m.before is not None and m.after is not None for m in metrics if m.key.startswith(('setup.','hold.'))):
        outcome='not_tested';headline='No comparable timing measurements were supplied.'
    else:
        outcome='unchanged';headline='No change in the comparable timing and implementation checks.'
    if any(g.status=='failed' for g in gates) or regressions or newly_failing:acceptance='blocked'
    elif any(g.status=='not_tested' for g in gates):acceptance='incomplete'
    else:acceptance='review_ready'
    notes=['Observed improvement is separate from acceptance. No result automatically approves a design change.',
           'Endpoint matching uses captured names and clock pairs, never path IDs or guessed renamed signals. Unmatched samples do not establish removal or newly created logic.',
           'Logical LUT primitive counts and physical LUT utilization measure different quantities.']
    resource_gate = next((gate for gate in gates if gate.name == "Resource budget"), None)
    notes.append(resource_gate.detail if resource_gate else "No resource budget was supplied.")
    if recovery:
        notes.insert(0, "Baseline resource counts come from synthesis after placement failed. "
                        "Candidate resource counts and timing come from the routed design.")
    if any(c.status=='unknown' for c in context):notes.insert(0,'Comparison is provisional: some build context was not captured. Numeric changes remain visible; causation is not established.')
    for label,run in [('Baseline',before),('Candidate',after)]:
        incomplete=sum(not path_coverage(p).complete for p in run.session.paths if _eligible(run,p))
        notes.append(f'{label}: {len(run.session.paths)} captured paths; {incomplete} in-scope paths have incomplete detailed evidence. Collection limits: {run.session.path_limit_per_type} per check / {run.session.paths_per_endpoint} per endpoint.')
    return Comparison(before,after,outcome,headline,acceptance,metrics,context,gates,endpoints,tuple(notes))


def number(value):
    if value is None:return 'Not tested'
    return f'{value:.3f}' if isinstance(value,float) and not value.is_integer() else str(int(value))
