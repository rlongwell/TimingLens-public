import json
from pathlib import Path
import time
from threading import Event, Thread

import pytest

from timinglens import Session, Thresholds, analyze, read_session
from timinglens.cli import main
from timinglens.service import export_result
from timinglens.vivado.runner import Cancelled, VivadoError, _execute, discover


def test_analysis_export_and_cli_import(tmp_path):
    data = analyze(Session(name="<test & example>"), Thresholds(fanout=17))
    first = tmp_path / "first"
    export_result(data, first)
    assert "&lt;test &amp; example&gt;" in (first / "report.html").read_text()
    assert read_session(first / "analysis.json").rule_thresholds["fanout"] == 17
    assert json.loads((first / "diagnostics.json").read_text())["thresholds"]["fanout"] == 17
    second = tmp_path / "second"
    assert main(["import", "--report", str(first / "analysis.json"), "--output", str(second)]) == 0
    assert (second / "diagnostics.json").read_bytes() == (first / "diagnostics.json").read_bytes()
    assert main(["import", "--report", str(first / "analysis.json"), "--output", str(first)]) == 1
    assert read_session(first / "analysis.json").name == "<test & example>"
    assert main(["analyze", "--checkpoint", "missing.dcp", "--output", str(tmp_path)]) == 1


def test_unsupported_session_version(tmp_path):
    bad = tmp_path / "analysis.json"
    bad.write_text('{"schema_version":99,"name":"unknown"}')
    assert main(["import", "--report", str(bad)]) == 1


def shell(path: Path, source: str) -> Path:
    path.write_text("#!/usr/bin/env bash\n" + source)
    path.chmod(0o700)
    return path


def test_vivado_process_log_and_failure(tmp_path):
    fake = shell(tmp_path / "fake vivado", 'printf "batch stdout\\n"; printf "batch stderr\\n" >&2\nexit 7\n')
    lines = []
    with pytest.raises(VivadoError, match="status 7"):
        _execute(fake, tmp_path, lines.append, Event())
    assert discover(str(fake)) == fake
    assert lines == ["batch stdout", "batch stderr"]
    assert (tmp_path / "vivado.log").read_text() == "batch stdout\nbatch stderr\n"


def test_vivado_cancels_without_waiting_for_quiet_process(tmp_path):
    fake = shell(tmp_path / "vivado", "sleep 40 &\necho ready\nwait\n")
    started = Event()
    cancel = Event()
    errors = []
    def execute():
        try:
            _execute(fake, tmp_path, lambda line: started.set(), cancel)
        except VivadoError as error:
            errors.append(error)
    worker = Thread(target=execute)
    worker.start()
    try:
        assert started.wait(5)
        then = time.monotonic()
        cancel.set()
        worker.join(7)
        assert not worker.is_alive() and time.monotonic() - then < 7
        assert len(errors) == 1 and isinstance(errors[0], Cancelled)
    finally:
        cancel.set()
        worker.join(7)
