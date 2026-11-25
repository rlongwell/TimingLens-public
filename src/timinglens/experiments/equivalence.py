"""Fail-closed Yosys equivalence gate for the pinned 16-lane priority rewrite."""
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import sys

from .priority_rewrite import SCOPE,SOURCE_SHA,CANDIDATE_SHA
from .priority_variants import VARIANTS
from .sweep import _bytes

MARKER='TIMINGLENS_PRIORITY_EQUIV_PASS'
SCRIPT='''# These hierarchy attributes are removed only in the formal intermediate representation.
# Staged RTL and Vivado builds retain their hierarchy/preservation attributes.
read_verilog -sv baseline.sv
hierarchy -check -top priority_top
proc
setattr -unset keep_hierarchy
setattr -mod -unset keep_hierarchy
flatten
rename priority_top gold
design -stash gold
read_verilog -sv candidate.sv
hierarchy -check -top priority_top
proc
setattr -unset keep_hierarchy
setattr -mod -unset keep_hierarchy
flatten
rename priority_top gate
design -stash gate
design -copy-from gold -as gold gold
design -copy-from gate -as gate gate
equiv_make gold gate equiv
hierarchy -check -top equiv
equiv_simple
equiv_status -assert
write_json proof.json
log TIMINGLENS_PRIORITY_EQUIV_PASS
'''


def discover_yosys(explicit=None):
    candidates=[explicit] if explicit else [Path(sys.executable).parent/'yowasp-yosys',shutil.which('yosys'),shutil.which('yowasp-yosys')]
    for name in candidates:
        if not name:continue
        path=Path(shutil.which(str(name)) or name).absolute()
        if path.is_file() and os.access(path,os.X_OK):return path
    raise ValueError('Yosys 0.69 is required for RTL equivalence. Install TimingLens with the gui/formal extra or select its executable.')


def command_prefix():
    """Keep first-time WebAssembly compilation at low priority on at most two CPUs."""
    prefix=[shutil.which('nice'),'-n','10'] if shutil.which('nice') else []
    if shutil.which('taskset') and hasattr(os,'sched_getaffinity'):
        prefix += [shutil.which('taskset'),'-c',','.join(str(n) for n in sorted(os.sched_getaffinity(0))[:2])]
    return prefix


def validate_proof(version,log,raw):
    if not re.search(r'\bYosys 0\.69(?:\s|$)',version):raise ValueError('Priority equivalence is qualified with Yosys 0.69.')
    if MARKER not in log or 'Equivalence successfully proven!' not in log:
        raise ValueError('Equivalence proof is missing its successful completion evidence.')
    proof=json.loads(raw)
    if set(proof.get('modules',{}))!={'equiv'}:raise ValueError('Expected one fully flattened equivalence module.')
    module=proof['modules']['equiv'];cells=list(module['cells'].values());equiv=[c for c in cells if c['type']=='$equiv']
    if len(equiv)!=67 or any(c['connections']['A']!=c['connections']['B'] for c in equiv):
        raise ValueError('Equivalence requires all 67 matched points to be proven; incomplete proof is not a pass.')
    if any(c['type'] not in {'$equiv','$dff','$mux','$and','$or','$not','$reduce_or','$scopeinfo'} for c in cells):
        raise ValueError('Unsupported cell in the equivalence proof.')
    points={bit for c in equiv for bit in c['connections']['Y']}
    for name,width in [('result',1),('u_select.req_q',16),('u_select.data_q',16)]:
        bits=module['netnames'][name]['bits']
        if len(bits)!=width or not set(bits)<=points:raise ValueError('Proof does not cover the output and every state bit.')
    return len(equiv)


def verify_proof(folder):
    version=_bytes(folder/'version.log',100_000).decode();log=_bytes(folder/'equivalence.log',4_000_000).decode()
    raw=_bytes(folder/'proof.json',8_000_000);count=validate_proof(version,log,raw)
    return {'timinglens_equivalence':1,'status':'passed','scope':SCOPE,'matched_points':count,
            'yosys':version.strip(),'proof_sha256':sha256(raw).hexdigest(),
            'inputs_sha256':{name:sha256(_bytes(folder/name,1_000_000)).hexdigest() for name in ('baseline.sv','candidate.sv','equivalence.ys')},
            'method':'Yosys equiv_make + equiv_simple + equiv_status -assert; all output, state and matched alias points proven.'}


def validate_attached_proof(run):
    """A portable pass must retain the proof and the exact source pair it covers."""
    def get(name):
        key='equivalence/'+name
        if key not in run.attachments:raise ValueError('RTL equivalence pass is missing embedded '+name)
        return run.attachments[key]
    raw=get('proof.json');version=get('version.log');log=get('equivalence.log')
    count=validate_proof(version,log,raw)
    result=json.loads(get('result.json'))
    candidate_sha=sha256(get('candidate.sv').encode()).hexdigest()
    if candidate_sha not in {v.sha256 for v in VARIANTS.values()}:raise ValueError('Equivalence candidate is outside the pinned variant catalog.')
    expected={'baseline.sv':SOURCE_SHA,'candidate.sv':candidate_sha,'equivalence.ys':sha256(SCRIPT.encode()).hexdigest()}
    if (result.get('timinglens_equivalence')!=1 or result.get('status')!='passed' or result.get('scope')!=SCOPE
        or result.get('matched_points')!=count or result.get('proof_sha256')!=sha256(raw.encode()).hexdigest()
        or result.get('inputs_sha256')!=expected or result.get('yosys')!=version.strip()):
        raise ValueError('RTL equivalence metadata disagrees with its proof or pinned source pair.')
    if any(sha256(get(name).encode()).hexdigest()!=digest for name,digest in expected.items()):
        raise ValueError('RTL equivalence input bytes changed.')
    if run.context.sources not in ({'design.sv':SOURCE_SHA},{'design.sv':candidate_sha}):
        raise ValueError('RTL equivalence proof does not cover this run source.')
