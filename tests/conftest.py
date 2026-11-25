"""Small, explicit synthetic sweep evidence for offline behavior tests."""
from hashlib import sha256

import pytest


@pytest.fixture
def sweep_factory():
    from timinglens.experiments.capture import from_session
    from timinglens.experiments.io import write_run
    from timinglens.experiments.models import Artifact, BuildContext, Check, Run
    from timinglens.experiments.recipes import RECIPES, variant_name
    from timinglens.experiments.sweep import write_sweep
    from timinglens.timing.models import Cell, Clock, Pin, Session, Source, Summary, TimingPath

    def make(directory,tweaks=None,statuses=None,status='completed'):
        directory.mkdir(parents=True);tweaks=tweaks or {};statuses=statuses or {}
        state={'example':'counter32','status':status,'strategies':list(RECIPES),'strategy_runs':{}}
        for strategy in ('baseline',*RECIPES):
            variant='baseline' if strategy=='baseline' else variant_name(strategy)
            options=tweaks.get(strategy,{})
            if strategy!='baseline':
                state['strategy_runs'][strategy]={'status':statuses.get(strategy,'completed'),'seconds':options.get('seconds',1.),'error':options.get('error','')}
                if statuses.get(strategy,'completed')!='completed':continue
            source='original synthetic fixture' if strategy=='baseline' else 'candidate synthetic fixture'
            digest=sha256(source.encode()).hexdigest()
            setup=Summary(worst_slack_ns=options.get('wns',-1.),total_negative_slack_ns=options.get('tns',-1.),failing_endpoints=options.get('fail',1),total_endpoints=4)
            hold=Summary(worst_slack_ns=options.get('hold_wns',.1),total_negative_slack_ns=options.get('hold_tns',0.),failing_endpoints=options.get('hold_fail',0),total_endpoints=4)
            reports={'pulse':'Design Timing Summary\nWNS(ns) TNS(ns) WPWS(ns) TPWS Total Endpoints\n------------\n-1 -1 1 4 .1 0 0 4 .5 0 0 1\n',
                     'route':'Design Route Status\n# of routable nets.... : 4 :\n# of fully routed nets.... : 4 :\n# of nets with routing errors.... : 0 :\n',
                     'drc':'Report DRC\nChecks found: 0\n','area':'Utilization\n| Slice LUTs | 42 |\n'}
            for name in options.get('omit_reports',()):reports.pop(name)
            paths=[TimingPath(id=variant+'-setup',analysis='setup',startpoint=options.get('start','a/Q'),endpoint='b/D',start_clock='clk',end_clock='clk',
                              slack_ns=options.get('endpoint_slack',.2),corner='Slow',path_type='Setup',logic_ns=options.get('logic',1.),routing_ns=.4,skew_ns=.02,uncertainty_ns=.1),
                   TimingPath(id=variant+'-hold',analysis='hold',startpoint='a/Q',endpoint='b/D',start_clock='clk',end_clock='clk',slack_ns=options.get('hold_endpoint_slack',.1),corner='Fast',path_type='Hold')]
            session=Session(name='SYNTHETIC sweep fixture',part=options.get('part','xc7z020clg400-1'),vivado='2024.2',stage='routed',top='counter',
                summary={'setup':setup,'hold':hold},paths=paths,reports=reports,clocks=[Clock(name='clk',period_ns=2.,waveform_ns=[0.,1.],generated=False)],
                cells={n:Cell(name=n,primitive='FDRE',sequential=True) for n in ('a','b','c')},
                pins={n:Pin(name=n,cell=n[0]) for n in ('a/Q','b/D','c/Q')},sources=[Source(path='design.sv',text=source,sha256=digest)])
            run=from_session(session)
            context=BuildContext(design_key='counter32',mode='out_of_context',dfx=False,constraints={'timing.xdc':'a'*64},sources={'design.sv':digest},
                compile_context={'defines':'none'},directives=RECIPES['default' if strategy=='baseline' else strategy].directives(),checkpoint_sha256='b'*64)
            if options.get('different_source'):context=context.model_copy(update={'sources':{'design.sv':'c'*64}})
            if options.get('wrong_directives'):context=context.model_copy(update={'directives':{'place':'Default'}})
            checks=[Check(name=n,status='passed',scope='Synthetic fixture only',evidence='Explicit test data') for n in ('functional','source_checkpoint')]
            run=run.model_copy(update={'context':context,'checks':[] if options.get('omit_checks') else checks})
            for population in ('design','register_paths'):
                record=run
                if population=='register_paths':
                    text=''.join(f'{kind}\t{s.worst_slack_ns}\t{s.total_negative_slack_ns}\t{s.failing_endpoints}\t{s.total_endpoints}\n' for kind,s in run.timing.items())
                    record=Run.model_validate({**run.model_dump(),'population':population,'attachments':{'registers.tsv':text},
                        'artifacts':[*run.artifacts,Artifact(name='registers.tsv',kind='register_timing',sha256=sha256(text.encode()).hexdigest())]})
                write_run(directory/f'runs/{variant}.{population}.run.json',record)
            if strategy=='baseline':state['baseline_records']=True
        write_sweep(directory,state)
        return directory/'sweep.json'
    return make


