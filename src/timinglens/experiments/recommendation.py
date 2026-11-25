"""Source-pinned, evidence-gated implementation experiments for bundled examples."""
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from importlib.resources import files
import json

from ..analysis.engine import analyze
from ..analysis.fixes import dfx_scope
from ..demo import example_path
from ..timing.models import Session
from .recipes import RECIPES, Recipe
from .priority_rewrite import PLAN_ID as PRIORITY_REWRITE,candidate,source_diff,SCOPE
from .priority_variants import SWEEP_ID,VARIANTS,candidate as variant_source,source_diff as variant_diff


@dataclass(frozen=True)
class Example:
    title: str
    top: str
    period: float
    hashes: tuple[str,str,str]
    plans: tuple[str,...]
    validation: str


EXAMPLES = {
 'deep':Example('Deep logic','deep',2.,('5084298f3c01fe86a55ce4193de026e541eeaf26a8ef0d2a23314369ab1aea6c','d15e9e65f15c75b6845e1cfd787c75be24cce1a1a5a746fc0544f58b80d826d7','56552e170068cb0af3136d8d4f569ac31d4b13bec80b3661e40e3e0dbd662cfa'),('vivado.remap','vivado.extra_timing'),'48 driven samples; 47 checked outputs against a finite logic-chain oracle after pipeline warmup.'),
 'priority':Example('Priority mux','priority_top',2.,('8790acd74effc21375adad0702354b39123f548851a0eaea00c743234f1b6b01','d15e9e65f15c75b6845e1cfd787c75be24cce1a1a5a746fc0544f58b80d826d7','806be61b407e42f75f71870cc8b0dfd6bc4b5b5c7b7954217904bdddb54cfb9f'),('vivado.remap','vivado.extra_timing',PRIORITY_REWRITE,SWEEP_ID),'Six checked priority-selection cases, including competing requests and no request.'),
 'fanout':Example('High fanout','fanout',3.,('887edf4e7f5d187d2c86f703748534839bc16e530980713c662b506e5973151e','84db8e4bbec1c49e9bd8f45091c7fb34f552cf80a9d6be69487caf1ff4b8b860','a303cd14a5814f236d9e3162e8362f4b5df1edf4615a05dfc915f407ee0eed89'),('vivado.fanout','vivado.extra_timing'),'Seven driven cycles; two lane-toggle checks. Verilator zero initialization is a simulation assumption, not hardware power-up or reset validation.'),
}
REMAP=Recipe('Performance_ExploreWithRemap','ExploreWithRemap','Explore','Explore','NoTimingRelaxation')
PLAN_RECIPES={SWEEP_ID:RECIPES['default'],PRIORITY_REWRITE:RECIPES['default'],'vivado.remap':REMAP,'vivado.extra_timing':RECIPES['extra_timing'],
              'vivado.fanout':Recipe('Post-place AggressiveFanoutOpt','Default','Default','AggressiveFanoutOpt','Default')}


def bundled_inputs(name):
    if name not in EXAMPLES:raise ValueError('Choose a supported bundled example.')
    spec=EXAMPLES[name];root=example_path()/name;contents=[]
    for filename,expected in zip(('design.sv','timing.xdc','tb.sv'),spec.hashes):
        path=root/filename
        if path.is_symlink() or not path.is_file():raise ValueError('Expected a regular bundled input: '+filename)
        data=path.read_bytes()
        if sha256(data).hexdigest()!=expected:raise ValueError('Bundled '+name+'/'+filename+' changed; experiment recipe requires revalidation.')
        contents.append(data)
    return tuple(contents)


def identify_example(session):
    name=next((name for name,spec in EXAMPLES.items() if spec.top==session.top),None)
    if not name:raise ValueError('Executable experiments currently support the deep, priority and fanout examples.')
    spec=EXAMPLES[name]
    if session.part!='xc7z020clg400-1' or session.vivado!='2024.2' or session.stage not in {'routed','placed','synthesized'}:
        raise ValueError('This experiment requires Vivado 2024.2, xc7z020clg400-1 and implemented or synthesized evidence.')
    hdl=[s for s in session.sources if not s.path.lower().endswith('.xdc')]
    if len(hdl)!=1 or hdl[0].text is None or hdl[0].sha256!=spec.hashes[0] or sha256(hdl[0].text.encode()).hexdigest()!=spec.hashes[0]:
        raise ValueError('Captured RTL bytes must match the pinned example; names or paths alone are insufficient.')
    constraints=[s for s in session.sources if s.path.lower().endswith('.xdc')]
    if len(constraints)>1:raise ValueError('Additional constraint files are outside this example recipe.')
    for source in constraints:
        if ((source.sha256 is not None and source.sha256!=spec.hashes[1]) or
            (source.text is not None and sha256(source.text.encode()).hexdigest()!=spec.hashes[1])):
            raise ValueError('Captured constraints differ from the pinned example.')
    if (len(session.clocks)!=1 or session.clocks[0].name!='clk' or session.clocks[0].period_ns!=spec.period
            or session.clocks[0].waveform_ns!=[0.,spec.period/2] or session.clocks[0].generated is not False):
        raise ValueError('Captured clocks differ from the example clock model.')
    return name


