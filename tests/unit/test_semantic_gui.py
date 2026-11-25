"""Review flow: captured source, independent diffs, filters and portable exports."""
import json
import time

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from timinglens import analyze
from timinglens.service import export_result
from timinglens.timing.io import write_session
from test_semantic_review import session


def test_diff_source_navigation_filter_and_export(tmp_path, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('TIMINGLENS_REPO_ROOT', str(tmp_path))
    from timinglens.gui.app import MainWindow
    app = QApplication.instance() or QApplication([])
    window = MainWindow(app); window.show()
    try:
        result = analyze(session()); window.set_result(result); window.navigate(2)
        assert window.issues.tree.topLevelItemCount() == 1
        assert window.issues.current_plan.id == 'rtl.compare_enable'
        assert window.issues.details.isTabEnabled(3)
        window.issues.details.setCurrentIndex(3)
        assert 'remaining >= amount' in window.issues.preview.toPlainText()
        window.issues.copy_diff.click()
        assert '@@' in app.clipboard().text() and '+  else if' in app.clipboard().text()
        window.issues._source_link(QUrl('tl-source:0'))
        assert window.stack.currentIndex() == 3
        assert window.source.active_range[0] == 6
        window.navigate(2); window.toggle_theme()
        assert window.issues.details.currentIndex() == 3
        window.issues.filter.setText('no such path')
        assert window.issues.tree.currentItem() is None
        assert not window.issues.open.isEnabled()
        window.issues.filter.clear()
        assert window.issues.current_plan.id == 'rtl.compare_enable'
        parent=window.issues.tree.topLevelItem(0);parent.setExpanded(True)
        window.issues.tree.setCurrentItem(parent.child(0));window.issues.tree.setFocus()
        QTest.keyClick(window.issues.tree,Qt.Key.Key_Return);app.processEvents()
        assert window.stack.currentIndex()==1
        export_result(result, tmp_path/'export')
        doc = json.loads((tmp_path/'export/diagnostics.json').read_text())
        assert doc['schema_version'] == 2 and len(doc['investigations']) == 1
        plan = doc['investigations'][0]['plans'][0]
        assert plan['changes'][0]['unified_diff'] == app.clipboard().text()
        assert plan['rule_version'] == '2' and plan['unknowns']
        html = (tmp_path/'export/report.html').read_text()
        assert 'Source hashes' in html and 'Original: remaining &gt;= amount' in html
        assert 'href="#path-P1"' in html
    finally:
        window.close();app.processEvents()


def test_background_semantic_work_keeps_event_loop_alive(tmp_path, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    monkeypatch.setenv('TIMINGLENS_REPO_ROOT',str(tmp_path))
    from timinglens.gui.app import MainWindow
    from timinglens.rtl.bounded import BoundedSemanticIndex
    original = BoundedSemanticIndex._run
    def delayed(self):
        time.sleep(.3)
        original(self)
    monkeypatch.setattr(BoundedSemanticIndex,'_run',delayed)
    path=tmp_path/'input.json';write_session(path,session())
    app=QApplication.instance() or QApplication([])
    window=MainWindow(app);window.show()
    heartbeats=[];timer=QTimer();timer.timeout.connect(lambda:heartbeats.append(time.monotonic()));timer.start(10)
    try:
        window.start_work(session=path)
        deadline=time.monotonic()+8
        while window.thread and time.monotonic()<deadline:
            app.processEvents();time.sleep(.005)
        assert window.result and not window.thread
        assert len(heartbeats) >= 15
        assert 'investigations' in window.result.__dict__
        assert window.issues.current_plan.changes
    finally:
        timer.stop();window.close();app.processEvents()


def test_invalid_project_input_keeps_previous_result_and_returns_to_files(tmp_path,monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    monkeypatch.setenv('TIMINGLENS_REPO_ROOT',str(tmp_path))
    from timinglens.gui.app import MainWindow
    app=QApplication.instance() or QApplication([]);window=MainWindow(app);window.show()
    previous=analyze(session());window.set_result(previous)
    source=tmp_path/'source_only.sv';source.write_text('module x; endmodule')
    try:
        window.start_work(inspection={'paths':[source]})
        deadline=time.monotonic()+5
        while window.thread and time.monotonic()<deadline:
            app.processEvents();time.sleep(.005)
        assert window.result is previous and window.stack.currentIndex()==5
        assert 'No supported Vivado' in window.footer.text()
    finally:
        window.close();app.processEvents()
