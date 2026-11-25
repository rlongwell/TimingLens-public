from collections import Counter

import pytest

from timinglens import Session, Thresholds, analyze
from timinglens.netlist.graph import Graph
from timinglens.rules.library import RULES, _lut_selector
from timinglens.timing.models import Arc, Cell, Net, Pin, TimingPath


def chain(primitives=("LUT2", "LUT2", "LUT2"), fanout=1, route=.7, **fields):
    cells = {}
    pins = {}
    nets = {}
    arcs = []
    names = []
    port_a, port_z = Pin(name="a", direction="IN", port=True), Pin(name="z", direction="OUT", port=True)
    pins.update(a=port_a, z=port_z)
    previous = "a"
    ordered_pins = [previous]
    for i, primitive in enumerate(primitives):
        key = f"u{i}"
        cells[key] = Cell(name=key, primitive=primitive)
        names.append(key)
        p1 = Pin(name=f"{key}/i", cell=key, direction="IN", ref_pin="CI" if primitive.startswith("CARRY") else "I0")
        p2 = Pin(name=f"{key}/o", cell=key, direction="OUT", ref_pin="CO[3]" if primitive.startswith("CARRY") else "O")
        pins.update({p1.name: p1, p2.name: p2})
        net = Net(name=f"n{i}", fanout=fanout, drivers=[previous], sinks=[p1.name])
        nets[net.name] = net
        arcs.extend((Arc(source=previous, sink=p1.name, kind="net", resource=net.name, delay_ns=route),
                     Arc(source=p1.name, sink=p2.name, kind="cell", resource=key, delay_ns=.3)))
        ordered_pins.extend((p1.name, p2.name))
        previous = p2.name
    net = Net(name="last", fanout=1, drivers=[previous], sinks=["z"])
    nets[net.name] = net
    arcs.append(Arc(source=previous, sink="z", kind="net", resource=net.name, delay_ns=.2))
    ordered_pins.append("z")
    defaults = dict(analysis="setup", startpoint="a", endpoint="z", slack_ns=-1.0, requirement_ns=2.0,
                    datapath_ns=4.0, logic_ns=1.5, routing_ns=2.5, levels=len(primitives))
    path = TimingPath(id="P1", **(defaults | fields), cells=names, pins=ordered_pins, nets=list(nets), arcs=arcs)
    return Session(name="fixture", cells=cells, pins=pins, nets=nets, paths=[path])


def ids(result):
    return {finding.rule for finding in result.findings}


def test_rule_catalog():
    assert set(RULES) == {f"TL-{char}" for char in "ABCDEFGH"}
    for rule in RULES.values():
        assert all((rule.title, rule.description, rule.required, rule.action, rule.why, rule.tradeoffs, rule.verify))


def test_depth_and_route_thresholds_are_independent():
    fixture = chain(levels=12)
    assert ids(analyze(fixture)) == {"TL-A", "TL-D"}
    assert ids(analyze(fixture, Thresholds(logic_levels=13, routing_fraction=.9))) == {"TL-H"}
    assert ids(analyze(chain(levels=12, logic_ns=None))) == {"TL-D"}
    assert ids(analyze(chain(levels=12, analysis="hold"))) == {"TL-H"}


@pytest.mark.parametrize(("fanout", "delay", "slack", "expected"), [
    (128, 1.0, -1.2, True), (128, .02, -1.2, False),
    (25, 1.0, -1.2, False), (128, 1.0, 0.0, False),
])
def test_fanout_needs_branch_impact(fanout, delay, slack, expected):
    assert ("TL-C" in ids(analyze(chain(fanout=fanout, route=delay, slack_ns=slack)))) == expected


def test_arithmetic_requires_connected_chain():
    fixture = chain(("CARRY4",) * 3)
    assert "TL-E" in ids(analyze(fixture))
    path = fixture.paths[0]
    broken = path.model_copy(update={"arcs": [a for a in path.arcs if a.kind == "cell"]})
    assert "TL-E" not in ids(analyze(fixture.model_copy(update={"paths": [broken]})))


def test_dsp_rule_requires_measured_fraction():
    assert "TL-E" not in ids(analyze(chain(("DSP48E1",))))
    assert "TL-E" in ids(analyze(chain(("DSP48E1",), datapath_ns=1.0)))


def test_bram_rule_uses_native_resource():
    assert "TL-F" in ids(analyze(chain(("RAMB36E1",))))
    assert "TL-F" not in ids(analyze(chain(("RAM32M",))))


def test_lut_detection_and_priority_evidence():
    assert _lut_selector("8'hb8") == "I1"
    assert _lut_selector("8'h96") is None  # XOR
    assert _lut_selector("invalid") is None
    fixture = chain(("LUT3",) * 3)
    assert "TL-B" not in ids(analyze(fixture))


def test_authoritative_constraints_and_fallback():
    fixture = chain(analysis="hold", start_clock="c0", end_clock="c1")
    assert ids(analyze(fixture)) == {"TL-H"}
    with_checks = fixture.model_copy(update={"timing_checks": {"no_clock": 2, "loops": 0}})
    assert ids(analyze(with_checks)) == {"TL-G", "TL-H"}
    finding = next(f for f in analyze(with_checks).findings if f.rule == "TL-G")
    assert finding.path_id is None
    interaction = {"source": "c0", "destination": "c1", "classification": "No Common Clock", "constraints": "Timed"}
    assert ids(analyze(fixture.model_copy(update={"clock_interactions": [interaction]}))) == {"TL-G"}


def test_graph_and_unique_path_counts():
    base = chain(levels=12)
    other = base.paths[0].model_copy(update={"id": "P2", "slack_ns": -2.0})
    total = base.model_copy(update={"paths": [base.paths[0], other]})
    result = analyze(total)
    assert analyze(total).groups == result.groups
    assert result.failing_paths == 2
    assert Counter(len(g.path_ids) for g in result.groups) == {2: 2}
    assert all(g.endpoints == 1 and g.worst_slack_ns == -2.0 for g in result.groups)
    assert not total.summary
    graph = Graph(total)
    assert graph.cone("z")["a"] == 7
    assert graph.cone("z", max_hops=1) == {"z": 0, "u2/o": 1}
    assert graph.shared(nets=True)["n1"] == ("P1", "P2")
    assert graph.common_segments(total.paths)
    assert graph.delay_class(total.paths[0]) == "routing-dominated"
