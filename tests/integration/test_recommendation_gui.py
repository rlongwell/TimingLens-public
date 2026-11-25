from dataclasses import replace
import json
import time

import pytest


def wait(app,condition,seconds=12):
    end=time.monotonic()+seconds
    while condition() and time.monotonic()<end:app.processEvents();time.sleep(.005)
    assert not condition()
    app.processEvents()


@pytest.fixture
def window(tmp_path,monkeypatch):
    pytest.importorskip('PySide6');monkeypatch.setenv('QT_QPA_PLATFORM','offscreen');monkeypatch.setenv('TIMINGLENS_REPO_ROOT',str(tmp_path))
    from PySide6.QtWidgets import QApplication
    from timinglens.gui.app import MainWindow
    app=QApplication.instance() or QApplication([]);w=MainWindow(app);w.show()
    yield app,w
    w.recommendation_runner.cancel_job();wait(app,lambda:w.thread is not None or w.recommendation_runner.thread is not None or w.lab.thread is not None)
    w.close();app.processEvents()


@pytest.mark.parametrize('name',['deep','priority','fanout'])
def test_recommendation_preview_is_frozen_and_theme_preserves_it(window,recommendation_factory,name,monkeypatch):
    from timinglens.gui import recommendation_runner as gui
    app,w=window;result,plan,prepared=recommendation_factory(name)
    monkeypatch.setattr(gui,'run_recommendation',lambda *_:pytest.fail('Opening a preview must not execute tools'))
    w.set_result(result);w.issues.select_experiment(plan.id);w.navigate(2)
    assert w.issues.try_experiment.isEnabled()
    w.issues.try_experiment.click();r=w.recommendation_runner
    assert w.stack.currentIndex()==8 and r.prepared==prepared and r.thread is None
    preview=r.preview.toPlainText();r.output.setText('/review-only/keep-this')
    for dark in (False,True):
        w.set_theme(dark);app.processEvents()
        assert r.preview.toPlainText()==preview and r.output.text()=='/review-only/keep-this'
    w.set_result(recommendation_factory('priority' if name=='deep' else 'deep')[0])
    assert r.prepared==prepared and r.preview.toPlainText()==preview
    w.issues.set_external_busy(True)
    assert not w.issues.try_experiment.isEnabled()


def test_unsupported_selection_is_disabled_with_reason(window,recommendation_factory):
    app,w=window;result,_,_=recommendation_factory();w.set_result(result)
    unsupported=next(p for g in result.investigations for p in g.plans if p.id not in {'vivado.remap','vivado.extra_timing'})
    w.issues.select_experiment(unsupported.id)
    assert not w.issues.try_experiment.isEnabled() and 'Select ' in w.issues.experiment_note.text()


def test_worker_handoff_restore_two_populations_and_settings(window,tmp_path,recommendation_factory,recommendation_tools,monkeypatch):
    from timinglens.gui import recommendation_runner as gui
    from timinglens.gui.app import MainWindow
    from timinglens.experiments.recommendation_runner import run_recommendation
    tool,calls,_,_=recommendation_tools;app,w=window
    monkeypatch.setattr(gui,'run_recommendation',lambda request,*args:run_recommendation(replace(request,verilator=str(tool)),*args))
    w.settings['unrelated_preference']={'keep':True};w.counter_runner.preferences['last_job']='retain-counter-history'
    w.save_runner(w.counter_runner.preferences)
    result,plan,_=recommendation_factory();w.set_result(result);w.issues.select_experiment(plan.id);w.issues.try_experiment.click()
    r=w.recommendation_runner;r.output.setText(str(tmp_path/'jobs'));r.start_button.click()
    assert not w.counter_runner.start_button.isEnabled() and not w.issues.try_experiment.isEnabled()
    w.start_work(session=tmp_path/'must-not-open');assert w.thread is None
    wait(app,lambda:r.thread is not None or w.lab.thread is not None)
    assert w.stack.currentIndex()==6 and w.lab.result.before.population=='register_paths'
    assert r.progress.value()==7 and r.registers.isEnabled()
    r.global_timing.click();wait(app,lambda:w.lab.thread is not None)
    assert w.lab.result.before.population=='design'
    w.persist();saved=json.loads((tmp_path/'.settings/gui.json').read_bytes())
    assert saved['unrelated_preference']=={'keep':True} and saved['counter_runner']['last_job']=='retain-counter-history'
    reopened=MainWindow(app)
    try:
        count=len(calls);reopened.recommendation_runner.restore.click()
        wait(app,lambda:reopened.recommendation_runner.thread is not None or reopened.lab.thread is not None)
        assert reopened.lab.result.before.population=='register_paths' and len(calls)==count
        assert reopened.recommendation_runner.prepared is None and not reopened.recommendation_runner.start_button.isEnabled()
    finally:reopened.close();app.processEvents()


