"""Real Qt document checks for incremental formatting and evidence preservation."""
import pytest


@pytest.fixture
def desktop(monkeypatch, tmp_path):
    pytest.importorskip('PySide6')
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('TIMINGLENS_REPO_ROOT', str(tmp_path))
    from PySide6.QtWidgets import QApplication
    from timinglens.gui.theme import apply_theme
    app = QApplication.instance() or QApplication([])
    apply_theme(app, True)
    return app


def format_at(editor, line, token):
    from PySide6.QtGui import QTextCharFormat
    block = editor.document().findBlockByNumber(line)
    position = len(block.text()[:block.text().index(token)].encode('utf-16-le')) // 2
    return next(QTextCharFormat(item.format) for item in block.layout().formats() if item.start <= position < item.start + item.length)


def test_diff_highlights_both_sources_without_changing_copied_evidence(desktop):
    from timinglens.gui.widgets import text_area
    from timinglens.gui.theme import DARK, LIGHT, apply_theme
    editor = text_area('diff')
    value = '--- before.sv\n+++ after.sv\n@@ -1,4 +1,4 @@\n-/* removed comment\n+assign y = 1; // 😀 literal\n-assign still_comment = 0;\n-*/\n+/* added comment\n+continued */ assign z = 2;\n assign q = "// not a comment";'
    editor.setPlainText(value)
    editor.syntax_highlighter.rehighlight()
    assert format_at(editor, 4, 'assign').foreground().color().name() == DARK['keyword']
    assert format_at(editor, 4, 'assign').background().color().name() == DARK['diff_add_bg']
    assert format_at(editor, 5, 'assign').foreground().color().name() == DARK['comment']
    assert format_at(editor, 8, 'assign').foreground().color().name() == DARK['keyword']
    assert format_at(editor, 9, '//').foreground().color().name() == DARK['literal']
    cursor = editor.textCursor(); cursor.setPosition(12); editor.setTextCursor(cursor)
    apply_theme(desktop, False)
    assert editor.toPlainText() == value and editor.textCursor().position() == 12
    assert format_at(editor, 4, 'assign').foreground().color().name() == LIGHT['keyword']
    assert format_at(editor, 4, 'assign').background().color().name() == LIGHT['diff_add_bg']
    editor.close()


def test_incremental_log_severity_and_all_runner_views(desktop):
    from timinglens.gui.app import MainWindow
    from timinglens.gui.theme import DARK
    w = MainWindow(desktop)
    try:
        log = w.recommendation_runner.log
        log.setPlainText('INFO: [Common 17-206] Starting route\n0 errors, 0 warnings')
        log.appendPlainText('WARNING: high fanout\nCRITICAL WARNING: missing constraint\nERROR: build failed\nEquivalence PASSED')
        log.syntax_highlighter.rehighlight()
        assert format_at(log, 1, '0').foreground().color().name() != DARK['bad']
        assert format_at(log, 2, 'WARNING').foreground().color().name() == DARK['warning']
        assert format_at(log, 3, 'CRITICAL').foreground().color().name() == DARK['bad']
        assert format_at(log, 4, 'ERROR').foreground().color().name() == DARK['bad']
        assert format_at(log, 5, 'PASSED').foreground().color().name() == DARK['success']
        for area in [w.recommendation_runner.diff,w.counter_runner.preview,w.counter_runner.log,w.lab.change,w.execution.log]:
            assert area.syntax_highlighter.document() is area.document()
    finally:
        w.close();desktop.processEvents()


def test_recommendation_snippets_and_mixed_lab_evidence(desktop):
    from timinglens.gui.app import MainWindow
    from timinglens.gui.theme import DARK, LIGHT, apply_theme

    w = MainWindow(desktop)
    try:
        preview = w.issues.preview
        preview.setHtml('<p>Keep this explanation.</p><pre>+if ((|remaining[31:4]) || ready)</pre>')
        preview.syntax_highlighter.rehighlight()
        assert not preview.document().firstBlock().layout().formats()
        for token, role in [('if', 'keyword'), ('remaining', 'identifier'), ('31', 'literal'), ('||', 'operator')]:
            assert format_at(preview, 1, token).foreground().color().name() == DARK[role]
        lab = w.lab
        cases = [('Provenance', '{"passed": true}', 'passed', 'keyword'),
                 ('Attachment / run.log', 'ERROR: failed to route', 'ERROR', 'bad'),
                 ('Attachment / change.patch', '+++ batch.tcl\n@@ hunk @@\n+set x [get_ports clk]', 'get_ports', 'keyword'),
                 ('Source / timing.xdc', 'create_clock -period 4 [get_ports clk]', '-period', 'identifier'),
                 ('Report / setup-paths.rpt', '   slack      -0.633', '-0.633', 'bad'),
                 ('Source / control.vhd', 'ready <= a and b; -- handshake', 'and', 'keyword'),
                 ('Source / system.bd', '{"design": {}}', 'design', 'keyword'),
                 ('Source / counter.sv', 'assign x = remaining >= 2;', '>=', 'operator')]
        lab.evidence_items = [(name, data) for name, data, _, _ in cases]
        lab.evidence_file.clear()
        lab.evidence_file.addItems([row[0] for row in cases])
        for i, (_, value, token, role) in enumerate(cases):
            lab.evidence_file.setCurrentIndex(i)
            lab.evidence.syntax_highlighter.rehighlight()
            assert lab.evidence.toPlainText() == value
            assert format_at(lab.evidence, value.count('\n'), token).foreground().color().name() == DARK[role]
        apply_theme(desktop, False)
        assert format_at(preview, 1, 'remaining').foreground().color().name() == LIGHT['identifier']
        assert lab.evidence.toPlainText() == cases[-1][1]
    finally:
        w.close()
        desktop.processEvents()