@pytest.fixture
def recommendation_factory():
    """Synthetic complete timing graph, with the real pinned RTL embedded."""
    from timinglens.analysis.engine import analyze
    from timinglens.experiments.recommendation import EXAMPLES,bundled_inputs,prepare_experiment
    from timinglens.timing.models import Arc,Cell,Clock,Net,Pin,Session,Source,Summary,TimingPath
    def make(name='deep'):
        spec=EXAMPLES[name];source,xdc,_=bundled_inputs(name)
        cells={n:Cell(name=n,primitive='FDRE',sequential=True) for n in ('launch','capture')}
        pins={'launch/Q':Pin(name='launch/Q',cell='launch',direction='OUT',ref_pin='Q'),'capture/D':Pin(name='capture/D',cell='capture',direction='IN',ref_pin='D')}
        nets={};arcs=[];ordered=['launch/Q'];previous='launch/Q'
        for i in range(8):
            n=f'logic{i}';cells[n]=Cell(name=n,primitive='LUT2')
            a,b=n+'/I0',n+'/O';pins[a]=Pin(name=a,cell=n,direction='IN',ref_pin='I0');pins[b]=Pin(name=b,cell=n,direction='OUT',ref_pin='O')
            net=f'net{i}';nets[net]=Net(name=net,fanout=192 if name=='fanout' else 1,drivers=[previous],sinks=[a])
            arcs += [Arc(source=previous,sink=a,kind='net',resource=net,delay_ns=2. if name=='fanout' and i==0 else .7),Arc(source=a,sink=b,kind='cell',resource=n,delay_ns=.3)]
            ordered += [a,b];previous=b
        nets['last']=Net(name='last',fanout=1,drivers=[previous],sinks=['capture/D']);arcs.append(Arc(source=previous,sink='capture/D',kind='net',resource='last',delay_ns=.2));ordered.append('capture/D')
        setup=TimingPath(id='P1',analysis='setup',startpoint='launch/Q',endpoint='capture/D',start_clock='clk',end_clock='clk',slack_ns=-1.,
            requirement_ns=spec.period,datapath_ns=9.5 if name=='fanout' else 8.2,logic_ns=2.4,routing_ns=7.1 if name=='fanout' else 5.8,levels=8,corner='Slow',path_type='Setup',cells=list(cells),pins=ordered,nets=list(nets),arcs=arcs)
        hold=setup.model_copy(update={'id':'P2','analysis':'hold','slack_ns':.1,'corner':'Fast','path_type':'Hold'})
        session=Session(name='SYNTHETIC recommendation fixture',top=spec.top,part='xc7z020clg400-1',vivado='2024.2',stage='routed',
            cells=cells,pins=pins,nets=nets,paths=[setup,hold],
            clocks=[Clock(name='clk',period_ns=spec.period,waveform_ns=[0.,spec.period/2],generated=False)],
            sources=[Source(path='/descriptive-only/design.sv',text=source.decode(),sha256=sha256(source).hexdigest()),Source(path='/descriptive-only/timing.xdc',text=xdc.decode(),sha256=sha256(xdc).hexdigest())],
            summary={'setup':Summary(worst_slack_ns=-1.,total_negative_slack_ns=-1.,failing_endpoints=1,total_endpoints=1),'hold':Summary(worst_slack_ns=.1,total_negative_slack_ns=0.,failing_endpoints=0,total_endpoints=1)},
            reports={'pulse':'Design Timing Summary\nWNS(ns) TNS(ns) WPWS(ns) TPWS Total Endpoints\n------------\n-1 -1 1 1 .1 0 0 1 .5 0 0 1\n',
                     'route':'Design Route Status\n# of routable nets.... : 4 :\n# of fully routed nets.... : 4 :\n# of nets with routing errors.... : 0 :\n'})
        result=analyze(session);id='vivado.fanout' if name=='fanout' else 'vivado.remap'
        plan=next(p for group in result.investigations for p in group.plans if p.id==id)
        return result,plan,prepare_experiment(result,plan)
    return make


