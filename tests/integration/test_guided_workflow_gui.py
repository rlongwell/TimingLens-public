"""Navigation must stage real inputs without silently starting expensive work."""
from pathlib import Path
from dataclasses import replace
import pytest


def window(tmp_path, monkeypatch):
    pytest.importorskip('PySide6')
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('TIMINGLENS_REPO_ROOT', str(tmp_path))
    from PySide6.QtWidgets import QApplication
    from timinglens.gui.app import MainWindow
    app = QApplication.instance() or QApplication([])
    w = MainWindow(app); w.show(); app.processEvents()
    return app, w


def test_start_routes_files_without_running_and_preserves_edits(tmp_path, monkeypatch):
    app, w = window(tmp_path, monkeypatch)
    try:
        assert w.stack.currentWidget() is w.home
        assert w.details_navigation.isHidden()
        rtl = tmp_path/'design.sv'; rtl.write_text('module design; endmodule')
        xdc = tmp_path/'timing.xdc'; xdc.write_text('')
        w.route_design_files([rtl, xdc])
        assert w.stack.currentWidget() is w.project_files
        assert w.project_files.files.count() == 2 and w.thread is None
        w.project_files.top.setText('unsaved_top')
        w.route_design_files([tmp_path/'design.dcp', rtl])
        assert w.stack.currentWidget() is w.execution
        assert w.execution.extra == [rtl] and not w.execution.build.isEnabled()
        w.route_design_files([tmp_path/'design.xpr'])
        assert w.execution.build.isEnabled() and w.execution.extra == []
        previous = w.execution.input.text()
        w.route_design_files([tmp_path/'a.xpr', tmp_path/'b.dcp'])
        assert w.execution.input.text() == previous and 'one Vivado' in w.footer.text()
        w.home.example.click()
        assert w.stack.currentWidget() is w.counter_runner
        assert w.counter_runner.example.currentData() == 'counter32_250'
        assert w.counter_runner.advanced.isHidden() and w.counter_runner.thread is None
        w.counter_runner.advanced_toggle.click()
        w.counter_runner.timeout.setValue(345)
        w.toggle_theme(); w.toggle_theme()
        assert not w.counter_runner.advanced.isHidden()
        assert w.counter_runner.timeout.value() == 345
        assert w.project_files.top.text() == 'unsaved_top'
        w.counter_runner.thread = object()
        w.tool_activity()
        assert not w.home.example.isEnabled() and not w.add_design.isEnabled()
        w.counter_runner.thread = None; w.tool_activity()
        assert w.home.example.isEnabled()
    finally:
        w.counter_runner.thread = None; w.close(); app.processEvents()


def test_summary_preserves_unknowns_regressions_and_population(tmp_path, monkeypatch):
    from timinglens.experiments import compare
    from timinglens.experiments.capture import from_session
    from timinglens.timing.models import Session, Summary
    app, w = window(tmp_path, monkeypatch)
    try:
        before = from_session(Session(name='before', summary={'setup':Summary(worst_slack_ns=-.5, total_negative_slack_ns=-1., failing_endpoints=2)}))
        after = from_session(Session(name='after', summary={'setup':Summary(worst_slack_ns=.2, total_negative_slack_ns=0., failing_endpoints=0)}))
        result = compare(before, after)
        w.lab.show_result(result)
        assert w.lab.metric_cards['setup.worst_slack_ns'].text() == '-0.500 → +0.200'
        assert w.lab.metric_cards['setup.failing_endpoints'].text() == '2 → 0'
        assert w.lab.metric_cards['area.lut_sites'].text() == 'Not supplied → Not supplied'
        assert 'Still to verify:' in w.lab.next_step.text()
        assert 'Integrated design validation' in w.lab.next_step.text()
        reversed_result = compare(after, before); w.lab.show_result(reversed_result)
        assert 'Next: resolve Setup timing' in w.lab.next_step.text()
        assert w.lab.result.acceptance == reversed_result.acceptance == 'blocked'
    finally:
        w.close(); app.processEvents()


def test_guided_counter_opens_whole_core_but_keeps_register_choice(tmp_path, monkeypatch):
    from timinglens.experiments.runner import CounterResult
    app, w = window(tmp_path, monkeypatch)
    runner = w.counter_runner
    runner.pair_requested.disconnect(w.import_counter_pair)
    pairs=[]; runner.pair_requested.connect(pairs.append)
    try:
        result=CounterResult(tmp_path,(Path('reg-before'),Path('reg-after')),(Path('all-before'),Path('all-after')),'counter32_250')
        runner.completed(result)
        assert pairs[-1] == result.global_pair
        runner.open_pair(False)
        assert pairs[-1] == result.register_pair
        runner.completed(replace(result,example='counter32'))
        assert pairs[-1] == result.register_pair
    finally:
        w.close(); app.processEvents()
