from dataclasses import replace
import time

import pytest


def wait(app,condition,seconds=15):
    end=time.monotonic()+seconds
    while condition() and time.monotonic()<end:app.processEvents();time.sleep(.005)
    assert not condition();app.processEvents()


def test_balanced_preview_preserves_diff_theme_and_proof_tool(tmp_path,monkeypatch,recommendation_factory):
    pytest.importorskip('PySide6');monkeypatch.setenv('QT_QPA_PLATFORM','offscreen');monkeypatch.setenv('TIMINGLENS_REPO_ROOT',str(tmp_path))
    from PySide6.QtWidgets import QApplication
    from timinglens.gui.app import MainWindow
    app=QApplication.instance() or QApplication([]);w=MainWindow(app);w.show()
    try:
        w.set_result(recommendation_factory('priority')[0]);w.issues.select_experiment('rtl.priority_balanced')
        assert w.issues.try_experiment.isEnabled() and w.issues.copy_diff.isEnabled()
        w.issues.try_experiment.click();r=w.recommendation_runner
        assert r.prepared.rtl_rewrite and r.yosys.isVisible() and w.stack.currentIndex()==8
        assert 'EQUIVALENCE GATE' in r.preview.toPlainText() and 'Default' in r.heading.text()
        assert r.tabs.isTabVisible(r.diff_index) and '--- baseline/design.sv' in r.diff.toPlainText()
        diff=r.diff.toPlainText()
        before=r.preview.toPlainText();r.yosys.setText('/retained/formal-tool');r.output.setText('/retained/output')
        for dark in (False,True):
            w.set_theme(dark);app.processEvents()
            assert r.preview.toPlainText()==before and r.yosys.text()=='/retained/formal-tool' and r.output.text()=='/retained/output'
            assert r.diff.toPlainText()==diff
        w.issues.select_experiment('vivado.remap');w.issues.try_experiment.click()
        assert not r.yosys.isVisible() and not r.prepared.rtl_rewrite
        assert not r.tabs.isTabVisible(r.diff_index)
    finally:w.close();app.processEvents()


def test_missing_equivalence_tool_is_a_visible_failure_without_vivado(tmp_path,monkeypatch,recommendation_factory):
    pytest.importorskip('PySide6');monkeypatch.setenv('QT_QPA_PLATFORM','offscreen');monkeypatch.setenv('TIMINGLENS_REPO_ROOT',str(tmp_path))
    from PySide6.QtWidgets import QApplication
    from timinglens.gui.app import MainWindow
    from timinglens.experiments import recommendation_runner as backend
    monkeypatch.setattr(backend,'execute',lambda *_:pytest.fail('Missing proof tool must not launch any process'))
    app=QApplication.instance() or QApplication([]);w=MainWindow(app);w.show()
    try:
        w.set_result(recommendation_factory('priority')[0]);w.issues.select_experiment('rtl.priority_balanced');w.issues.try_experiment.click()
        r=w.recommendation_runner;r.output.setText(str(tmp_path/'jobs'));r.yosys.setText(str(tmp_path/'does-not-exist'))
        r.start_button.click();wait(app,lambda:r.thread is not None)
        assert 'failed' in r.status.text().lower() and 'Yosys 0.69 is required' in r.log.toPlainText()
        assert w.lab.result is None and not r.registers.isEnabled()
        assert list((tmp_path/'jobs').glob('*/equivalence/equivalence.ys'))
    finally:w.close();app.processEvents()