def eligibility(result,plan):
    """Cheap UI check using already computed analysis; execution reanalyzes the frozen session."""
    try:
        name=identify_example(result.session)
        if dfx_scope(result):raise ValueError('DFX evidence is outside this bundled-example runner.')
        if not plan or plan.id not in EXAMPLES[name].plans or plan.kind!=('rtl_experiment' if plan.id in {PRIORITY_REWRITE,SWEEP_ID} else 'vivado_experiment'):
            raise ValueError('Select '+('AggressiveFanoutOpt or Performance_ExtraTimingOpt.' if name=='fanout' else 'Verified RTL variants, Balanced priority tree, Performance_ExploreWithRemap or Performance_ExtraTimingOpt.' if name=='priority' else 'Performance_ExploreWithRemap or Performance_ExtraTimingOpt.'))
        if not any(plan==p for group in result.investigations for p in group.plans):
            raise ValueError('The selected recommendation is not supported by this analysis.')
        return name,''
    except ValueError as error:return None,str(error)


@dataclass(frozen=True)
class PreparedExperiment:
    example: str
    plan_id: str
    trigger_json: str
    selection: dict
    variant: str | None = None

    @property
    def trigger_sha256(self):return sha256(self.trigger_json.encode()).hexdigest()

    @property
    def recipe(self):return PLAN_RECIPES[self.plan_id]

    @property
    def rtl_rewrite(self):return self.plan_id in {PRIORITY_REWRITE,SWEEP_ID}

    @property
    def rtl_sweep(self):return self.plan_id==SWEEP_ID and self.variant is None

    @property
    def variant_key(self):return self.variant or 'balanced'

    @property
    def candidate_commands(self):
        return ('open_checkpoint placement.dcp','phys_opt_design -directive AggressiveFanoutOpt','route_design -directive Default') if self.plan_id=='vivado.fanout' else self.recipe.commands()

    def document(self):
        spec=EXAMPLES[self.example]
        document={'timinglens_recommendation':1,'example':self.example,'top':spec.top,'plan_id':self.plan_id,
            'trigger_sha256':self.trigger_sha256,'selection':self.selection,'source_sha256':spec.hashes[0],'constraint_sha256':spec.hashes[1],
            'testbench_sha256':spec.hashes[2],'recipe':self.recipe.name,'commands':list(self.candidate_commands),
            'baseline':'Fresh Default build from pinned example source and constraints; imported timing is a trigger, not the comparison baseline.',
            'candidate_start':'Copy of the fresh baseline placed checkpoint' if self.plan_id=='vivado.fanout' else 'Fresh synthesis from the same RTL and constraints',
            'functional_scope':spec.validation+' RTL simulation only; not formal or implemented-netlist equivalence.',
            'limits':['Single trial; benefit and repeatability are not assumed.','All KEEP, KEEP_HIERARCHY and DONT_TOUCH attributes remain intact.',
                'Missing constraint bytes in an older trigger capture do not establish its build context; the new pair uses pinned constraints.',
                'This standalone example is not a board deployment or a validation of a larger integrated application.']}
        if self.rtl_rewrite:
            source=bundled_inputs(self.example)[0]
            document.update(candidate_source_sha256=sha256(variant_source(source,self.variant_key)).hexdigest(),
                candidate_start='Fresh synthesis of '+VARIANTS[self.variant_key].title+'; Default recipe in both builds',
                equivalence_scope=SCOPE,functional_scope=spec.validation+' Run independently on baseline and candidate; finite simulation is additional to the equivalence gate.')
            document['limits'][1]='KEEP is retained on the replacement tree wires; hierarchy and register logic are unchanged.'
            if self.plan_id==SWEEP_ID:
                document.update(variant=self.variant,variants={key:asdict(v) for key,v in VARIANTS.items()})
                document['limits'][1]='KEEP accompanies each replacement structure; hierarchy and register logic are unchanged.'
                if self.rtl_sweep:
                    document.pop('candidate_source_sha256');document['candidate_start']='Three independently proved candidates; one shared original Default build.'
        return document

    def preview(self):
        spec=EXAMPLES[self.example];doc=self.document()
        if self.rtl_sweep:
            return '\n'.join(['Priority mux · Verified RTL variant sweep','Measured trigger: '+self.trigger_sha256,'',
                'One fresh original build, three independently proved candidates. All builds use Default.',
                'Each candidate must pass RTL equivalence and simulation before its implementation. Failed variants stay visible; other variants can continue.',
                *[v.title+': '+v.description for v in VARIANTS.values()],'','EQUIVALENCE GATE',SCOPE,'',
                'Timing/LUT tradeoffs include the original baseline. A frontier point is not acceptance.',
                'Register and full-example populations stay separate. Optional LUT limits flag candidates without hiding results.',
                '',*doc['limits'],'','SOURCE DIFF',*['\n'+v.title+'\n'+variant_diff(bundled_inputs(self.example)[0],key) for key,v in VARIANTS.items()]])
        if self.rtl_rewrite:
            return '\n'.join([spec.title+' · Balanced priority tree','Measured trigger: '+self.trigger_sha256,'',
                'Original RTL → balanced four-level priority tree. Highest asserted request index wins; no request returns zero.',
                'Same input/output registers, ports, clock and constraints. Both builds use Default.',
                'EQUIVALENCE GATE',SCOPE,'A missing, failed or incomplete proof stops the job before Vivado implementation.',
                'Yosys 0.69 reads the exact staged RTL; proof inputs, script, log and result are retained.',
                '',doc['functional_scope'],'','BOTH IMPLEMENTATIONS','  '+'\n  '.join(self.recipe.commands()),
                '',*doc['limits'],'','SOURCE DIFF',source_diff(bundled_inputs(self.example)[0])])
        return '\n'.join([spec.title+' · '+self.recipe.name,'Selected recommendation: '+self.selection['title'],
            'Measured trigger: '+self.trigger_sha256,'',doc['baseline'],'Candidate: '+doc['candidate_start'],
            'RTL and constraint diff: none. Preservation attributes remain unchanged.',
            f'Vivado 2024.2 · xc7z020clg400-1 · {spec.period:g} ns clock · 2 threads · sequential builds','',
            'BASELINE','  '+'\n  '.join(RECIPES['default'].commands()),'','CANDIDATE',
            '  '+'\n  '.join(self.candidate_commands),
            '',doc['functional_scope'],'',*self.selection['evidence'],'',*doc['limits']])