@pytest.mark.parametrize('close',[False,True])
def test_cancel_preserves_prior_lab_and_waits_for_worker(window,tmp_path,recommendation_factory,recommendation_tools,monkeypatch,close):
    from timinglens.gui import recommendation_runner as gui
    from timinglens.experiments.recommendation_runner import run_recommendation,RecommendationRequest
    from timinglens.experiments.runner import JobFailure
    app,w=window;tool,_,_,_=recommendation_tools;prepared=recommendation_factory()[2]
    previous=run_recommendation(RecommendationRequest(prepared,tmp_path/'previous',verilator=str(tool)))
    w.lab.import_paths(list(previous.register_pair),pair=True);wait(app,lambda:w.lab.thread is not None);comparison=w.lab.result
    events=[]
    def pending(request,log,progress,cancel):
        events.append('started');progress('baseline implementation');assert cancel.wait(5)
        events.append('cancelled');raise JobFailure('retained cancellation evidence',request.output,'cancelled')
    monkeypatch.setattr(gui,'run_recommendation',pending)
    r=w.recommendation_runner;r.configure(prepared);r.output.setText(str(tmp_path/'jobs'));r.start_job()
    wait(app,lambda:'started' not in events)
    if close:w.close();assert w.pending_close
    else:r.cancel_button.click()
    wait(app,lambda:r.thread is not None)
    if close:wait(app,w.isVisible)
    assert events==['started','cancelled'] and w.lab.result is comparison and 'Cancelled' in r.status.text()


def test_failed_restore_retains_lab(window,tmp_path,recommendation_factory,recommendation_tools):
    from timinglens.experiments.recommendation_runner import run_recommendation,RecommendationRequest
    app,w=window;tool,_,_,_=recommendation_tools
    previous=run_recommendation(RecommendationRequest(recommendation_factory()[2],tmp_path/'previous',verilator=str(tool)))
    w.lab.import_paths(list(previous.register_pair),pair=True);wait(app,lambda:w.lab.thread is not None);comparison=w.lab.result
    job=tmp_path/'failed';job.mkdir();(job/'job.json').write_text(json.dumps({'status':'failed','error':'Missing simulation completion marker'}))
    r=w.recommendation_runner;r.preferences['last_job']=str(job);r.restore_job();wait(app,lambda:r.thread is not None)
    assert w.lab.result is comparison and 'Missing simulation' in r.log.toPlainText()


def test_restore_clears_an_unrelated_prepared_experiment(window,tmp_path,recommendation_factory,recommendation_tools):
    from timinglens.experiments.recommendation_runner import run_recommendation,RecommendationRequest
    app,w=window;tool,_,_,_=recommendation_tools
    previous=run_recommendation(RecommendationRequest(recommendation_factory('fanout')[2],tmp_path/'previous',verilator=str(tool)))
    r=w.recommendation_runner;r.configure(recommendation_factory('deep')[2]);r.preferences['last_job']=str(previous.directory)
    r.restore_job();wait(app,lambda:r.thread is not None or w.lab.thread is not None)
    assert r.prepared is None and not r.start_button.isEnabled() and 'High fanout' in r.heading.text()
    assert 'Deep logic' not in r.preview.toPlainText()
