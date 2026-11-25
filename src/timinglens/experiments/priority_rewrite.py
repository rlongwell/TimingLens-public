"""One source-pinned, latency-preserving balanced priority experiment."""
from hashlib import sha256
from difflib import unified_diff

PLAN_ID='rtl.priority_balanced'
SOURCE_SHA='8790acd74effc21375adad0702354b39123f548851a0eaea00c743234f1b6b01'
CANDIDATE_SHA='c91666dfe520eeea117280b94b15b2ef48b9a9301a68ccd069455c46dfe67f20'
SCOPE=('RTL equivalence for priority_top at N=16 with binary inputs and corresponding register states; '
       'the input and output register stages are unchanged. No four-state, hardware power-up, '
       'physical timing or implemented-netlist equivalence claim.')
TREE='''    localparam LEAVES = 2**$clog2(N);
    (* keep = "true" *) wire [2*LEAVES-1:1] priority_valid, priority_value;
    for (genvar i=0; i<LEAVES; i++) begin : leaf
        if (i<N) begin : used
            assign priority_valid[LEAVES+i] = req_q[i];
            assign priority_value[LEAVES+i] = req_q[i] & data_q[i];
        end else begin : padding
            assign priority_valid[LEAVES+i] = 1'b0;
            assign priority_value[LEAVES+i] = 1'b0;
        end
    end
    for (genvar i=1; i<LEAVES; i++) begin : branch
        assign priority_valid[i] = priority_valid[2*i] | priority_valid[2*i+1];
        // The right subtree contains the higher-priority requests.
        assign priority_value[i] = priority_valid[2*i+1] ? priority_value[2*i+1] : priority_value[2*i];
    end
'''


def candidate(source:bytes)->bytes:
    if sha256(source).hexdigest()!=SOURCE_SHA:raise ValueError('Priority rewrite requires the exact pinned original source.')
    text=source.decode();start=text.index('    (* keep =');end=text.index('    always_ff',start)
    result=(text[:start]+TREE+text[end:]).replace('result <= selected[N];','result <= priority_value[1];').encode()
    if sha256(result).hexdigest()!=CANDIDATE_SHA:raise ValueError('Balanced candidate changed; revalidate the recipe and proof.')
    return result


def source_diff(source):
    return ''.join(unified_diff(source.decode().splitlines(True),candidate(source).decode().splitlines(True),
                                fromfile='baseline/design.sv',tofile='candidate/design.sv'))


def recommendation(result,path):
    from .recommendation import identify_example
    from ..analysis.fixes import FixPlan,Location,ChangePreview
    try:
        if identify_example(result.session)!='priority':return None
    except ValueError:return None
    source=next(s for s in result.session.sources if not s.path.lower().endswith('.xdc'))
    text=source.text;changed=candidate(text.encode()).decode();location=Location(source.path,1,len(text.splitlines()),text)
    return FixPlan(PLAN_ID,'Balanced priority tree · RTL rewrite','rtl_experiment','Pinned priority_top, N=16',
        (f'{path.id}: {path.levels} measured logic levels; setup slack {path.slack_ns:.3f} ns.',
         'Exact bundled RTL contains a serial highest-index-wins priority chain.'),
        'A four-level tree combines valid/value pairs; each right subtree wins over its lower-index left subtree.',
        'Build an isolated balanced candidate, require an RTL equivalence proof, then compare both RTL versions using Default.',
        prerequisites=('Exact pinned original source and constraints.','Yosys 0.69 and a complete proof before either Vivado implementation.'),
        checks=(SCOPE,'Run both RTL versions through the original finite simulation checks.',
                'Compare routed setup, hold, pulse width, DRC, routing and resources with identical Default recipes.'),
        limitations=('Only the bundled 16-lane top is qualified. A timing improvement is not guaranteed.',
                     'KEEP is applied to the replacement tree wires; hierarchy and register logic remain unchanged.'),
        next_steps=('Review the exact source diff and proof scope.','Run the equivalence-gated experiment in isolated copies.',
                    'Inspect both register and full-example Lab comparisons.'),
        changes=(ChangePreview(location,SOURCE_SHA,0,len(text.encode()),text,changed,'review_diff',source_diff(text.encode()),
                    conditions=('Equivalence must be proven on these exact staged bytes.',),
                    preserved=('Top-level ports, clock, register stages and highest-index priority.','Original XDC and KEEP_HIERARCHY.')),))
