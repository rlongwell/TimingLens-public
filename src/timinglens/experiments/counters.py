"""Source-pinned counter experiments; arbitrary projects and patches are excluded."""
from dataclasses import dataclass
from difflib import unified_diff
from hashlib import sha256

from ..analysis.rtl_fixes import factored
from ..demo import example_path
from ..rtl.semantics import SemanticIndex
from ..rtl.syntax import build_index
from ..timing.models import Source

XDC_HASH = 'd15e9e65f15c75b6845e1cfd787c75be24cce1a1a5a746fc0544f58b80d826d7'

@dataclass(frozen=True)
class Counter:
    width: int
    operator: str
    source_hash: str
    testbench_hash: str
    period_ns: float = 2.
    constraint_hash: str = XDC_HASH


COUNTERS = {
    'counter32': Counter(32, '>=', 'e24003f3a011fa85a442d27dd7433e66cd8a23e83fe519ccf2e24ad7d8ba32ea', '38b03bd7f55ca5c36b016ced310e84a96fa13f02032001ffbfce774d9fc1da69'),
    'counter64': Counter(64, '>', '4c8afe6e337ceb7d508a870642c806eeab615fd971e144ab5ca62223cbe27c1f', 'a45808c96712ba516fb45c4e798472dfdde8d40534f3db1437fe7edc97270106'),
    'counter32_250': Counter(32, '>=', 'e24003f3a011fa85a442d27dd7433e66cd8a23e83fe519ccf2e24ad7d8ba32ea', '38b03bd7f55ca5c36b016ced310e84a96fa13f02032001ffbfce774d9fc1da69', 4., '8aec164025f69e1d235d502292384a17d5f907d8e359ad19d4ab0ab5814372da'),
}


@dataclass(frozen=True)
class CounterPlan:
    name: str
    baseline: bytes
    candidate: bytes
    constraints: bytes
    testbench: bytes
    diff: str
    original: str
    replacement: str
    start: int
    end: int

    def document(self):
        return {'recipe':'unsigned-comparison-factor.v1','example':self.name,
                'clock_period_ns':COUNTERS[self.name].period_ns,
                'baseline_sha256':sha256(self.baseline).hexdigest(),'candidate_sha256':sha256(self.candidate).hexdigest(),
                'constraints_sha256':sha256(self.constraints).hexdigest(),'testbench_sha256':sha256(self.testbench).hexdigest(),
                'start_byte':self.start,'end_byte':self.end,'original':self.original,'replacement':self.replacement,
                'scope':'One unsigned binary comparison; same counter width, reset, load, acceptance and latency.',
                'validation':'Finite simulation plus routed OOC measurements; not formal equivalence or integrated signoff.'}


def plan_counter(name: str) -> CounterPlan:
    if name not in COUNTERS:
        raise ValueError('Choose a bundled counter profile; this runner does not accept arbitrary designs.')
    spec=COUNTERS[name];root=example_path()/name
    for filename in ('design.sv','timing.xdc','tb.sv'):
        if (root/filename).is_symlink() or not (root/filename).is_file():
            raise ValueError('Counter inputs must be bundled regular files, not symlinks.')
    source=(root/'design.sv').read_bytes();constraints=(root/'timing.xdc').read_bytes();tb=(root/'tb.sv').read_bytes()
    if sha256(source).hexdigest()!=spec.source_hash or sha256(constraints).hexdigest()!=spec.constraint_hash:
        raise ValueError('Bundled counter source/constraints changed; refusing to apply a stale recipe.')
    if sha256(tb).hexdigest()!=spec.testbench_hash:
        raise ValueError('Bundled counter testbench changed; refusing to claim the expected validation scope.')
    index=build_index([Source(path='design.sv',text=source.decode(),sha256=spec.source_hash)])
    register,reason=SemanticIndex(index,'counter').resolve(index.modules['counter'][0],None,'remaining')
    if not register or register.parameterized or register.elaboration!='Supplied project hierarchy':
        raise ValueError('Counter semantic context is unresolved: '+reason)
    comparisons={c.span.start:c for d in register.enable_decisions for c in d.comparisons}
    if len(comparisons)!=1:raise ValueError('Expected exactly one supported counter comparison.')
    comparison=next(iter(comparisons.values()))
    if (comparison.unknowns_possible or comparison.operand_type.signed or comparison.operand_type.four_state
            or comparison.operand_type.width!=spec.width or comparison.narrow_width!=4 or comparison.operator!=spec.operator):
        raise ValueError('The unsigned, two-state counter preconditions no longer hold.')
    span=comparison.span;replacement=factored(comparison)
    if not replacement or source[span.start:span.end].decode()!=span.text:
        raise ValueError('Source bytes do not match the proposed expression span.')
    candidate=source[:span.start]+replacement.encode()+source[span.end:]
    diff=''.join(unified_diff(source.decode().splitlines(True),candidate.decode().splitlines(True),
                             fromfile='baseline/design.sv',tofile='candidate/design.sv'))
    return CounterPlan(name,source,candidate,constraints,tb,diff,span.text,replacement,span.start,span.end)