def prepare_experiment(result,plan):
    name,reason=eligibility(result,plan)
    if reason:raise ValueError(reason)
    bundled_inputs(name)
    # Freeze exact embedded evidence; later GUI selection changes cannot alter the request.
    return PreparedExperiment(name,plan.id,result.session.model_dump_json(),asdict(plan))


def revalidate(prepared):
    session=Session.model_validate_json(prepared.trigger_json)
    result=analyze(session)
    selected=next((p for group in result.investigations for p in group.plans if p.id==prepared.plan_id and asdict(p)==prepared.selection),None)
    if selected is None:raise ValueError('Frozen evidence no longer supports the selected recommendation.')
    fresh=prepare_experiment(result,selected)
    if prepared.variant is not None:
        if prepared.plan_id!=SWEEP_ID or prepared.variant not in VARIANTS:raise ValueError('Unsupported priority variant.')
        fresh=replace(fresh,variant=prepared.variant)
    if fresh!=prepared:raise ValueError('Prepared experiment disagrees with its frozen evidence.')
    return fresh


def build_script(name,plan_id=None):
    if name not in EXAMPLES or (plan_id is not None and plan_id not in EXAMPLES[name].plans):raise ValueError('Unsupported example recipe.')
    spec=EXAMPLES[name]
    template=files('timinglens.experiments').joinpath('counter_build.tcl').read_text()
    template=template.replace('counter_main','example_main').replace('TIMINGLENS_COUNTER_BUILD_V1','TIMINGLENS_EXAMPLE_BUILD_V1')
    template=template.replace('TimingLens counter runner','TimingLens recommendation runner')
    template=template.replace('synth_design -top counter -part xc7z020clg400-1 -mode out_of_context',f'synth_design -top {spec.top} -part xc7z020clg400-1')
    template=template.replace('counter counter {} 400 1 0',f'{name} {spec.top} {{}} 400 1 0')
    original=''.join('    '+line+'\n' for line in RECIPES['default'].commands())
    if template.count(original)!=1:raise ValueError('Build template recipe insertion point changed.')
    if plan_id=='vivado.fanout':
        head=f'    read_verilog -sv design.sv\n    read_xdc timing.xdc\n    synth_design -top {spec.top} -part xc7z020clg400-1\n'
        template=template.replace(head,'    open_checkpoint placement.dcp\n')
        commands=('phys_opt_design -directive AggressiveFanoutOpt','route_design -directive Default')
    elif plan_id and plan_id not in {PRIORITY_REWRITE,SWEEP_ID}:commands=PLAN_RECIPES[plan_id].commands()
    else:commands=('opt_design','place_design -directive Default','write_checkpoint placed.dcp','route_design -directive Default')
    template=template.replace(original,''.join('    '+line+'\n' for line in commands),1)
    return template.encode()
