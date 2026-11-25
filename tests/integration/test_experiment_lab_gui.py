from pathlib import Path
import time

import pytest

from timinglens.experiments import compare, load_run, write_run
from timinglens.experiments.capture import from_session
from timinglens.timing.models import Clock, Session, Summary, TimingPath


def wait(app,condition,seconds=10):
    deadline=time.monotonic()+seconds
    while condition() and time.monotonic()<deadline:
        app.processEvents();time.sleep(.005)
    assert not condition(), 'Qt worker did not finish'
    app.processEvents()


def test_lab_import_compare_filters_inspect_export_history_and_failure(tmp_path,monkeypatch):
    pytest.importorskip('PySide6')
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen');monkeypatch.setenv('TIMINGLENS_REPO_ROOT',str(tmp_path))
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from timinglens.gui.app import MainWindow
    import timinglens.gui.experiment_lab as module
    def forbidden(*args,**kwargs):raise AssertionError('Experiment Lab must not run Vivado or resolve source files')
    monkeypatch.setattr('timinglens.service.collect',forbidden)
    monkeypatch.setattr('timinglens.gui.app.collect',forbidden)
    records=[]
    for label,slack in [('Baseline',.1),('Candidate',-.1)]:
        path=TimingPath(id=label,analysis='setup',endpoint='counter/D',startpoint='counter/Q',start_clock='clk',end_clock='clk',slack_ns=slack)
        session=Session(name=label,stage='routed',paths=[path],clocks=[Clock(name='clk',period_ns=2.,waveform_ns=[0.,1.],generated=False)],
            summary={'setup':Summary(worst_slack_ns=slack,total_negative_slack_ns=min(slack,0.),failing_endpoints=int(slack<0),total_endpoints=1)})
        target=tmp_path/(label+'.json');write_run(target,from_session(session));records.append(target)
    real_load=module.load_run
    def slow_load(path):time.sleep(.04);return real_load(path)
    monkeypatch.setattr(module,'load_run',slow_load)
    app=QApplication.instance() or QApplication([]);app.setStyle('Fusion')
    w=MainWindow(app);w.show();w.navigate(6);lab=w.lab
    ticks=[];timer=QTimer();timer.timeout.connect(lambda:ticks.append(1));timer.start(5)
    try:
        lab.import_paths(records,pair=True);wait(app,lambda:lab.thread is not None)
        assert ticks and lab.result.outcome=='regressed' and lab.export_button.isEnabled()
        lab.endpoint_filter.setCurrentIndex(2);assert lab.endpoint_model.rowCount()==1
        lab.search.setText('absent');assert lab.endpoint_model.rowCount()==0
        lab.search.clear();lab.endpoint_table.selectRow(0)
        assert 'Candidate' in lab.after_path.toPlainText()
        lab.open_after.click();wait(app,lambda:w.thread is not None)
        assert w.stack.currentIndex()==1 and w.result.session.name=='Candidate'
        assert w.paths.proxy.rowCount()==1
        w.navigate(6);original=lab.result
        lab.import_paths([tmp_path/'absent.json']);wait(app,lambda:lab.thread is not None)
        assert lab.result is original and 'Could not complete' in lab.status.text()
        assert lab.compare_button.isEnabled()
        lab.swap_runs();assert not lab.export_button.isEnabled() and 'Selection changed' in lab.status.text()
        lab.swap_runs();lab.export_to(tmp_path/'export');wait(app,lambda:lab.thread is not None)
        assert load_run(tmp_path/'export/candidate.run.json').label=='Candidate'
        assert (tmp_path/'export/report.html').is_file()
        w.toggle_theme();assert not w.dark
        assert lab.metric_model.colors['bad']=='#9f2d24'
    finally:
        timer.stop();w.close();app.processEvents()
    reopened=MainWindow(app)
    try:
        assert reopened.lab.recent.isEnabled() and not reopened.lab.records
        reopened.lab.restore_history();wait(app,lambda:reopened.lab.thread is not None)
        assert reopened.lab.baseline.currentText().startswith('Baseline')
        assert reopened.lab.candidate.currentText().startswith('Candidate')
        reopened.lab.compare_selected();wait(app,lambda:reopened.lab.thread is not None)
        assert reopened.lab.result.outcome=='regressed'
        # Closing during import defers destruction until the worker is idle.
        reopened.show();reopened.lab.import_paths(records,pair=True);reopened.close()
        assert reopened.pending_close
        wait(app,lambda:reopened.lab.thread is not None)
        wait(app,reopened.isVisible)
    finally:reopened.close();app.processEvents()


CATALOG=Path(__file__).resolve().parents[2]/'work/experiment-lab/catalog'


@pytest.mark.skipif(not (CATALOG/'catalog.json').is_file(),reason='Retained private captures are not distributed with the source')
def test_retained_counter_and_dfx_verdicts():
    cases=[('unsigned32_ge-internal','improved','blocked',-2.377,-1.659,64,64),
           ('unsigned64_gt-internal','regressed','blocked',-3.030,-2.043,126,128),
           ('unsigned32_ge-global','regressed','blocked',-2.377,-1.659,96,96),
           ('unsigned64_gt-global','regressed','blocked',-3.030,-2.043,190,192)]
    for stem,outcome,acceptance,wns_a,wns_b,fail_a,fail_b in cases:
        result=compare(load_run(CATALOG/(stem+'-before.run.json')),load_run(CATALOG/(stem+'-after.run.json')))
        metrics={m.key:m for m in result.metrics}
        assert (result.outcome,result.acceptance)==(outcome,acceptance)
        assert (metrics['setup.worst_slack_ns'].before,metrics['setup.worst_slack_ns'].after)==(wns_a,wns_b)
        assert (metrics['setup.failing_endpoints'].before,metrics['setup.failing_endpoints'].after)==(fail_a,fail_b)
        assert metrics['area.lut_sites'].after in (42.,82.)
    dfx=compare(load_run(CATALOG/'dfx-failing.run.json'),load_run(CATALOG/'dfx-passing.run.json'))
    assert (dfx.outcome,dfx.acceptance)==('improved','incomplete')
    assert next(m for m in dfx.metrics if m.key=='setup.failing_endpoints').after==0
    assert next(g for g in dfx.gates if g.name=='DFX compatibility').status=='not_tested'
    assert next(c for c in dfx.context if c.name=='Constraint file hashes').status=='unknown'
    assert next(m for m in dfx.metrics if m.key=='drc.errors').after is None