@pytest.fixture
def recommendation_tools(tmp_path,monkeypatch,recommendation_factory):
    from pathlib import Path
    from timinglens.experiments import recommendation_runner as runner
    from timinglens.timing.models import Source
    executable=tmp_path/'tool';executable.write_text('fixture');executable.chmod(0o700)
    monkeypatch.setenv('TIMINGLENS_REPO_ROOT',str(tmp_path));monkeypatch.setattr(runner,'discover',lambda _:executable)
    calls=[]
    def execute(command,cwd,logfile,cancel,timeout,log):
        calls.append((cwd.name,logfile.name,[str(c) for c in command]));text='fixture completed\n'
        if logfile.name=='vivado-version.log':text='Vivado v2024.2\n'
        elif logfile.name=='verilator-version.log':text='Verilator 5.020\n'
        elif logfile.name=='simulation.log':text='TIMINGLENS_EXAMPLE_SIM_PASS\n'
        elif logfile.name=='vivado.log':
            (cwd/'routed.dcp').write_bytes(b'fixture checkpoint '+cwd.name.encode())
            if cwd.name=='baseline':(cwd/'placed.dcp').write_bytes(b'fixture placement')
            (cwd/'completed.txt').write_text('TIMINGLENS_EXAMPLE_BUILD_V1\n');(cwd/'internal').mkdir()
            (cwd/'registers.tsv').write_text('setup\t-1\t-1\t1\t1\nhold\t0.1\t0\t0\t1\n')
            (cwd/'primitives.tsv').write_text('LUT*\t8\n');(cwd/'utilization.rpt').write_text('Utilization\n| Slice LUTs | 8 |\n')
            (cwd/'drc.rpt').write_text('Report DRC\nChecks found: 0\n')
        logfile.write_text(text);log(text)
        return {'command':[str(c) for c in command],'seconds':.01,'returncode':0,'log':logfile.name}
    def snapshot(folder,source_root):
        import json
        job=source_root.parent;name=json.loads((job/'plan.json').read_bytes())['example']
        session=recommendation_factory(name)[0].session
        sources=[Source(path=str(source_root/name),text=(source_root/name).read_text(),sha256=sha256((source_root/name).read_bytes()).hexdigest()) for name in ('design.sv','timing.xdc')]
        return session.model_copy(update={'sources':sources})
    monkeypatch.setattr(runner,'execute',execute);monkeypatch.setattr(runner,'snapshot',snapshot)
    return executable,calls,execute,snapshot


@pytest.fixture
def rtl_sweep_prepared(recommendation_factory):
    from timinglens.experiments.recommendation import prepare_experiment
    result=recommendation_factory('priority')[0]
    plan=next(p for g in result.investigations for p in g.plans if p.id=='rtl.priority_sweep')
    return prepare_experiment(result,plan)


@pytest.fixture
def rtl_tools(recommendation_tools,monkeypatch):
    """Synthetic process adapter, only for orchestration and UI behavior tests."""
    import json
    from timinglens.experiments import recommendation_runner as runner
    from timinglens.experiments.equivalence import MARKER
    tool,calls,old,snapshot=recommendation_tools
    cells={f'e{i}':{'type':'$equiv','connections':{'A':[i+100],'B':[i+100],'Y':[i]}} for i in range(67)}
    proof={'modules':{'equiv':{'cells':cells,'netnames':{'result':{'bits':[0]},'u_select.req_q':{'bits':list(range(1,17))},'u_select.data_q':{'bits':list(range(17,33))}}}}}
    def fake(command,cwd,logfile,*args):
        if logfile.name in {'version.log','equivalence.log'}:
            calls.append((cwd.name,logfile.name,[str(c) for c in command]))
            logfile.write_text('Yosys 0.69 (synthetic fixture)' if logfile.name=='version.log' else 'Equivalence successfully proven!\n'+MARKER)
            if logfile.name=='equivalence.log':(cwd/'proof.json').write_text(json.dumps(proof))
            return {'seconds':.01,'returncode':0,'log':logfile.name}
        result=old(command,cwd,logfile,*args)
        if logfile.name=='vivado.log':(cwd/'utilization.rpt').write_text('Utilization\n| Slice LUTs | 8 |\n| Register as Flip Flop | 33 |\n')
        return result
    monkeypatch.setattr(runner,'execute',fake);monkeypatch.setattr(runner,'discover_yosys',lambda _:tool)
    return tool,calls,fake,snapshot


@pytest.fixture
def rtl_job_factory(rtl_tools,rtl_sweep_prepared):
    from timinglens.experiments.recommendation_runner import RecommendationRequest,run_recommendation
    def make(path):return run_recommendation(RecommendationRequest(rtl_sweep_prepared,path,verilator=str(rtl_tools[0])))
    return make
