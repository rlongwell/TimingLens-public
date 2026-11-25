import json

import pytest


def test_automatic_setting_survives_restart_and_drives_native_project_request(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM","offscreen")
    monkeypatch.setenv("TIMINGLENS_REPO_ROOT",str(tmp_path))
    from PySide6.QtWidgets import QApplication
    from timinglens.experiments.auto_fix import AutoRequest
    from timinglens.gui.app import MainWindow
    from timinglens.gui.pages import Execution

    app = QApplication.instance() or QApplication([])
    window = MainWindow(app)
    window.execution.auto_mode.setCurrentIndex(window.execution.auto_mode.findData("source"))
    assert not window.execution.resource_limit.isEnabled()
    window.execution.balance_resources.setChecked(True)
    window.execution.resource_limit.setValue(78)
    assert json.loads((tmp_path/".settings/gui.json").read_text())["auto_fix_mode"] == "source"
    window.close()
    reopened = MainWindow(app)
    assert reopened.execution.auto_mode.currentData() == "source"
    assert reopened.execution.balance_resources.isChecked() and reopened.execution.resource_limit.value() == 78
    reopened.close()
    panel = Execution()
    requests = []
    panel.requested.connect(requests.append)
    panel.output.setText(str(tmp_path))
    panel.input.setText(str(tmp_path/"demo.xpr"))
    panel.auto_mode.setCurrentIndex(panel.auto_mode.findData("source"))
    panel.balance_resources.setChecked(True)
    panel.resource_limit.setValue(80)
    panel.start.click()
    req, = requests
    assert isinstance(req, AutoRequest) and req.apply_to_source and req.output.parent == tmp_path
    assert req.resource_limit == 80
    assert not panel.build.isEnabled() and "apply" in panel.start.text()
    panel.input.setText(str(tmp_path/"routed.dcp"))
    assert not panel.auto_mode.isEnabled() and panel.start.text() == "Run analysis"
    panel.close()


def test_block_recommendation_opens_the_automatic_project_workflow(tmp_path,monkeypatch):
    from types import SimpleNamespace
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM","offscreen")
    monkeypatch.setenv("TIMINGLENS_REPO_ROOT",str(tmp_path))
    from PySide6.QtWidgets import QApplication, QFileDialog
    from timinglens.gui.app import MainWindow
    app = QApplication.instance() or QApplication([])
    window = MainWindow(app)
    xpr = tmp_path/"original.xpr"
    monkeypatch.setattr(QFileDialog,"getOpenFileName",lambda *a,**kw:(str(xpr),""))
    window.issues.current_plan = SimpleNamespace(id="bd.multiplier_dsp")
    window.issues._update_experiment()
    assert window.issues.try_experiment.isEnabled() and window.issues.try_experiment.text()=="Run from project…"
    window.issues.try_experiment.click()
    assert window.execution.input.text()==str(xpr) and window.execution.auto_mode.currentData()=="copy"
    assert window.stack.currentIndex()==4 and not window.thread
    window.close()
