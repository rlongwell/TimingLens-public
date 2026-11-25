import time
from pathlib import Path
import pytest


def wait(app,condition):
    end=time.monotonic()+20
    while condition() and time.monotonic()<end:app.processEvents();time.sleep(.005)
    assert not condition();app.processEvents()


@pytest.fixture
def desktop(tmp_path,monkeypatch):
    pytest.importorskip('PySide6');monkeypatch.setenv('QT_QPA_PLATFORM','offscreen');monkeypatch.setenv('TIMINGLENS_REPO_ROOT',str(tmp_path))
    from PySide6.QtWidgets import QApplication
    from timinglens.gui.app import MainWindow
    app=QApplication.instance() or QApplication([]);w=MainWindow(app);w.show()
    yield app,w
    w.recommendation_runner.cancel_job();wait(app,lambda:w.recommendation_runner.thread is not None or w.lab.thread is not None)
    w.close();app.processEvents()


def test_sweep_preview_handoff_tradeoffs_drilldown_export_and_restore(desktop,tmp_path,rtl_sweep_prepared,rtl_tools):
    from timinglens.experiments.rtl_sweep import load_rtl_sweep
    from timinglens.experiments.priority_variants import VARIANTS,source_diff
    from timinglens.experiments.recommendation import bundled_inputs
    app,w=desktop;r=w.recommendation_runner;lab=w.lab
    w.prepare_recommendation(rtl_sweep_prepared);r.output.setText(str(tmp_path/'jobs'));r.yosys.setText(str(rtl_tools[0]))
    # The configured UI worker discovers the fake Verilator through PATH.
    import timinglens.gui.recommendation_runner as gui
    old=gui.run_recommendation
    from dataclasses import replace
    gui.run_recommendation=lambda request,*args:old(replace(request,verilator=str(rtl_tools[0])),*args)
    try:
        preview=r.preview.toPlainText();assert 'three' in preview.lower() and r.form.isRowVisible(r.yosys)
        r.tabs.setCurrentIndex(r.diff_index)
        for i,key in enumerate(VARIANTS):
            r.variant.setCurrentIndex(i);assert r.diff.toPlainText()==source_diff(bundled_inputs('priority')[0],key)
        before=r.diff.toPlainText();w.toggle_theme();assert before==r.diff.toPlainText() and r.preview.toPlainText()==preview
        r.start_button.click();assert r.cancel_button.isEnabled() and not r.start_button.isEnabled()
        wait(app,lambda:r.thread is not None or lab.thread is not None)
        rtl=lab.rtl
        assert r.result.status=='completed' and lab.tabs.currentIndex()==lab.rtl_index and w.stack.currentIndex()==6
        assert rtl.model.rowCount()==4 and not lab.comparison_card.isVisible() and not lab.selectors.isVisible()
        rtl.table.selectRow(1);assert rtl.compare.isEnabled() and 'Acceptance: blocked' in rtl.detail.toPlainText()
        before=rtl.detail.toPlainText();w.toggle_theme();assert before==rtl.detail.toPlainText()
        rtl.limit.setValue(4);rtl.limit.editingFinished.emit();wait(app,lambda:lab.thread is not None)
        assert all('Over LUT limit' in row.review_limits for row in rtl.review.rows)
        assert all(row.frontier=='Frontier' for row in rtl.review.rows)
        lab.export_to(tmp_path/'export');wait(app,lambda:lab.thread is not None)
        assert load_rtl_sweep(tmp_path/'export/rtl-sweep.json',max_luts=4).document()==rtl.review.document()
        rtl.population.setCurrentIndex(1);wait(app,lambda:lab.thread is not None);assert rtl.review.population=='design'
        rtl.table.selectRow(2);rtl.compare.click();wait(app,lambda:lab.thread is not None)
        assert lab.result.before.context.directives==lab.result.after.context.directives
        assert 'group_select' in lab.change.toPlainText() and lab.tabs.currentIndex()==0
        assert next(g.status for g in lab.result.gates if g.name=='RTL equivalence')=='passed'
        r.restore_job();wait(app,lambda:r.thread is not None or lab.thread is not None)
        assert rtl.review.population=='register_paths' and lab.tabs.currentIndex()==lab.rtl_index
        assert lab.preferences['last_rtl_sweep']==str(r.result.sweep_path.resolve())
        previous=rtl.review;rtl.load(tmp_path/'missing');wait(app,lambda:lab.thread is not None)
        assert rtl.review is previous and 'Could not complete' in lab.status.text()
        record=r.result.directory/'runs/grouped.design.run.json';record.write_bytes(record.read_bytes()+b' ')
        rtl.population.setCurrentIndex(1);wait(app,lambda:lab.thread is not None)
        assert rtl.review is previous and rtl.population.currentData()=='register_paths'
    finally:gui.run_recommendation=old


def test_failed_proof_is_visible_in_lab_and_cannot_be_compared(desktop,tmp_path,rtl_sweep_prepared,monkeypatch):
    from timinglens.experiments import recommendation_runner as backend
    monkeypatch.setattr(backend,'execute',lambda *_:pytest.fail('Missing proof tool must not run a process'))
    app,w=desktop;r=w.recommendation_runner
    w.prepare_recommendation(rtl_sweep_prepared);r.yosys.setText(str(tmp_path/'missing'));r.output.setText(str(tmp_path/'jobs'));r.start_job()
    wait(app,lambda:r.thread is not None or w.lab.thread is not None)
    rtl=w.lab.rtl;assert r.result.status=='failed' and rtl.review.manifest.status=='failed'
    assert len(rtl.review.rows)==4 and all(row.run is None for row in rtl.review.rows)
    rtl.table.selectRow(1)
    assert not rtl.compare.isEnabled() and 'Yosys 0.69 is required' in rtl.detail.toPlainText()
    assert w.lab.export_button.isEnabled() and 'not tested' in rtl.detail.toPlainText()
    r.restore_job();wait(app,lambda:r.thread is not None or w.lab.thread is not None)
    assert rtl.review.manifest.status=='failed' and r.registers.isEnabled()
