from pathlib import Path
import time

import pytest

from timinglens import Session, analyze
from timinglens.service import export_result
from timinglens.timing.models import Arc, Cell, Net, Pin, Source, SourceLink, TimingPath


def test_desktop_open_jump_to_source_filters_and_theme(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("TIMINGLENS_REPO_ROOT", str(tmp_path))
    from PySide6.QtWidgets import QApplication
    from timinglens.gui.app import MainWindow

    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    source = Source(path="tree.sv", text="module m(input a, output b);\n assign b = a;\nendmodule\n")
    link = SourceLink(file=source.path, first_line=2, last_line=2, provenance="vivado_cell_file_name_line_number")
    cell = Cell(name="g", primitive="LUT1", source=link)
    pins = {
        p.name: p for p in (
            Pin(name="a", port=True, direction="IN"), Pin(name="g/I0", cell="g", direction="IN"),
            Pin(name="g/O", cell="g", direction="OUT"), Pin(name="b", port=True, direction="OUT"))
    }
    nets = {"a": Net(name="a", drivers=["a"], sinks=["g/I0"]), "b": Net(name="b", drivers=["g/O"], sinks=["b"])}
    arcs = [
        Arc(source="a", sink="g/I0", resource="a", kind="net", delay_ns=.3),
        Arc(source="g/I0", sink="g/O", resource="g", kind="cell", delay_ns=.2),
        Arc(source="g/O", sink="b", resource="b", kind="net", delay_ns=.5),
    ]
    path = TimingPath(id="P1", analysis="setup", cells=["g"], pins=list(pins), nets=list(nets), arcs=arcs,
                      startpoint="a", endpoint="b", slack_ns=-1.0)
    session = Session(name="test", stage="routed", top="m", sources=[source], paths=[path], cells={"g": cell},
                      pins=pins, nets=nets)
    export_result(analyze(session), tmp_path / "exports")
    window = MainWindow(app)
    window.show()
    window.start_work(session=tmp_path / "exports" / "analysis.json")
    deadline = time.monotonic() + 5
    while window.thread and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    try:
        assert window.result and window.result.failing_paths == 1
        assert window.stack.currentIndex() == 0 and window.dark
        window.show_path("P1")
        assert window.paths.proxy.rowCount() == 1
        assert window.paths.graph.scene().items()
        node = next(item for item in window.paths.graph.scene().items() if item.data(0) == "cell")
        node.setSelected(True)
        assert "LUT1" in window.paths.properties.toPlainText()
        window.paths.open_rtl.click()
        assert window.stack.currentIndex() == 3
        assert "Vivado source tag" in window.source.evidence.text()
        assert "not a proven critical expression" in window.source.evidence.text()
        assert len(window.source.editor.extraSelections()) == 1
        window.source.search.setText("assign")
        window.source.find()
        assert window.source.editor.textCursor().selectedText() == "assign"
        window.navigate(1)
        window.paths.low.setText("0")
        assert window.paths.proxy.rowCount() == 0
        window.toggle_theme()
        assert not window.dark and window.paths.low.text() == "0"
    finally:
        window.close()
        app.processEvents()
    reopened = MainWindow(app)
    try:
        assert not reopened.dark
        assert (tmp_path / ".settings" / "gui.json").is_file()
    finally:
        reopened.close()
