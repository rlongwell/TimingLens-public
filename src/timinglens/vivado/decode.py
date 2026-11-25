"""Decode the private Tcl transport and join it with verified timing report rows."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
from math import isfinite
from pathlib import Path
import re

from ..timing.models import Arc, Cell, Clock, Net, Pin, Session, Source, SourceLink, TimingPath
from . import reports

HDL_SUFFIXES = {".v", ".sv", ".vh", ".svh", ".vhd", ".vhdl"}
TEXT_SUFFIXES = HDL_SUFFIXES | {".tcl", ".xdc", ".bd", ".xci", ".json", ".mem", ".mif", ".coe", ".hex", ".edf", ".edn"}
MAX_SOURCE_BYTES = 2_000_000
MAX_SOURCE_TOTAL = 24_000_000
PATH_PROPERTIES = (
    "startpoint", "endpoint", "start_clock", "end_clock", "group", "corner", "slack_ns",
    "requirement_ns", "arrival_ns", "required_ns", "datapath_ns", "logic_ns", "routing_ns",
    "skew_ns", "uncertainty_ns", "levels", "path_type", "EXCEPTION", "CLOCK_PESSIMISM",
    "STARTPOINT_CLOCK_DELAY", "ENDPOINT_CLOCK_DELAY", "ROUTABLE_NETS",
)


def number(value: str) -> float | None:
    try:
        result = float(value)
    except ValueError:
        return None
    return result if isfinite(result) else None


def integer(value: str) -> int | None:
    return int(value) if value.isdecimal() else None


def flag(value: str) -> bool | None:
    return {"0": False, "1": True, "false": False, "true": True}.get(value.lower())


def read_rows(path: Path) -> dict[str, list[list[str]]]:
    rows = defaultdict(list)
    with path.open(encoding="ascii") as stream:
        for line in stream:
            record, *fields = line.rstrip("\n").split("\t")
            rows[record].append([bytes.fromhex(field).decode() for field in fields])
    return rows


def children(rows: list[list[str]]) -> dict[str, list[str]]:
    result = defaultdict(list)
    for parent, child in rows:
        if child:
            result[parent].append(child)
    return result


def sources_from(rows: list[list[str]], extra: list[Path], embed: bool) -> list[Source]:
    entries = {str(path.resolve()): "" for path in extra}
    entries.update(rows)
    sources = []
    total = 0
    for name, file_type in sorted(entries.items()):
        path = Path(name)
        data = None
        if path.suffix.lower() in TEXT_SUFFIXES:
            try:
                size = path.stat().st_size
                if size <= MAX_SOURCE_BYTES and total + size <= MAX_SOURCE_TOTAL:
                    data = path.read_bytes()
                    total += len(data)
            except OSError:
                pass
        sources.append(Source(path=name, file_type=file_type, sha256=sha256(data).hexdigest() if data is not None else None,
                              text=data.decode("utf-8", errors="replace") if embed and data is not None else None))
    return sources


def ordered_arcs(
    pin_names: list[str], net_names: list[str], pins: dict[str, Pin], nets: dict[str, Net], detail: str,
) -> list[Arc]:
    rows = reports.detail_rows(detail)
    positions = []
    scan = 0
    for name in pin_names:
        found = next((i for i in range(scan, len(rows)) if rows[i][:2] == ("pin", name)), None)
        positions.append(found)
        if found is not None:
            scan = found + 1

    by_driver = defaultdict(set)
    for name in net_names:
        for driver in nets[name].drivers:
            by_driver[driver].add(name)
    arcs = []
    for index, (src, dst) in enumerate(zip(pin_names, pin_names[1:])):
        src_pin, dst_pin = pins[src], pins[dst]
        first, last = positions[index:index + 2]
        delay = None
        if src_pin.cell and src_pin.cell == dst_pin.cell and src_pin.direction == "IN" and dst_pin.direction == "OUT":
            if last is not None:
                delay = rows[last][2]
            arcs.append(Arc(source=src, sink=dst, kind="cell", resource=src_pin.cell, delay_ns=delay))
            continue
        possible = {name for name in by_driver[src] if dst in nets[name].sinks}
        if first is not None and last is not None:
            for kind, label, elapsed in rows[first + 1:last]:
                if kind != "net":
                    continue
                matches = [name for name in by_driver[src]
                           if (label == name or label in nets[name].aliases)
                           and (name in possible or not nets[name].sinks_complete)]
                if len(matches) == 1:
                    # The anchored path row also verifies a sink omitted from the capped net snapshot.
                    arcs.append(Arc(source=src, sink=dst, kind="net", resource=matches[0], delay_ns=elapsed))
                    break
            else:
                if len(possible) == 1:
                    arcs.append(Arc(source=src, sink=dst, kind="net", resource=possible.pop()))
        elif len(possible) == 1:
            arcs.append(Arc(source=src, sink=dst, kind="net", resource=possible.pop()))
    return arcs


def make_path(row: list[str], path_objects: dict, pins: dict, nets: dict, detail: str) -> TimingPath:
    path_id, analysis, *values = row
    fields = {}
    properties = {}
    for key, value in zip(PATH_PROPERTIES, values, strict=True):
        if key.isupper():
            if value and "unset" not in value:
                properties[key] = value
        elif key.endswith("_ns"):
            fields[key] = number(value)
        elif key == "levels":
            fields[key] = integer(value)
        else:
            fields[key] = value or None
    pin_names = list(path_objects["PPIN"][path_id])
    for key, position in (("startpoint", 0), ("endpoint", len(pin_names))):
        boundary = fields[key]
        if boundary in pins and boundary not in pin_names:
            pin_names.insert(position if key == "startpoint" else len(pin_names), boundary)
    net_names = list(dict.fromkeys(path_objects["PNET"][path_id]))
    arcs = ordered_arcs(pin_names, net_names, pins, nets, detail)
    match = re.search(r"^\s*Path Type:\s*(.+)$", detail, re.MULTILINE)
    if match:
        fields["path_type"] = match[1].strip()
    return TimingPath(id=path_id, analysis=analysis, **fields, properties=properties,
                      pins=pin_names, nets=net_names, cells=path_objects["PCELL"][path_id], arcs=arcs)


def refresh_report_arcs(session: Session) -> Session:
    """Rejoin embedded raw evidence on import, including older parser exports.

    Timing totals and report text remain unchanged. No files or Vivado state are
    consulted; a report must match the existing path's native pin/net objects.
    """
    blocks = {}
    for kind in ("setup", "hold"):
        blocks.update(reports.detail_blocks(session.reports.get(f"{kind}-paths.rpt", "")))
    return session.model_copy(update={"paths": [
        p.model_copy(update={"arcs": ordered_arcs(p.pins, p.nets, session.pins, session.nets, blocks[p.id])})
        if p.id in blocks else p for p in session.paths]})


def decode(folder: Path, max_paths: int, nworst: int, build: str, extra: list[Path], embed: bool) -> Session:
    rows = read_rows(folder / "records.tsv")
    ((session_name, vivado, part, top, origin, run, mode),) = rows["META"]
    sources = sources_from(rows["SOURCE"], extra, embed)
    source_paths = {source.path for source in sources if source.sha256}
    checkpoint_changes = set()
    if mode == "checkpoint":
        checkpoint_time = Path(origin).stat().st_mtime_ns
        for filename in source_paths:
            try:
                if Path(filename).stat().st_mtime_ns > checkpoint_time:
                    checkpoint_changes.add(filename)
            except OSError:
                checkpoint_changes.add(filename)
        source_paths -= checkpoint_changes
    if rows["STALE"]:
        source_paths.clear()
    cells = {}
    extra_properties = defaultdict(dict)
    for name, key, value in rows["CELLPROP"]:
        extra_properties[name][key] = value
    for (key, parent, ref, orig, original_name, loc, bel, init, seq, primitive,
         filename, line, primitive_type, keep, region) in rows["CELL"]:
        filename = str(Path(filename).resolve()) if filename else ""
        link = None
        if filename in source_paths and (line_number := integer(line)) and line_number > 0:
            link = SourceLink(file=filename, first_line=line_number, last_line=line_number,
                              provenance="vivado_cell_file_name_line_number")
        cells[key] = Cell(name=key, primitive=ref, parent=parent or None, original_ref=orig or None,
                          original_name=original_name or None, location=loc or None, bel=bel or None,
                          init=init or None, sequential=flag(seq) is True, hierarchical=flag(primitive) is False,
                          source=link, properties={k: v for k, v in
                              {"PRIMITIVE_TYPE": primitive_type, "DONT_TOUCH": keep, "CLOCK_REGION": region,
                               **extra_properties[key]}.items() if v})
    pins = {key: Pin(name=key, cell=cell or None, port=flag(port) is True, direction=direction or None,
                     ref_pin=ref or None) for key, cell, port, direction, ref in rows["PIN"]}
    details = {p.name: p.read_text(encoding="utf-8", errors="replace") for p in folder.glob("*.rpt")}
    aliases, drivers, sinks = (children(rows[k]) for k in ("ALIAS", "DRIVER", "SINK"))
    nets = {key: Net(name=key, fanout=integer(fanout), sinks_complete=flag(complete) is True,
                     aliases=aliases[key], drivers=drivers[key], sinks=sinks[key],
                     properties={k: v for k, v in {"ROUTE_STATUS": route, "TYPE": kind, "IS_CLOCK": clock}.items() if v})
            for key, fanout, complete, route, kind, clock in rows["NET"]}
    wave, clock_sources = (children(rows[k]) for k in ("WAVE", "CLOCKSOURCE"))
    clocks = [Clock(name=key, period_ns=number(period), waveform_ns=[v for edge in wave[key]
                    if (v := number(edge)) is not None], generated=flag(generated),
                    master=master or None, sources=clock_sources[key])
              for key, period, generated, master in rows["CLOCK"]]
    blocks = {}
    for kind in ("setup", "hold"):
        blocks.update(reports.detail_blocks(details.get(f"{kind}-paths.rpt", "")))
    path_objects = {kind: children(rows[kind]) for kind in ("PPIN", "PCELL", "PNET")}
    paths = [make_path(row, path_objects, pins, nets, blocks.get(row[0], "")) for row in rows["PATH"]]
    summary_text = details.get("timing_summary.rpt", "")
    summary = reports.timing_summary(summary_text)
    warnings = [message for (message,) in rows["WARNING"]]
    totals = Counter(path.analysis for path in paths)
    for kind in ("setup", "hold"):
        if totals[kind] >= max_paths:
            warnings.append(f"The {kind} collection reached the requested limit of {max_paths} paths.")
    if checkpoint_changes:
        warnings.append("Direct attribution suppressed for source files newer than the checkpoint.")
    if not summary:
        warnings.append("Design-wide timing totals unavailable from Vivado's timing summary.")
    return Session(name=session_name, vivado=vivado or None, part=part or None, top=top or None, origin=origin,
                   run=run or None, stage=reports.design_stage(summary_text, details.get("route_status.rpt", ""), build),
                   timestamp=datetime.now(timezone.utc).isoformat(), path_limit_per_type=max_paths,
                   paths_per_endpoint=nworst, sources=sources, cells=cells, pins=pins, nets=nets,
                   clocks=clocks, paths=paths, summary=summary, reports=details,
                   timing_checks=reports.timing_checks(details.get("check_timing.rpt", "")),
                   clock_interactions=reports.clock_interactions(details.get("clock_interaction.rpt", "")),
                   warnings=warnings)
