"""Engineering rule definitions and deterministic predicates."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations, product
from collections import Counter
from functools import lru_cache

from pydantic import Field

from ..netlist.graph import Graph
from ..rtl.correlate import Association, Confidence
from ..timing.models import Record, Session, TimingPath


class Thresholds(Record):
    logic_levels: int = Field(default=8, ge=2)
    min_logic_ns: float = Field(default=.8, gt=0, allow_inf_nan=False)
    min_logic_budget_fraction: float = Field(default=.3, gt=0, le=1)
    mux_levels: int = Field(default=3, ge=2)
    fanout: int = Field(default=64, ge=2)
    fanout_delay_ns: float = Field(default=.45, gt=0, allow_inf_nan=False)
    fanout_path_fraction: float = Field(default=.12, gt=0, le=1)
    routing_fraction: float = Field(default=.6, gt=0, le=1)
    routing_nets: int = Field(default=2, ge=1)
    carry_cells: int = Field(default=3, ge=2)
    dsp_fraction: float = Field(default=.2, gt=0, le=1)


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    description: str
    required: tuple[str, ...]
    thresholds: tuple[str, ...]
    action: str
    why: str
    tradeoffs: str
    verify: str


RULES = {rule.id: rule for rule in (
    Rule("TL-A", "Deep combinational logic",
         "A failing setup path traverses many combinational levels and spends a material part of its setup budget in logic.",
         ("setup slack", "native logic depth", "logic delay", "positive timing requirement"),
         ("logic_levels", "min_logic_ns", "min_logic_budget_fraction"),
         "Inspect the measured chain for dependent operations, redundant logic, or logic that can run in parallel. Consider a register boundary if the interface permits another cycle.",
         "Reducing serial primitive stages reduces accumulated cell delay and can remove intervening nets.",
         "Factoring changes LUT usage. A pipeline stage adds cycles and usually registers. Align valid, enable, reset, and data across the new boundary.",
         "Run functional regression and compare post-route endpoint slack and path depth under the same constraints."),
    Rule("TL-B", "Mux chain with a priority source tag",
         "Several electrically connected mux data arcs have Vivado source tags overlapping an RTL priority construct. Confirm that the tagged construct still describes the optimized cells.",
         ("setup slack", "ordered mux data arcs", "verified cell-to-RTL attribution"),
         ("mux_levels",),
         "Review redundant conditions and consider a grouped selector with explicitly preserved winner priority.",
         "Groups can evaluate concurrently and combine winners with fewer dependent selections.",
         "The same winner and fallback must hold for simultaneous requests. A tree changes area. Registering winner selection changes cycle latency.",
         "Test zero, single, and overlapping requests and compare implemented mux depth and slack."),
    Rule("TL-C", "High-fanout net with measured delay",
         "A high-load data branch consumes a material fraction of the failing setup path.",
         ("setup slack", "fanout", "per-sink net delay", "datapath delay", "driver connectivity"),
         ("fanout", "fanout_delay_ns", "fanout_path_fraction"),
         "Inspect the driver and sink locations. Consider local control distribution or legal driver register replication if the driver is sequential.",
         "Local drivers can reduce routing branches and the distance to the affected loads.",
         "Replication uses registers and may affect control sets and congestion. Global clock networks and special control resources require separate review.",
         "Compare measured delay at the same sink and review replicated state, resets, enables, and post-route slack."),
    Rule("TL-D", "Routing-dominated datapath",
         "Measured data routing accounts for most of the failing setup datapath.",
         ("setup slack", "net delay", "datapath delay", "ordered nets"),
         ("routing_fraction", "routing_nets"),
         "Inspect the slowest branches and placed resource locations. Review locality, placement constraints, and physical optimization.",
         "Moving dependent resources closer or reducing routing pressure can shorten connections.",
         "Placement changes can move congestion to other paths. Synthesized route estimates can change materially during placement and routing.",
         "Rerun implementation and compare net delay, setup and hold, utilization, and nearby congestion."),
    Rule("TL-E", "Cascaded arithmetic on failing path",
         "The failing setup path traverses a dedicated carry chain or spends significant time in DSP cells.",
         ("setup slack", "ordered carry cascade or measured DSP arc delay"),
         ("carry_cells", "dsp_fraction"),
         "Review operand widths and dependent arithmetic. Inspect carry grouping or available DSP registers where the actual arithmetic operator and device support them.",
         "Narrower arithmetic or a register boundary can reduce the number of cascaded transfers per cycle.",
         "Width changes affect overflow and precision. DSP mapping consumes DSP sites. Internal DSP registers or a pipeline change latency.",
         "Test arithmetic corner cases and compare mapped primitives, latency, and implemented slack."),
    Rule("TL-F", "Block RAM timing interface",
         "The failing setup datapath reaches or departs a mapped block RAM.",
         ("setup slack", "ordered block RAM cell", "RAM boundary connectivity"),
         (),
         "Identify whether the slow branch is address/control or memory output. Evaluate surrounding logic and supported output registers on the read side.",
         "Registering a read output or shortening RAM access logic can reduce the logic and routing in a cycle.",
         "Output registration adds a read cycle and changes handshake scheduling. Preserve enable, reset, and read-during-write behavior.",
         "Recheck read/write latency, stall behavior, collision semantics, and implemented setup and hold."),
    Rule("TL-G", "Clock or constraint review",
         "Vivado reported a constraint coverage finding or a suspicious timed clock-pair classification.",
         ("check_timing or report_clock_interaction output",), (),
         "Verify clock definitions, generated clock relationships, I/O delays, and CDC architecture against the design specification.",
         "Accurate constraints tell the timing engine which edges and delays hardware must satisfy.",
         "Timing exceptions require an independent functional justification. Constraint corrections can expose additional violations.",
         "Review the Vivado reports and verify clock relationships, CDC synchronizers, and timing coverage."),
    Rule("TL-H", "Timing violation requires investigation",
         "The measured failing path has insufficient evidence for a more specific diagnosis.",
         ("negative slack",), (),
         "Inspect the complete timing path and clock relationship in Vivado. Compare the incremental delays and endpoint requirements.",
         "The path report identifies where timing margin was lost and which measurements require more context.",
         "The likely corrective action depends on the actual logic, routing, and timing requirements.",
         "Reproduce the path under the same design stage and constraints before comparing changes."),
)}


@dataclass(frozen=True)
class Finding:
    rule: str
    path_id: str | None
    anchors: tuple[str, ...]
    evidence: tuple[str, ...]
    portion: float
    confidence: Confidence
    module: str | None = None


def configuration_checks(session: Session) -> list[Finding]:
    findings = []
    for check, count in sorted(session.timing_checks.items()):
        if count > 0:
            findings.append(Finding("TL-G", None, (f"check_timing/{check}",),
                                    (f"Vivado check_timing reports {count} for {check}.",), 0, Confidence.UNKNOWN))
    return findings


@lru_cache(maxsize=64)
def _lut_selector(init: str) -> str | None:
    """Identify the select input of exactly one uninverted three-input mux truth table."""
    try:
        mask = int(init.split("'h")[-1].removeprefix("0x"), 16)
    except ValueError:
        return None
    for select, low, high in permutations(range(3)):
        expected = sum(bits[high if bits[select] else low] << sum(bit << i for i, bit in enumerate(bits))
                       for bits in product((0, 1), repeat=3))
        if mask == expected:
            return f"I{select}"
    return None


def mux_chain(path: TimingPath, session: Session, links: dict[str, Association]) -> tuple[str, ...]:
    longest: tuple[str, ...] = ()
    chain: tuple[str, ...] = ()
    prev_output = None
    prev_scope = None
    relay = None
    for arc in path.arcs:
        if arc.kind == "net":
            relay = arc.sink if arc.source == prev_output else None
            continue
        cell = session.cells[arc.resource]
        pin = session.pins[arc.source]
        association = links[arc.resource]
        select = ("S" if cell.primitive.startswith("MUXF") else
                  _lut_selector(cell.init.lower()) if cell.primitive == "LUT3" and cell.init else None)
        structure = next((c for c in association.constructs if c.kind == "priority selection candidate"), None)
        scope = (association.file, association.instance, structure.first if structure else None)
        if select and pin.ref_pin and pin.ref_pin != select and structure and association.confidence == Confidence.EXACT:
            chain = (*chain, cell.name) if relay == arc.source and scope == prev_scope else (cell.name,)
            longest = max(longest, chain, key=len)
            prev_scope, prev_output = scope, arc.sink
        else:
            chain, prev_output = (), None
        relay = None
    return longest


def _arithmetic(path: TimingPath, session: Session) -> tuple[list[str], list[str], float]:
    longest: list[str] = []
    chain: list[str] = []
    dsp = []
    dsp_delay = 0.0
    carry_output = None
    relay = None
    for arc in path.arcs:
        if arc.kind == "net":
            relay = arc.sink if arc.source == carry_output else None
            continue
        cell = session.cells[arc.resource]
        ref = cell.primitive
        if ref.startswith(("CARRY4", "CARRY8")):
            input_pin = session.pins[arc.source].ref_pin or ""
            output_pin = session.pins[arc.sink].ref_pin or ""
            if chain and relay == arc.source and input_pin in {"CI", "CI_TOP"}:
                chain.append(cell.name)
            else:
                chain = [cell.name]
            longest = max(longest, chain.copy(), key=len)
            carry_output = arc.sink if output_pin.startswith("CO") else None
        else:
            chain.clear()
            carry_output = None
        relay = None
        if ref.startswith("DSP") and arc.delay_ns is not None:
            dsp.append(cell.name)
            dsp_delay += max(0, arc.delay_ns)
    return longest, dsp, dsp_delay


def _segments(graph: Graph, path: TimingPath, *, kind: str | None = None) -> tuple[str, ...]:
    eligible = set(graph.logic_cells(path))
    anchors = []
    for run in graph.segments(path):
        for arc, nxt in zip(run, run[1:]):
            if arc[3] in eligible and nxt[2] == "net":
                anchors.append(f"{arc[3]} → {nxt[3]}")
    if anchors:
        return tuple(dict.fromkeys(anchors))
    resources = path.nets if kind == "net" else graph.logic_cells(path)
    return tuple(resources) or (path.endpoint or path.id,)


def diagnose(path: TimingPath, graph: Graph, links: dict[str, Association],
             association: Association, cfg: Thresholds) -> list[Finding]:
    if path.slack_ns is None or path.slack_ns >= 0:
        return []
    session = graph.session
    findings: list[Finding] = []
    data = path.datapath_ns or 0
    logic = path.logic_ns or 0
    routing = path.routing_ns or 0
    branch_arcs = [arc for arc in path.arcs if arc.kind == "net" and arc.delay_ns is not None]

    def add(rule: str, anchors, evidence, portion=0.0, source=None):
        src = source or association
        findings.append(Finding(rule, path.id, tuple(anchors), tuple(evidence),
                                min(1.0, max(0.0, portion)), src.confidence, src.module))

    def location(pin_name):
        pin = session.pins[pin_name]
        cell = session.cells.get(pin.cell or "")
        return cell.location if cell else None

    if path.analysis == "setup" and "recovery" not in (path.path_type or "").lower():
        requirement = path.requirement_ns or 0
        if (path.levels or 0) >= cfg.logic_levels and logic >= cfg.min_logic_ns and requirement > 0 and (
                logic / requirement >= cfg.min_logic_budget_fraction):
            primitives = Counter(session.cells[name].primitive for name in graph.logic_cells(path))
            evidence = [f"{path.levels} Vivado logic levels",
                        f"{logic:.3f} ns logic against a {requirement:.3f} ns requirement"]
            if primitives:
                evidence.append("Captured combinational cells · " +
                                ", ".join(f"{p} × {n}" for p, n in sorted(primitives.items())))
            add("TL-A", _segments(graph, path), evidence, logic / data if data > 0 else 0.0)
        chain = mux_chain(path, session, links)
        if len(chain) >= cfg.mux_levels:
            source = links[chain[-1]]
            add("TL-B", (f"{a} → {b}" for a, b in zip(chain, chain[1:])),
                [f"{len(chain)} electrically cascaded mux stages",
                 f"Vivado source hint: {source.module} line {source.first} contains a priority construct; causal attribution is unproven",
                 "Verified muxes: " + ", ".join(chain)], source=source)
        if data > 0:
            for arc in branch_arcs:
                net = session.nets[arc.resource]
                delay = arc.delay_ns
                if ((net.fanout or 0) >= cfg.fanout and delay >= cfg.fanout_delay_ns
                    and delay / data >= cfg.fanout_path_fraction
                    and net.properties.get("IS_CLOCK", "").lower() not in {"1", "true"}
                    and arc.source in net.drivers):
                    driver = session.cells.get(session.pins[arc.source].cell or "")
                    load = session.cells.get(session.pins[arc.sink].cell or "")
                    add("TL-C", (net.name,), (
                        f"{net.fanout} loads on {net.name}",
                        f"{delay:.3f} ns ({delay / data:.1%} of datapath) to {arc.sink}",
                        f"Driver {arc.source} ({driver.primitive if driver else 'port'})",
                        f"Locations {driver.location if driver and driver.location else 'unavailable'} → "
                        f"{load.location if load and load.location else 'unavailable'}",
                    ), delay / data, links.get(driver.name) if driver else None)
            if routing / data >= cfg.routing_fraction and len(path.nets) >= cfg.routing_nets:
                slow = sorted(branch_arcs, key=lambda a: (-a.delay_ns, a.resource))
                evidence = [f"{routing:.3f} ns route delay ({routing / data:.1%}) across {len(path.nets)} captured nets",
                            f"Vivado design stage: {session.stage}"]
                for a in slow[:3]:
                    src_loc, sink_loc = location(a.source), location(a.sink)
                    physical = f" ({src_loc} → {sink_loc})" if src_loc and sink_loc else ""
                    net = session.nets[a.resource]
                    driver = session.cells.get(session.pins[a.source].cell or "")
                    protected = " · driver DONT_TOUCH" if driver and driver.properties.get("DONT_TOUCH", "").lower() in {"1", "true"} else ""
                    evidence.append(f"{a.resource} → {a.sink}: {a.delay_ns:.3f} ns{physical} · {net.fanout if net.fanout is not None else 'unknown'} loads{protected}")
                add("TL-D", [a.resource for a in slow[:3]] or _segments(graph, path, kind="net"),
                    evidence, routing / data)
        carry, dsp, dsp_delay = _arithmetic(path, session)
        if len(carry) >= cfg.carry_cells:
            measured = [a.delay_ns for a in path.arcs if a.kind == "cell" and a.resource in carry]
            carry_delay = sum(measured) if measured and all(d is not None for d in measured) else None
            evidence = [f"{len(carry)} consecutive carry primitives: {', '.join(carry)}"]
            if carry_delay is not None:
                evidence.append(f"{carry_delay:.3f} ns summed carry cell delay ({carry_delay / data:.1%} of datapath)" if data > 0
                                else f"{carry_delay:.3f} ns summed carry cell delay")
            add("TL-E", (f"{a} → {b}" for a, b in zip(carry, carry[1:])),
                evidence, carry_delay / data if carry_delay is not None and data > 0 else 0.0, source=links[carry[-1]])
        if dsp and data > 0 and dsp_delay / data >= cfg.dsp_fraction:
            add("TL-E", dsp, [f"{dsp_delay:.3f} ns summed DSP arc delay across {', '.join(dsp)}"],
                dsp_delay / data, links[dsp[-1]])
        for name in path.cells:
            cell = session.cells[name]
            if cell.primitive.startswith(("RAMB18", "RAMB36", "URAM")):
                boundary = "launch" if path.startpoint and session.pins.get(path.startpoint) and (
                    session.pins[path.startpoint].cell == name) else "capture or internal"
                add("TL-F", (name,), [f"{cell.primitive} {name} at the {boundary} side",
                                     f"Placement: {cell.location or 'unavailable'}"], source=links[name])
    for row in session.clock_interactions:
        classification = row.get("classification", "").lower()
        timed = "timed" in row.get("constraints", "").lower() and "ignored" not in row.get("constraints", "").lower()
        if (timed and row.get("source") == path.start_clock and row.get("destination") == path.end_clock
                and classification in {"no common clock", "no common period", "no common node", "partial false path"}):
            add("TL-G", (f"{path.start_clock} → {path.end_clock}",),
                [f"Vivado reports {row['classification']} with {row['constraints']} constraints"])
    if not findings:
        add("TL-H", (path.endpoint or path.id,),
            [f"{path.analysis.title()} slack {path.slack_ns:.3f} ns",
             f"Ordered graph coverage: {len(path.arcs)} verified arcs"])
    return findings
