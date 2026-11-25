"""Vivado discovery and isolated, cancellable batch execution on Linux."""
from __future__ import annotations

from dataclasses import dataclass, field
from importlib.resources import files
import os
import codecs
from pathlib import Path
import re
import shutil
import signal
from selectors import DefaultSelector, EVENT_READ
import subprocess
from tempfile import TemporaryDirectory, mkdtemp
from threading import Event
from time import monotonic
from typing import Callable

from ..timing.models import Session
from .decode import decode

Log = Callable[[str], None]
DEFAULT_PART = "xc7z020clg400-1"


class VivadoError(RuntimeError):
    pass


class Cancelled(VivadoError):
    pass


@dataclass(frozen=True)
class Request:
    kind: str
    input: Path
    output: Path
    vivado: str | None = None
    run: str = ""
    build: str = "none"
    part: str = DEFAULT_PART
    top: str = ""
    xdc: Path | None = None
    max_paths: int = 100
    paths_per_endpoint: int = 3
    sources: list[Path] = field(default_factory=list)
    embed_sources: bool = True

    def validate(self) -> None:
        extensions = {"checkpoint": ".dcp", "project": ".xpr", "demo": ".sv"}
        if self.kind not in extensions or self.input.suffix.lower() != extensions[self.kind]:
            raise VivadoError(f"Expected a valid {self.kind} input")
        if not self.input.is_file():
            raise VivadoError(f"Input file does not exist: {self.input}")
        if not 1 <= self.max_paths <= 10000 or not 1 <= self.paths_per_endpoint <= 100:
            raise VivadoError("Path limits must be 1–10000 overall and 1–100 per endpoint")
        if self.build not in {"none", "synth", "route"} or (self.kind == "checkpoint" and self.build != "none"):
            raise VivadoError("Builds are supported only for projects and examples")
        if self.run and self.kind != "project":
            raise VivadoError("Run selection requires a Vivado project")
        if self.kind == "demo" and (not self.top or self.xdc is None or not self.xdc.is_file()):
            raise VivadoError("An example requires a top module and an XDC file")
        for source in self.sources:
            if not source.is_file():
                raise VivadoError(f"Source file does not exist: {source}")


def discover(configured: str | None = None) -> Path:
    explicit = configured or os.environ.get("TIMINGLENS_VIVADO")
    if explicit:
        candidate = Path(shutil.which(explicit) or explicit).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.absolute()
        raise VivadoError(f"Configured Vivado executable is unavailable: {explicit}")
    paths = []
    if root := os.environ.get("XILINX_VIVADO"):
        paths.append(Path(root) / "bin" / "vivado")
    if executable := shutil.which("vivado"):
        paths.append(Path(executable))
    for root in (Path("/opt/amd/xilinx"), Path("/opt/Xilinx"), Path("/tools/Xilinx"), Path.home() / "Xilinx"):
        paths.extend(sorted(root.glob("Vivado/*/bin/vivado"), reverse=True))
    for path in paths:
        if path.is_file() and os.access(path, os.X_OK):
            return path.absolute()
    raise VivadoError("Vivado was not found. Set TIMINGLENS_VIVADO or supply --vivado.")


