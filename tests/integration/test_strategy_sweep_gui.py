import time

import pytest


def wait(app,condition):
    end=time.monotonic()+8
    while condition() and time.monotonic()<end:app.processEvents();time.sleep(.005)
    assert not condition();app.processEvents()


@pytest.fixture
def desktop(tmp_path,monkeypatch):
    pytest.importorskip('PySide6');monkeypatch.setenv('QT_QPA_PLATFORM','offscreen');monkeypatch.setenv('TIMINGLENS_REPO_ROOT',str(tmp_path))
    from PySide6.QtWidgets import QApplication
    from timinglens.gui.app import MainWindow
    app=QApplication.instance() or QApplication([]);w=MainWindow(app);w.show()
    yield app,w
    w.counter_runner.cancel_job();wait(app,lambda:w.counter_runner.thread is not None or w.lab.thread is not None)
    w.close();app.processEvents()


def test_sweep_handoff_population_drilldown_export_and_theme(desktop,tmp_path,sweep_factory,monkeypatch):
    import timinglens.gui.counter_runner as gui
    from timinglens.experiments.sweep import load_sweep
    app,w=desktop;seen=[]
    def run(request,log,progress,cancel):
        seen.append(request.strategies);progress('candidate_extra_timing implementation');time.sleep(.03)
        sweep_factory(request.output,{'explore':{'wns':-.5,'tns':-.5},'extra_timing':{'endpoint_slack':-.2}})
        return gui.read_completed_job(request.output)
    monkeypatch.setattr(gui,'run_counter',run)
    r=w.counter_runner;r.output.setText(str(tmp_path/'jobs'));r.mode.setCurrentIndex(1);w.navigate(7)
    preview=r.preview.toPlainText();w.toggle_theme();assert r.preview.toPlainText()==preview
    r.start_button.click();assert not r.mode.isEnabled() and r.cancel_button.isEnabled()
    wait(app,lambda:r.thread is not None or w.lab.thread is not None)
    lab=w.lab;assert w.stack.currentIndex()==6 and lab.tabs.currentIndex()==lab.sweep_index
    assert seen==[('default','explore','extra_timing')] and r.progress.maximum()==11 and r.progress.value()==11
    assert lab.sweep_model.rowCount()==3 and lab.sweep_review.rows[0].strategy=='explore'
    assert lab.sweep_acceptance.text()=='Acceptance: blocked'
    assert not lab.selectors.isVisible() and not lab.comparison_card.isVisible()
    assert r.registers.text()=='View sweep' and r.preferences['sweep'] is True
    before=lab.sweep_detail.toPlainText();w.toggle_theme();assert lab.sweep_detail.toPlainText()==before
    lab.export_to(tmp_path/'export');wait(app,lambda:lab.thread is not None)
    assert load_sweep(tmp_path/'export/sweep.json').document()==lab.sweep_review.document()
    lab.population.setCurrentIndex(1);wait(app,lambda:lab.thread is not None)
    assert lab.sweep_review.population=='design'
    lab.sweep_strategy.click();wait(app,lambda:lab.thread is not None)
    assert lab.tabs.currentIndex()==0 and lab.selectors.isVisible()
    assert lab.result.before.context.sources==lab.result.after.context.sources
    assert lab.result.before.context.directives!=lab.result.after.context.directives
    lab.tabs.setCurrentIndex(lab.sweep_index);lab.sweep_overall.click();wait(app,lambda:lab.thread is not None)
    assert lab.result.before.context.sources!=lab.result.after.context.sources
    assert lab.preferences['last_sweep']==str(r.result.sweep.resolve())
    lab.tabs.setCurrentIndex(lab.sweep_index)
    lab.import_sweep(tmp_path/'missing.json');wait(app,lambda:lab.thread is not None)
    assert lab.sweep_model.rowCount()==3 and 'Could not complete' in lab.status.text()


def test_partial_restore_keeps_failed_rows_unranked_and_no_drilldown(desktop,tmp_path,sweep_factory):
    app,w=desktop;r=w.counter_runner
    path=sweep_factory(tmp_path/'partial',{'explore':{'error':'deliberate fixture failure'}},statuses={'explore':'failed'},status='partial')
    r.preferences['last_job']=str(path.parent);r.restore_job();wait(app,lambda:r.thread is not None or w.lab.thread is not None)
    lab=w.lab;assert r.result.status=='partial' and 'Partial' in lab.sweep_title.text()
    failed=next(i for i,row in enumerate(lab.sweep_review.rows) if row.strategy=='explore')
    lab.sweep_table.selectRow(failed)
    assert 'deliberate fixture failure' in lab.sweep_detail.toPlainText()
    assert not lab.sweep_strategy.isEnabled() and not lab.sweep_overall.isEnabled()
    assert lab.sweep_acceptance.text()=='Acceptance: not tested'
    assert lab.sweep_model.rows[failed][0]=='Unranked' and lab.sweep_model.rows[failed][3] is None
    assert lab.export_button.isEnabled()


def test_worker_failure_hands_retained_sweep_to_lab(desktop,tmp_path,sweep_factory,monkeypatch):
    import timinglens.gui.counter_runner as gui
    from timinglens.experiments.runner import JobFailure
    app,w=desktop
    def cancelled(request,*args):
        sweep_factory(request.output,{'explore':{'error':'cancelled fixture'}},statuses={'explore':'cancelled','extra_timing':'not_run'},status='cancelled')
        raise JobFailure('cancelled fixture',request.output,'cancelled')
    monkeypatch.setattr(gui,'run_counter',cancelled)
    r=w.counter_runner;r.output.setText(str(tmp_path/'jobs'));r.mode.setCurrentIndex(1);r.start_job()
    wait(app,lambda:r.thread is not None or w.lab.thread is not None)
    assert r.result.status=='cancelled' and w.lab.sweep_review.manifest.status=='cancelled'
    assert w.lab.sweep_model.rowCount()==3 and 'Cancelled' in r.status.text()


def test_drilldown_revalidates_file_digests_and_population_reverts_after_error(desktop,tmp_path,sweep_factory):
    app,w=desktop;path=sweep_factory(tmp_path/'sweep');lab=w.lab;lab.import_sweep(path);wait(app,lambda:lab.thread is not None)
    previous=lab.sweep_review
    record=path.parent/'runs/candidate.register_paths.run.json';record.write_bytes(record.read_bytes()+b' ')
    lab.sweep_strategy.click();wait(app,lambda:lab.thread is not None)
    assert lab.result is None and lab.sweep_review is previous and 'digest mismatch' in lab.status.text()
    global_record=path.parent/'runs/candidate.design.run.json';global_record.write_bytes(global_record.read_bytes()+b' ')
    lab.population.setCurrentIndex(1);wait(app,lambda:lab.thread is not None)
    assert lab.sweep_review is previous and lab.population.currentData()=='register_paths'
