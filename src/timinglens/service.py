"""Shared application entry points for live collection and imported sessions."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event

from .analysis.engine import Analysis, analyze
from .export.diagnostics import write_diagnostics
from .export.html import write_html
from .rules.library import Thresholds
from .timing.io import read_session, write_session
from .vivado.runner import Cancelled, Log, Request, run
from .vivado.decode import refresh_report_arcs
from .inputs import assemble

EXPORTS = ("analysis.json", "report.html", "diagnostics.json")


def _check_output(output: Path) -> None:
    for name in EXPORTS:
        if (output / name).exists() or (output / name).is_symlink():
            raise FileExistsError(f"Output already contains {name}. Choose another directory.")


def export_result(result: Analysis, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    _check_output(output)
    with TemporaryDirectory(prefix=".timinglens-export-", dir=output) as folder:
        draft = Path(folder)
        session = result.session.model_copy(update={"rule_thresholds": result.thresholds.model_dump()})
        write_session(draft / "analysis.json", session)
        write_html(draft / "report.html", result)
        write_diagnostics(draft / "diagnostics.json", result)
        published = []
        try:
            for name in EXPORTS:
                target = output / name
                os.link(draft / name, target)
                published.append(target)
        except OSError:
            for target in published:
                target.unlink(missing_ok=True)
            raise


def collect(request: Request, thresholds: Thresholds | None = None, log: Log = lambda _: None,
            cancel: Event | None = None) -> tuple[Analysis, Path]:
    _check_output(request.output)
    session, work = run(request, log, cancel)
    result = analyze(session, thresholds, trust_manifest_paths=True)
    if cancel is not None and cancel.is_set():
        raise Cancelled(f"Analysis cancelled. See {work / 'vivado.log'}")
    export_result(result, request.output)
    return result, work


def load(path: Path, thresholds: Thresholds | None = None, *, resolve_local_sources: bool = False) -> Analysis:
    return analyze(refresh_report_arcs(read_session(path)), thresholds, trust_manifest_paths=resolve_local_sources)


def inspect_files(paths: list[Path], thresholds: Thresholds | None = None, *, top=None, base=None) -> Analysis:
    return analyze(assemble(paths, top=top, base=base), thresholds)
