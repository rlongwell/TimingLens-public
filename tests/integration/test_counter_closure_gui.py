import pytest


def test_counter_clock_label_and_preview_follow_profile_across_theme_changes(monkeypatch):
    pytest.importorskip('PySide6')
    from PySide6.QtWidgets import QApplication
    from timinglens.gui.counter_runner import CounterRunner
    from timinglens.gui.theme import apply_theme
    app=QApplication.instance() or QApplication([])
    widget=CounterRunner({'example':'counter32_250'})
    try:
        assert widget.example.currentData()=='counter32_250'
        assert '4 ns clock' in widget.budget.text()
        preview=widget.preview.toPlainText()
        for dark in (False,True):
            apply_theme(app,dark)
            assert widget.preview.toPlainText()==preview
            assert '4 ns clock' in widget.budget.text()
        widget.example.setCurrentIndex(widget.example.findData('counter32'))
        assert '2 ns clock' in widget.budget.text()
        assert widget.start_button.isEnabled()
    finally:widget.close()
