#!/usr/bin/env python3
"""Evaluate labeled local captures; all inputs are read-only.

The four original examples are regression data, not held-out validation.
Pass copied DFX captures and independently built holdout results explicitly.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import time

from timinglens.service import load, export_result

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dfx-inputs',type=Path,required=True)
    p.add_argument('--heldout',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    cases=[]
    def case(name,path,partition,required=(),plan=None,negative_edit=True,reason='',clean=False):
        cases.append(dict(name=name,path=str(path),partition=partition,required_rules=required,
                          required_plan=plan,no_review_diff=negative_edit,negative_reason=reason,clean=clean))
    for name,rule in [('deep','TL-A'),('priority','TL-B'),('fanout','TL-C'),('clean',None)]:
        case(name,ROOT/f'results/verified/{name}/analysis.json','existing rule-development regression',
             (rule,) if rule else (),reason='No supported bounded unsigned comparison-to-enable source edit.',clean=name=='clean')
    case('dfx-failing',args.dfx_inputs/'dfx-failing.json','existing real-design regression',('TL-A','TL-D','TL-E'),
         'rtl.compare_enable',reason='Four-state operands and isolated-module elaboration require a hypothesis, not a patch.')
    case('dfx-passing',args.dfx_inputs/'dfx-passing.json','existing real-design regression',
         reason='No measured failures in the completed passing configuration.',clean=True)
    case('stream',args.heldout/'stream/review/analysis.json','held-out RTL design; BD gate revised after first evaluation',('TL-A',),'bd.boundary_review',
         reason='Slow logic is internal to the receiver. An interface slice cannot split that cone. The initial boundary suggestion was downgraded after this counterexample.')
    case('memory_dsp',args.heldout/'memory_dsp/review/analysis.json','held-out design',('TL-E','TL-F'),
         reason='Mapped RAM/DSP do not prove a legal extra cycle or identify unused registers.')
    case('insufficient',ROOT/'tests/fixtures/ambiguous.json','existing evidence-negative regression',('TL-H',),
         reason='Source/graph evidence is absent. Correct response is insufficient evidence.')
    rows=[]
    for spec in cases:
        path=Path(spec['path']);start=time.monotonic();r=load(path)
        plans=[p for i in r.investigations for p in i.plans]+list(r.project_plans)
        rules=sorted({f.rule for f in r.findings});plan_ids=sorted({p.id for p in plans})
        diffs=sum(bool(c.unified_diff) for p in plans for c in p.changes)
        missed=sorted(set(spec['required_rules'])-set(rules))
        if spec['required_plan'] and spec['required_plan'] not in plan_ids:missed.append(spec['required_plan'])
        false_positives=[]
        if spec['no_review_diff'] and diffs:false_positives.append('Unsupported review diff')
        if spec['clean'] and (r.findings or plans):false_positives.append('Finding on labeled clean capture')
        row={**spec,'input_sha256':sha256(path.read_bytes()).hexdigest(),'seconds':round(time.monotonic()-start,3),
             'rules':rules,'plan_ids':plan_ids,'missed_expected_labels':missed,'false_positive_labels':false_positives,
             'review_diffs':diffs,'paths':len(r.session.paths),'failing_paths':r.failing_paths,
             'groups':len(r.groups),'investigations':len(r.investigations),
             'ambiguous_path_associations':sum(a.confidence.value==0 for a in r.paths.values()),
             'unresolved_rtl_plans':sum(p.id=='rtl.mapping' for p in plans),
             'incomplete_paths':sum(not c.complete for c in r.coverage.values()),
             'top_recommendation':r.investigations[0].title if r.investigations else None,
             'summary':{k:v.model_dump() for k,v in r.session.summary.items()}}
        rows.append(row);export_result(r,out/spec['name']);print(spec['name'],rules,plan_ids,missed,false_positives,flush=True)
    report={'scope':'9 captures from 7 RTL designs plus an insufficient-evidence fixture; original fixtures are not held out.',
            'metric_scope':'False positives/misses refer only to the explicit labels below, not all possible design defects.',
            'cases':rows,'false_positive_labels':sum(len(r['false_positive_labels']) for r in rows),
            'missed_expected_labels':sum(len(r['missed_expected_labels']) for r in rows),
            'heldout_rtl_cases':2, 'untouched_heldout_bd_cases':1,
            'initial_overreach':'stream initially received bd.register_slice from interface names alone. A measured cross-instance delay gate now returns bd.boundary_review. This case is no longer held out for the BD rule.'}
    (out/'evaluation.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
