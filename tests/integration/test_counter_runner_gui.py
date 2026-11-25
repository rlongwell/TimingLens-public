from hashlib import sha256
import json
from pathlib import Path
import time

import pytest

from timinglens.experiments.capture import from_session
from timinglens.experiments.io import write_run
from timinglens.experiments.models import Artifact, Run
from timinglens.experiments.runner import CounterResult, JobFailure
from timinglens.timing.models import Session, Summary


def wait(app,condition,seconds=8):
    end=time.monotonic()+seconds
    while condition() and time.monotonic()<end:app.processEvents();time.sleep(.005)
    assert not condition()
    app.processEvents()


def completed(directory):
    directory.mkdir(parents=True);pairs={}
    for population in ('register_paths','design'):
        pairs[population]={}
        for variant,slack in [('baseline',-1.),('candidate',-.5)]:
            summary=Summary(worst_slack_ns=slack,total_negative_slack_ns=slack,failing_endpoints=1,total_endpoints=1)
            run=from_session(Session(name=variant,summary={'setup':summary}))
            if population=='register_paths':
                text=f'setup\t{slack}\t{slack}\t1\t1\n'
                run=Run.model_validate({**run.model_dump(),'population':population,'attachments':{'registers.tsv':text},
                    'artifacts':[Artifact(name='registers.tsv',sha256=sha256(text.encode()).hexdigest(),kind='register_timing')]})
            filename=f'runs/{variant}.{population}.run.json';write_run(directory/filename,run)
            pairs[population][variant]=filename
    (directory/'job.json').write_text(json.dumps({'timinglens_job':1,'status':'completed','example':'counter64','pairs':pairs}))
    return CounterResult(directory,tuple(directory/pairs['register_paths'][v] for v in ('baseline','candidate')),
                         tuple(directory/pairs['design'][v] for v in ('baseline','candidate')),'counter64')


def test_runner_gui_handoff_restore_theme_and_global_pair(tmp_path,monkeypatch):
    pytest.importorskip('PySide6');monkeypatch.setenv('QT_QPA_PLATFORM','offscreen');monkeypatch.setenv('TIMINGLENS_REPO_ROOT',str(tmp_path))
    from PySide6.QtWidgets import QApplication
    from timinglens.gui.app import MainWindow
    import timinglens.gui.counter_runner as gui
    def fake_run(request,log,progress,cancel):
        progress('simulation');log('Checking the known source change');time.sleep(.05)
        return completed(request.output)
    monkeypatch.setattr(gui,'run_counter',fake_run)
    app=QApplication.instance() or QApplication([]);w=MainWindow(app);w.show();w.navigate(7)
    try:
        r=w.counter_runner;r.output.setText(str(tmp_path/'jobs'));r.example.setCurrentIndex(1)
        before=r.preview.toPlainText();w.toggle_theme();assert r.preview.toPlainText()==before
        r.start_button.click();assert not r.start_button.isEnabled() and r.cancel_button.isEnabled()
        wait(app,lambda:r.thread is not None or w.lab.thread is not None)
        assert w.stack.currentIndex()==6 and w.lab.result.outcome=='improved'
        assert w.lab.result.before.population=='register_paths'
        w.navigate(7);r.global_timing.click();wait(app,lambda:w.lab.thread is not None)
        assert w.lab.result.before.population=='design'
        assert r.progress.value()==7 and r.registers.isEnabled()
    finally:w.close();app.processEvents()
    reopened=MainWindow(app)
    try:
        assert reopened.counter_runner.example.currentData()=='counter64'
        assert reopened.counter_runner.restore.isEnabled()
        reopened.counter_runner.restore.click()
        wait(app,lambda:reopened.counter_runner.thread is not None or reopened.lab.thread is not None)
        assert reopened.lab.result.before.population=='register_paths'
    finally:reopened.close();app.processEvents()


def test_close_cancels_runner_and_does_not_replace_previous_comparison(tmp_path,monkeypatch):
    pytest.importorskip('PySide6');monkeypatch.setenv('QT_QPA_PLATFORM','offscreen');monkeypatch.setenv('TIMINGLENS_REPO_ROOT',str(tmp_path))
    from PySide6.QtWidgets import QApplication
    from timinglens.gui.app import MainWindow
    import timinglens.gui.counter_runner as gui
    events=[]
    def pending(request,log,progress,cancel):
        events.append('started');progress('baseline implementation')
        assert cancel.wait(5)
        events.append('cancelled');raise JobFailure('retained cancellation evidence',request.output,'cancelled')
    monkeypatch.setattr(gui,'run_counter',pending)
    app=QApplication.instance() or QApplication([]);w=MainWindow(app);w.show();w.navigate(7)
    r=w.counter_runner;r.output.setText(str(tmp_path/'jobs'))
    try:
        previous=completed(tmp_path/'previous');w.lab.import_paths(list(previous.register_pair),pair=True)
        wait(app,lambda:w.lab.thread is not None);result=w.lab.result
        w.navigate(7);r.start_job();wait(app,lambda:'started' not in events)
        w.close();assert w.pending_close
        wait(app,lambda:r.thread is not None);wait(app,w.isVisible)
        assert events==['started','cancelled'] and w.lab.result is result
        assert 'Cancelled' in r.status.text()
    finally:r.cancel_job();wait(app,lambda:r.thread is not None);w.close();app.processEvents()


def test_completed_job_rejects_paths_outside_job(tmp_path):
    pytest.importorskip('PySide6')
    from timinglens.gui.counter_runner import read_completed_job
    result=completed(tmp_path/'job');state=json.loads((result.directory/'job.json').read_text())
    state['pairs']['register_paths']['baseline']='../outside.run.json'
    (result.directory/'job.json').write_text(json.dumps(state))
    with pytest.raises(ValueError,match='Unexpected run path'):read_completed_job(result.directory)
