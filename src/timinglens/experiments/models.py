"""Self-contained evidence records. Paths are descriptive and never followed."""
from hashlib import sha256
import json
from typing import Literal

from pydantic import Field, model_validator

from ..timing.models import Record, Finite, Session, Summary


class Artifact(Record):
    name: str
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    kind: str
    note: str = ''


class Check(Record):
    name: str
    status: Literal['passed', 'failed', 'not_tested', 'not_applicable'] = 'not_tested'
    scope: str = Field(min_length=1)
    evidence: str = ''

    @model_validator(mode='after')
    def measured_result(self):
        if self.status in {'passed','failed'} and not self.evidence.strip():
            raise ValueError('A recorded pass/fail check requires an evidence description.')
        return self


class BuildContext(Record):
    design_key: str | None = None
    mode: Literal['integrated', 'out_of_context', 'unknown'] = 'unknown'
    constraints: dict[str, str] = Field(default_factory=dict)
    sources: dict[str, str] = Field(default_factory=dict)
    directives: dict[str, str] = Field(default_factory=dict)
    compile_context: dict[str, str] = Field(default_factory=dict)
    checkpoint_sha256: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')
    dfx: bool | None = None
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def digests(self):
        import re
        if any(not re.fullmatch(r'[0-9a-f]{64}', h) for h in (*self.constraints.values(), *self.sources.values())):
            raise ValueError('Source/constraint identities require SHA-256 digests.')
        return self


class Run(Record):
    label: str = Field(min_length=1, max_length=200)
    session: Session
    population: Literal['design', 'register_paths'] = 'design'
    timing: dict[Literal['setup', 'hold'], Summary] = Field(default_factory=dict)
    metrics: dict[str, Finite] = Field(default_factory=dict)
    metric_evidence: dict[str, str] = Field(default_factory=dict)
    context: BuildContext = Field(default_factory=BuildContext)
    checks: list[Check] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    attachments: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    change_diff: str = ''

    @model_validator(mode='after')
    def consistency(self):
        if len({c.name for c in self.checks}) != len(self.checks):
            raise ValueError('Check names must be unique; conflicting results cannot be merged.')
        for key,value in self.metrics.items():
            if key not in {'pulse.wns','pulse.tns'} and value < 0:
                raise ValueError('Resource and violation counts must be nonnegative.')
            if key not in {'pulse.wns','pulse.tns','area.bram_tiles'} and not float(value).is_integer():
                raise ValueError('Endpoint, resource and violation counts must be integral.')
        if self.population == 'design' and self.timing != self.session.summary:
            raise ValueError('Design-wide timing must agree with the captured session summary.')
        if self.population == 'register_paths' and not any(a.kind == 'register_timing' for a in self.artifacts):
            raise ValueError('Register-only timing requires its own report provenance.')
        artifacts = {a.name:a for a in self.artifacts}
        if len(artifacts)!=len(self.artifacts):
            raise ValueError('Artifact names must be unique.')
        for name,text in self.attachments.items():
            if name not in artifacts or sha256(text.encode()).hexdigest()!=artifacts[name].sha256:
                raise ValueError('An embedded attachment must match its artifact digest.')
        pipeline_proof = "pipeline-proof/proof.json" in self.attachments
        if pipeline_proof and "equivalence/result.json" in self.attachments:
            raise ValueError("The run contains two different equivalence proof formats.")
        if pipeline_proof or 'equivalence/result.json' in self.attachments or any(c.name=='equivalence' and c.status=='passed' for c in self.checks):
            if not any(c.name=='equivalence' and c.status=='passed' for c in self.checks):
                raise ValueError('An embedded completed equivalence proof requires its explicit passed check.')
            if pipeline_proof:
                from .pipeline_proof import validate_attached_pipeline
                validate_attached_pipeline(self)
            else:
                from .equivalence import validate_attached_proof
                validate_attached_proof(self)
        if self.population == 'register_paths':
            reports=[a for a in self.artifacts if a.kind=='register_timing']
            if len(reports)!=1 or reports[0].name not in self.attachments:
                raise ValueError('Register-only timing requires one embedded register_timing TSV.')
            measured={}
            for line in self.attachments[reports[0].name].splitlines():
                kind,wns,tns,failed,total=line.split('\t')
                if kind not in {'setup','hold'} or kind in measured:
                    raise ValueError('Register timing TSV has unknown or duplicate checks.')
                measured[kind]=Summary(worst_slack_ns=float(wns),total_negative_slack_ns=round(float(tns),3),
                                       failing_endpoints=int(failed),total_endpoints=int(total))
            if measured!=self.timing:
                raise ValueError('Register timing must agree with its embedded TSV measurements.')
        for summary in self.timing.values():
            if summary.failing_endpoints is not None and summary.total_endpoints is not None and summary.failing_endpoints > summary.total_endpoints:
                raise ValueError('Failing endpoints exceed the reported population.')
        if len(self.session.paths) > 10000 or len(self.artifacts) > 512:
            raise ValueError('Experiment evidence exceeds path/artifact limits.')
        return self

    @property
    def fingerprint(self):
        return sha256(canonical(self.model_dump(mode='json'))).hexdigest()


def canonical(data):
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
