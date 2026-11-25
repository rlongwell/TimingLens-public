"""Narrow parsers for report fields without native Vivado object properties."""
from __future__ import annotations

import re

from ..timing.models import Summary

NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"


def timing_summary(text: str) -> dict[str, Summary]:
    section = text.partition("| Design Timing Summary")[2]
    lines = section.splitlines()
    for index, line in enumerate(lines):
        if "WNS(ns)" not in line or "WHS(ns)" not in line:
            continue
        for candidate in lines[index + 1:index + 5]:
            fields = candidate.split()
            if len(fields) != 12 or not all(
                re.fullmatch(NUMBER, value) or value in {"NA", "N/A", "-"} for value in fields
            ):
                continue
            result = {}
            for kind, offset in (("setup", 0), ("hold", 4)):
                worst, total, failing, endpoints = fields[offset:offset + 4]
                result[kind] = Summary(
                    worst_slack_ns=float(worst) if re.fullmatch(NUMBER, worst) else None,
                    total_negative_slack_ns=float(total) if re.fullmatch(NUMBER, total) else None,
                    failing_endpoints=int(failing) if failing.isdecimal() else None,
                    total_endpoints=int(endpoints) if endpoints.isdecimal() else None,
                )
            return result
    return {}


def design_stage(summary: str, route: str, mode: str) -> str:
    state = re.search(r"^\| Design State\s*:\s*(.+)$", summary, re.MULTILINE)
    label = state[1].strip().lower() if state else ""
    if "partial" in label and "rout" in label:
        return "partially_routed"
    if label in {"routed", "fully routed", "implemented"}:
        return "routed" if label != "implemented" else route_stage(route)
    if "synth" in label:
        return "synthesized"
    if "placed" in label:
        return route_stage(route) if route else "placed"
    if mode == "synth":
        return "synthesized"
    return route_stage(route)


def route_stage(text: str) -> str:
    counts = {key.strip().lower(): int(count) for key, count in
              re.findall(r"^\s*# of (.*?)\.+\s*:\s*(\d+)\s*:", text, re.MULTILINE)}
    routable = counts.get("routable nets", 0)
    routed = counts.get("fully routed nets", 0)
    errors = counts.get("nets with routing errors", 0)
    unplaced = counts.get("nets with no placed pins", 0)
    logical = counts.get("logical nets", 0)
    if routed and routed == routable and not errors:
        return "routed"
    if routed or errors:
        return "partially_routed"
    if routable:
        return "placed"
    if logical and unplaced == logical:
        return "synthesized"
    return "unknown"


def timing_checks(text: str) -> dict[str, int]:
    return {name: int(count) for name, count in
            re.findall(r"^\s*\d+\. checking (\w+) \((\d+)\)", text, re.MULTILINE)}


def clock_interactions(text: str) -> list[dict[str, str]]:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if "From Clock" not in line or "Classification" not in line or index + 1 == len(lines):
            continue
        spans = [(m.start(), m.end()) for m in re.finditer(r"-+", lines[index + 1])]
        keys = ("source", "destination", "edges", "worst_slack_ns", "total_negative_slack_ns",
                "failing_endpoints", "total_endpoints", "requirement_ns", "classification", "constraints")
        # The ordinary Vivado 2024.2 table has ten columns.
        if len(spans) != len(keys):
            continue
        return [
            {key: row[start:end].strip() for key, (start, end) in zip(keys, spans)}
            for row in lines[index + 2:] if row.strip() and len(row) >= spans[-1][0]
        ]
    return []


ROW = re.compile(
    rf"^(?P<label>.*?)\s+(?P<inc>{NUMBER})\s+(?P<total>{NUMBER})"
    r"\s+(?:(?P<edge>[rf])\s+)?(?P<name>\S.*?)\s*$"
)
PIN_ROW = re.compile(r"^\s*(?:\S+\s+){0,2}[rf]\s+(\S.*?)\s*$")
CLOCK_SUFFIX = re.compile(r" \((?:IN|OUT|INOUT)\)$")


def detail_rows(text: str) -> list[tuple[str, str, float | None]]:
    """Extract events before the first arrival total, retaining exact resource labels."""
    rows = []
    partition_column = resource_column = None
    for line in text.splitlines():
        if "Incr(ns)" in line and "Netlist Resource" in line:
            # DFX reports add Partition and PBlock between the edge and resource.
            # Keep the native resource spelling (including spaces/escaped names),
            # rather than guessing that the last whitespace token is its name.
            partition_column = line.find("Partition")
            resource_column = line.find("Netlist Resource")
            if partition_column < 0:
                partition_column = resource_column = None
            continue
        if re.search(r"\b(?:data )?arrival time\s*(?:[+-]?\d+\.\d+)?\s*$", line, re.IGNORECASE):
            break
        if partition_column is not None and len(line) >= resource_column:
            line = line[:partition_column] + line[resource_column:]
        match = ROW.match(line)
        if match:
            name = CLOCK_SUFFIX.sub("", match["name"])
            kind = "net" if re.search(r"\bnet\s*\(", match["label"]) else "pin"
            rows.append((kind, name, float(match["inc"])))
        elif (match := PIN_ROW.match(line)):
            rows.append(("pin", CLOCK_SUFFIX.sub("", match[1]), None))
    return rows


def detail_blocks(text: str) -> dict[str, str]:
    fields = re.split(r"^TIMINGLENS_PATH (P\d+)\s*$", text, flags=re.MULTILINE)
    return dict(zip(fields[1::2], fields[2::2]))


def forwarded_clock_outputs(session) -> tuple[str, ...]:
    """Recognize Vivado's verbose LOW forwarded-clock case; missing detail stays unknown."""
    count = session.timing_checks.get("no_output_delay", 0)
    if not count:
        return ()
    report = session.reports.get("check_timing.rpt", "")
    checks = timing_checks(report)
    if (any(checks.get(key) != 0 for key in ("no_clock", "unconstrained_internal_endpoints", "no_input_delay",
                                               "generated_clocks", "multiple_clock", "partial_output_delay"))
            or {key: n for key, n in checks.items() if n} != {"no_output_delay": count}):
        return ()
    sections = re.findall(r"^\d+\. checking no_output_delay \((\d+)\)\s*\n-+\n(.*?)(?=^\d+\. checking |\Z)",
                          report, re.M | re.S)
    if len(sections) != 1 or int(sections[0][0]) != count:
        return ()
    detail = re.fullmatch(
        r"\s*There are 0 ports with no output delay specified\.\s+"
        r"There are 0 ports with no output delay but user has a false path constraint\.?\s+"
        r"There (?:is|are) (\d+) ports? with no output delay but with a timing clock defined on "
        r"it or propagating through it \(LOW\)\s+([\w./\[\]\s-]+)", sections[0][1])
    if not detail or int(detail[1]) != count:
        return ()
    ports = detail[2].split()
    masters = {c.name for c in session.clocks if c.period_ns and c.period_ns > 0}
    forwarded = {s for c in session.clocks if c.generated and c.master != c.name and c.master in masters and c.period_ns and c.period_ns > 0
                 for s in c.sources}
    return tuple(ports) if len(set(ports)) == len(ports) == count and set(ports) <= forwarded else ()
