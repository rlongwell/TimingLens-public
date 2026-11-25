"""Three source-pinned, latency-preserving priority implementations."""
from dataclasses import dataclass,replace
from hashlib import sha256
from difflib import unified_diff
from .priority_rewrite import SOURCE_SHA,CANDIDATE_SHA,candidate as balanced

SWEEP_ID='rtl.priority_sweep'

@dataclass(frozen=True)
class Variant:
    title:str
    sha256:str
    description:str

VARIANTS={
    'balanced':Variant('Balanced tree',CANDIDATE_SHA,'Four binary valid/value merge levels.'),
    'grouped':Variant('Grouped selection','f81deaf231cfecc1b86518e02635ed4dfd18251214f14dcc2745148687f364b3','Four local 4-lane selectors followed by a group-priority selector.'),
    'mask':Variant('Priority mask','6d3d7bc8652bc37bcfbc0aa9cdf41d6342b05a2721b1efa17e81bcf262375434','Each lane wins only when no higher request is asserted; winning data bits are ORed.'),
}
GROUPED='''    localparam GROUPS = (N+3)/4;
    (* keep = "true" *) wire [GROUPS-1:0] group_valid, group_value;
    for (genvar g=0; g<GROUPS; g++) begin : group_select
        wire [3:0] local_valid;
        (* keep = "true" *) wire [4:0] local_value;
        assign local_value[0] = 1'b0;
        for (genvar j=0; j<4; j++) begin : lane
            if (4*g+j<N) begin : used
                assign local_valid[j] = req_q[4*g+j];
                assign local_value[j+1] = req_q[4*g+j] ? data_q[4*g+j] : local_value[j];
            end else begin : padding
                assign local_valid[j] = 1'b0;
                assign local_value[j+1] = local_value[j];
            end
        end
        assign group_valid[g] = |local_valid;
        assign group_value[g] = local_value[4];
    end
    (* keep = "true" *) wire [GROUPS:0] group_choice;
    assign group_choice[0] = 1'b0;
    for (genvar g=0; g<GROUPS; g++) begin : choose_group
        assign group_choice[g+1] = group_valid[g] ? group_value[g] : group_choice[g];
    end
'''
MASK='''    (* keep = "true" *) wire [N-1:0] winning_data;
    for (genvar i=0; i<N; i++) begin : winner
        if (i==N-1) begin : highest
            assign winning_data[i] = req_q[i] & data_q[i];
        end else begin : lower
            assign winning_data[i] = req_q[i] & data_q[i] & ~(|req_q[N-1:i+1]);
        end
    end
'''

def _render(source,key):
    if key=='balanced':return balanced(source)
    text=source.decode();start=text.index('    (* keep =');end=text.index('    always_ff',start)
    body,output=(GROUPED,'group_choice[GROUPS]') if key=='grouped' else (MASK,'|winning_data')
    return (text[:start]+body+text[end:]).replace('result <= selected[N];','result <= '+output+';').encode()

def candidate(source,key='balanced'):
    if key not in VARIANTS or sha256(source).hexdigest()!=SOURCE_SHA:raise ValueError('Choose a pinned priority variant and original source.')
    data=_render(source,key)
    if sha256(data).hexdigest()!=VARIANTS[key].sha256:raise ValueError('Priority variant changed; revalidate source and equivalence.')
    return data

def source_diff(source,key='balanced'):
    return ''.join(unified_diff(source.decode().splitlines(True),candidate(source,key).decode().splitlines(True),fromfile='baseline/design.sv',tofile='candidate/design.sv'))

def sweep_plan(plan):
    change=plan.changes[0];source=change.original.encode()
    return replace(plan,id=SWEEP_ID,title='Verified RTL variants · 3 candidates',
        reasoning='Compare a balanced tree, grouped selection and priority mask under the same Default implementation recipe.',
        action='Prove every candidate independently; reuse one fresh original build and inspect timing/area tradeoffs.',
        next_steps=('Review all three source diffs and the proof scope.','Run isolated candidates with individual equivalence gates.',
                    'Inspect the timing/LUT frontier, regressions and acceptance in RTL variants.'),
        changes=tuple(replace(change,proposed=candidate(source,key).decode(),unified_diff=source_diff(source,key)) for key in VARIANTS))
