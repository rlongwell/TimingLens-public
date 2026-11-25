"""Sequential, independently gated RTL candidates sharing one controlled baseline."""
from dataclasses import dataclass,replace
import json
from pathlib import Path
from threading import Event
from time import monotonic

from .runner import runner_lock,digest,JobFailure
from .recommendation_runner import _run_recommendation
from .priority_variants import VARIANTS
from .rtl_sweep import RTLSweep,VariantEvidence,write_manifest,load_rtl_sweep,validate_proof_bundle
from .sweep import Reference,_bytes
from ..vivado.runner import Cancelled

POPULATIONS=('register_paths','design')

@dataclass(frozen=True)
class BaselineReference:
    directory:Path
    record:dict
    hashes:dict

    @classmethod
    def capture(cls,child):
        directory=child/'baseline'
        if not all((child/f'runs/baseline.{p}.run.json').is_file() for p in POPULATIONS):return None
        if not json.loads(_bytes(child/'baseline-recheck.json',1_000_000)).get('supported'):raise ValueError('Shared original no longer supports this experiment.')
        # Only the controlled build's native outputs; never follow symlinks.
        paths=[p for p in directory.rglob('*') if not any(part.startswith('.') for part in p.relative_to(directory).parts)]
        if any(p.is_symlink() for p in paths):raise ValueError('Shared original contains a symlink.')
        hashes={str(p.relative_to(directory)):digest(p) for p in paths if p.is_file()}
        if not {'design.sv','timing.xdc','batch.tcl','extract.tcl','routed.dcp','build-record.json','completed.txt'}<=hashes.keys():raise ValueError('Shared original lacks build evidence.')
        record=json.loads(_bytes(directory/'build-record.json',4_000_000))
        if record['checkpoint_sha256']!=hashes['routed.dcp'] or not record['inputs_unchanged']:raise ValueError('Shared original checkpoint provenance disagrees.')
        return cls(directory,record,hashes)

    def copy_to(self,target):
        staged={'design.sv','timing.xdc','batch.tcl','extract.tcl'}
        for name,expected in self.hashes.items():
            source=self.directory/name
            if source.is_symlink() or not source.resolve().is_relative_to(self.directory.resolve()):raise ValueError('Shared original escaped its controlled directory.')
            data=_bytes(source,128_000_000)
            from hashlib import sha256
            if sha256(data).hexdigest()!=expected:raise ValueError('Shared original changed after capture: '+name)
            destination=target/name
            if name in staged:
                if digest(destination)!=expected:raise ValueError('Shared original inputs differ from this candidate recipe.')
            elif name!='build-record.json':
                destination.parent.mkdir(parents=True,exist_ok=True)
                with destination.open('xb') as output:output.write(data)
                destination.chmod(0o444)

@dataclass(frozen=True)
class RTLSweepResult:
    directory:Path
    sweep_path:Path
    status:str
    example:str='priority'

def read_rtl_job(directory):
    path=Path(directory)/'rtl-sweep.json'
    reviews=[load_rtl_sweep(path,p) for p in POPULATIONS]
    if reviews[0].manifest!=reviews[1].manifest:raise ValueError('RTL sweep changed while reading; retry when idle.')
    return RTLSweepResult(Path(directory),path,reviews[0].manifest.status)

def run_rtl_sweep(request,log=lambda _:None,progress=lambda _:None,cancel=None):
    request.validate();cancel=cancel or Event()
    if not request.prepared.rtl_sweep:raise ValueError('Expected a reviewed priority RTL sweep.')
    with runner_lock():
        job=request.output.absolute();job.mkdir(parents=True,exist_ok=False,mode=0o700)
        manifest=RTLSweep(job_name=job.name,status='running',variants=[VariantEvidence(id=k,status='pending') for k in VARIANTS])
        def save():write_manifest(job/'rtl-sweep.json',manifest)
        def retain(child,variant,key):
            refs={}
            for population in POPULATIONS:
                src=child/f'runs/{variant}.{population}.run.json';dst=job/f'runs/{key}.{population}.run.json'
                dst.parent.mkdir(exist_ok=True)
                with dst.open('xb') as out:out.write(_bytes(src,64_000_000))
                refs[population]=Reference(path=str(dst.relative_to(job)),sha256=digest(dst))
            return refs
        save();shared=None;fatal=False
        for index,key in enumerate(VARIANTS):
            if cancel.is_set() or fatal:
                manifest.variants[index]=VariantEvidence(id=key,status='not_run',error='Cancelled before this candidate.' if cancel.is_set() else 'Shared baseline unavailable; see sweep error.');save();continue
            child=job/'variants'/key;started=monotonic();status='completed';error=''
            manifest.variants[index]=VariantEvidence(id=key,status='running');save()
            progress(f'{VARIANTS[key].title} · starting');log('RTL variant: '+VARIANTS[key].title)
            try:
                _run_recommendation(replace(request,prepared=replace(request.prepared,variant=key),output=child),log,
                    lambda phase:progress(VARIANTS[key].title+' · '+phase),cancel,shared_baseline=shared,locked=True)
            except (Exception,KeyboardInterrupt) as failure:
                status='cancelled' if cancel.is_set() or getattr(failure,'status',None)=='cancelled' or isinstance(failure,(Cancelled,KeyboardInterrupt)) else 'failed'
                error=str(failure);log(error)
                if status=='cancelled':cancel.set()
                elif not isinstance(failure,JobFailure):fatal=True
            state=json.loads(_bytes(child/'job.json',4_000_000)) if (child/'job.json').is_file() else {}
            if shared is None and not cancel.is_set():
                try:
                    shared=BaselineReference.capture(child)
                    if shared:manifest=manifest.model_copy(update={'baseline':retain(child,'baseline','baseline')})
                except (ValueError,OSError) as failure:
                    status='failed';error=str(failure);fatal=True
            if status=='failed' and (state.get('phase','').startswith('baseline') or 'tool checks'==state.get('phase')):fatal=True
            if fatal:manifest=manifest.model_copy(update={'error':error})
            records=retain(child,'candidate',key) if status=='completed' else {}
            proof='passed' if state.get('equivalence',{}).get('status')=='passed' else 'not_proven';proof_record=None
            if proof=='passed' and status!='completed':
                try:
                    bundle={'equivalence/'+n:_bytes(child/'equivalence'/n,8_000_000).decode() for n in ('baseline.sv','candidate.sv','equivalence.ys','version.log','equivalence.log','proof.json','result.json')}
                    validate_proof_bundle(bundle,key);target=job/f'proofs/{key}.json';target.parent.mkdir(exist_ok=True)
                    with target.open('x') as out:json.dump(bundle,out)
                    proof_record=Reference(path=str(target.relative_to(job)),sha256=digest(target))
                except (ValueError,OSError) as failure:proof='not_proven';error+='\nProof evidence could not be retained: '+str(failure)
            manifest.variants[index]=VariantEvidence(id=key,status=status,proof=proof,proof_record=proof_record,records=records,seconds=monotonic()-started,error=error)
            save()
        count=sum(v.status=='completed' for v in manifest.variants)
        manifest=manifest.model_copy(update={'status':'cancelled' if cancel.is_set() else 'completed' if count==len(VARIANTS) else 'partial' if count else 'failed'})
        save();result=read_rtl_job(job);progress(manifest.status);return result
