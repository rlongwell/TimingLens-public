"""Map failing fabric arithmetic to an actual IP Integrator Multiplier Generator."""
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re

from .fixes import CHECKS, Evidence, FixPlan, Location, dfx_scope, internal_clock_path

RULE = "bd.multiplier_dsp"
VLNV = "xilinx.com:ip:mult_gen:12.0"
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True)
class Multiplier:
    file: str
    digest: str
    design: str
    cell: str
    module: str
    a: int
    b: int
    latency: int
    line: int
    construction: str = "Use_LUTs"


def configurations(source, *, both_mappings=False):
    if (Path(source.path).suffix.lower() != ".bd" or not source.text or
            sha256(source.text.encode()).hexdigest() != source.sha256):
        return
    try:
        design = json.loads(source.text)["design"]
        name = design["design_info"]["name"]
        components = design["components"]
        if not isinstance(name, str) or not IDENT.fullmatch(name) or not isinstance(components, dict):
            return
        for cell, item in components.items():
            if item.get("vlnv") != VLNV or not IDENT.fullmatch(cell):
                continue
            module = item.get("xci_name", "")
            if not IDENT.fullmatch(module):
                continue
            params = {key: v["value"] for key, v in item.get("parameters", {}).items()}
            construction = params.get("Multiplier_Construction", "Use_LUTs")
            supported = {"Use_LUTs", "Use_Mults"} if both_mappings else {"Use_LUTs"}
            if (construction not in supported or
                    params.get("MultType", "Parallel_Multiplier") != "Parallel_Multiplier" or
                    any(params.get(key) != "Unsigned" for key in ("PortAType", "PortBType")) or
                    any(str(params.get(key, "false")).lower() != "false" for key in
                        ("Use_Custom_Output_Width", "ClockEnable", "SyncClear", "UseRounding", "ZeroDetect"))):
                continue
            a, b, latency = (int(params.get(key, default)) for key, default in
                             (("PortAWidth", 18), ("PortBWidth", 18), ("PipeStages", 1)))
            if 2 <= a <= 64 and 2 <= b <= 64 and 1 <= latency <= 16:
                components_start = source.text.find('"components"')
                token = re.search(r'"' + re.escape(cell) + r'"\s*:\s*\{', source.text[components_start:])
                line = 1 + source.text.count("\n", 0, components_start + token.start()) if token else 1
                yield Multiplier(source.path, source.sha256, name, cell, module, a, b, latency, line, construction)
    except (ValueError, TypeError, KeyError, AttributeError):
        return


def _owner(cell, session, ips):
    visited = set()
    while cell and cell.name not in visited:
        visited.add(cell.name)
        if cell.hierarchical:
            matches = [ip for ip in ips if ip.module in (cell.primitive, cell.original_ref)]
            if len(matches) == 1:
                return matches[0], cell.name
        cell = session.cells.get(cell.parent)
    return None


def _fabric_evidence(result, path, ips):
    session = result.session
    coverage = result.coverage[path.id]
    if not coverage.expected_links or coverage.captured_links != coverage.expected_links:
        return None
    fabric = {}
    for arc in path.arcs:
        cell = session.cells.get(arc.resource)
        if arc.kind == "cell" and cell and cell.primitive.startswith(("LUT", "CARRY")):
            owner = _owner(cell, session, ips)
            if owner:
                fabric.setdefault(owner, []).append(arc)
    for (ip, instance), arcs in sorted(fabric.items(), key=lambda row: len(row[1]), reverse=True):
        cells = tuple(dict.fromkeys(arc.resource for arc in arcs))
        if len(cells) < 2:
            continue
        if coverage.complete:
            delay = sum(arc.delay_ns for arc in arcs)
            description = f"{delay:.3f} ns of measured LUT/carry delay inside {ip.module}"
        else:
            # Some vendor reports suppress pin names. Use the native whole-path
            # figure only when every ordered pin belongs to one physical instance.
            pins = [session.pins.get(name) for name in (path.startpoint, *path.pins, path.endpoint)]
            if not path.logic_ns or not all(pin and _owner(session.cells.get(pin.cell), session, ips)
                                            == (ip, instance) for pin in pins):
                continue
            delay = path.logic_ns
            description = (f"{delay:.3f} ns total logic delay on a path wholly inside {instance}, "
                           f"including {len(cells)} LUT/carry cells")
        if delay >= abs(path.slack_ns) * 0.25:
            return ip, cells, description
    return None


def candidates(result):
    session = result.session
    ips = [ip for source in session.sources for ip in configurations(source)]
    if not ips or session.stage != "routed" or dfx_scope(result):
        return {}
    found = {}
    for path in session.paths:
        if (path.analysis != "setup" or path.slack_ns is None or path.slack_ns >= 0 or
                not internal_clock_path(session, path)):
            continue
        match = _fabric_evidence(result, path, ips)
        if not match:
            continue
        ip, cells, description = match
        here = Location(ip.file, ip.line, ip.line, f"{ip.design}/{ip.cell} • {ip.module}")
        measured = Evidence(f"{path.id}:multiplier", "measured",
                            f"{path.id} has {path.slack_ns:.3f} ns setup slack and {description}.",
                            (path.id,), tuple(cells))
        config = Evidence(f"{path.id}:ip-config", "syntax",
                          f"{ip.design}/{ip.cell} uses LUTs for a {ip.a} × {ip.b} unsigned product with {ip.latency} pipeline stage(s).",
                          (path.id,), (ip.module,), here)
        found[path.id] = FixPlan(RULE, f"Map {ip.design}/{ip.cell} to DSP blocks", "block_design_hypothesis",
            f"{ip.design}/{ip.cell}", (measured.statement, config.statement),
            "The implemented failing path crosses the fabric multiplier. The same Xilinx IP can map the product to dedicated DSP hardware.",
            "Change Multiplier_Construction to Use_Mults in the block design and regenerate the IP.",
            commands=(f"set_property CONFIG.Multiplier_Construction Use_Mults [get_bd_cells {ip.cell}]",
                      "validate_bd_design", "save_bd_design"), checks=CHECKS, source_candidates=(here,),
            evidence_links=(measured, config), next_steps=("Switch the multiplier implementation in an isolated block design.",
                "Check generated ports and pipeline latency, simulate the configured IP, and compare whole-design routes."),
            unknowns=("The candidate build measures available DSP capacity and the resulting timing.",))
    return found