def version(executable: Path) -> str:
    try:
        result = subprocess.run([str(executable), "-version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise VivadoError(f"Unable to query Vivado at {executable}: {error}") from error
    match = re.search(r"[Vv]ivado\s+v?([0-9]+\.[0-9]+(?:\.[0-9]+)?)", result.stdout)
    if result.returncode or not match:
        raise VivadoError(f"Vivado version probe failed at {executable}: {result.stderr.strip()}")
    return match[1]


def _terminate(process: subprocess.Popen, sig: signal.Signals) -> None:
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        pass


def _execute(executable: Path, work: Path, log: Log, cancel: Event, timeout: float | None = None) -> None:
    if cancel.is_set():
        raise Cancelled("Vivado operation cancelled before launch")
    command = [str(executable), "-mode", "batch", "-nolog", "-nojournal", "-source", "batch.tcl"]
    try:
        process = subprocess.Popen(command, cwd=work, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   start_new_session=True)
    except OSError as error:
        raise VivadoError(f"Could not start {executable}: {error}") from error
    deadline = monotonic() + timeout if timeout is not None else None
    stopping = None
    exited = None
    expired = False
    pending = ""
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    log_file = work / "vivado.log"
    try:
        with process.stdout as pipe, DefaultSelector() as poller, log_file.open(
            "w", encoding="utf-8", buffering=1
        ) as stream:
            os.set_blocking(pipe.fileno(), False)
            poller.register(pipe, EVENT_READ)
            while True:
                now = monotonic()
                expired = expired or (deadline is not None and now >= deadline)
                if (cancel.is_set() or expired) and stopping is None:
                    stopping = now
                    _terminate(process, signal.SIGTERM)
                if stopping is not None and now - stopping > 5:
                    _terminate(process, signal.SIGKILL)
                    break
                if process.poll() is not None and exited is None:
                    exited = now
                ready = poller.select(.1)
                if not ready:
                    if exited is not None and now - exited > 1:
                        break
                    continue
                try:
                    chunk = os.read(pipe.fileno(), 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    break
                decoded = decoder.decode(chunk)
                stream.write(decoded)
                lines = (pending + decoded).split("\n")
                pending = lines.pop()
                for line in lines:
                    log(line.rstrip("\r"))
                if len(pending) > 262144:
                    log(pending)
                    pending = ""
            pending += decoder.decode(b"", final=True)
            if pending:
                log(pending)
        status = process.wait(timeout=10)
    except subprocess.TimeoutExpired as error:
        raise VivadoError(f"Vivado did not exit after closing its output. See {log_file}") from error
    finally:
        if process.poll() is None or stopping is not None:
            _terminate(process, signal.SIGKILL)
            process.wait(timeout=10)
    if expired:
        raise VivadoError(f"Vivado timed out. See {log_file}")
    if cancel.is_set():
        raise Cancelled(f"Vivado operation cancelled. See {log_file}")
    if status:
        raise VivadoError(f"Vivado exited with status {status}. See {log_file}")


def _prepare(work: Path, values: tuple) -> None:
    for name in ("batch.tcl", "extract.tcl"):
        (work / name).write_bytes(files("timinglens.vivado").joinpath(name).read_bytes())
    (work / "request.tsv").write_text("".join(f"{str(value).encode().hex()}\n" for value in values), encoding="ascii")


def run(request: Request, log: Log = lambda _: None, cancel: Event | None = None) -> tuple[Session, Path]:
    request.validate()
    executable = discover(request.vivado)
    output = request.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    work = Path(mkdtemp(prefix="vivado-", dir=output))
    source = request.input.resolve()
    _prepare(work, (request.kind, source, source.parent.name if request.kind == "demo" else source.stem,
                    request.run, request.build, request.max_paths, request.paths_per_endpoint,
                    request.part, request.top, request.xdc.resolve() if request.xdc else ""))
    log(f"TimingLens: using {executable}")
    log(f"TimingLens: batch folder {work}")
    _execute(executable, work, log, cancel or Event())
    if not (work / "records.tsv").is_file():
        raise VivadoError(f"Vivado did not produce structured timing data. See {work / 'vivado.log'}")
    try:
        session = decode(work, request.max_paths, request.paths_per_endpoint, request.build,
                         request.sources + ([source] if request.kind == "demo" else []), request.embed_sources)
    except (OSError, ValueError) as error:
        raise VivadoError(f"Could not decode timing evidence in {work}: {error}") from error
    return session, work


def probe(executable: Path, part: str = DEFAULT_PART) -> dict[str, bool]:
    result = {}
    with TemporaryDirectory(prefix="timinglens-doctor-") as folder:
        work = Path(folder)
        _prepare(work, ("doctor", "", "", "", "none", 1, 1, part))
        lines: list[str] = []
        _execute(executable, work, lines.append, Event(), timeout=90)
        for line in lines:
            if match := re.fullmatch(r"TIMINGLENS_COMMAND (\w+) ([01])", line):
                result[match[1]] = match[2] == "1"
            elif match := re.fullmatch(r"TIMINGLENS_PART ([01])", line):
                result[part] = match[1] == "1"
        if part not in result or "get_timing_paths" not in result:
            raise VivadoError("Vivado did not return command and device probe results")
    return result
