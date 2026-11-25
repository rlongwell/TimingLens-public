"""Cross-check a TimingLens capture against separate, native Vivado timing queries."""
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import re


def rows(path):
    with path.open() as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("build", type=Path)
    cli.add_argument("capture", type=Path)
    cli.add_argument("--full", action="store_true", help="require a path for every failing setup endpoint")
    args = cli.parse_args()
    build = args.build
    session = json.loads((args.capture / "analysis.json").read_text())
    diagnostics = json.loads((args.capture / "diagnostics.json").read_text())
    census = {r["endpoint"]: r for r in rows(build / "native_failing.tsv")}
    assert session["stage"] == "routed"
    assert not any(session["timing_checks"].values())
    summary = (build / "timing_summary.rpt").read_text()
    design_row = re.search(r"^\s+WNS\(ns\).*?\n[^\n]*\n([^\n]+)", summary, re.M).group(1).split()
    for n, check in ((0, "setup"), (4, "hold")):
        assert [float(v) for v in design_row[n:n+4]] == [
            session["summary"][check][k] for k in
            ("worst_slack_ns", "total_negative_slack_ns", "failing_endpoints", "total_endpoints")]
    assert len(census) == session["summary"]["setup"]["failing_endpoints"]
    measured = {p["endpoint"]: p for p in session["paths"] if p["analysis"] == "setup" and p["slack_ns"] < 0}
    assert measured and all(p["slack_ns"] == float(census[e]["slack_ns"]) for e, p in measured.items())
    same_start = sum(census[e]["startpoint"] == p["startpoint"] for e, p in measured.items())
    if args.full:
        assert measured.keys() == census.keys()
    findings = defaultdict(list)
    for hit in diagnostics["findings"]:
        findings[hit["path_id"]].append(hit)
    probes = {}
    for native in rows(build / "native_paths.tsv"):
        label = native["family"]
        record = {"slack_ns": float(native["slack_ns"]), "failing_endpoints": int(native["failing_endpoints"]),
                  "startpoint": native["startpoint"], "endpoint": native["endpoint"]}
        if label == "local_control":
            assert record["slack_ns"] > 0 and not record["failing_endpoints"]
        elif native["endpoint"] not in measured and not args.full:
            record["coverage"] = "Outside the global sample"
        else:
            path = measured[native["endpoint"]]
            assert path["startpoint"] == native["startpoint"] and path["slack_ns"] == record["slack_ns"]
            assert path["logic_ns"] == float(native["logic_ns"]) and path["routing_ns"] == float(native["route_ns"])
            assert path["levels"] == int(native["levels"])
            hits = findings[path["id"]]
            record.update(path=path["id"], rules=sorted({h["rule"] for h in hits}), logic_ns=path["logic_ns"],
                          routing_ns=path["routing_ns"], levels=path["levels"], findings=hits)
            if label == "energy":
                assert native["path_cells"].count(":DSP48E1") == 2
                assert any(h["rule"] == "TL-E" and h["module"] == "energy_mix" and
                           any("DSP arc delay" in e for e in h["evidence"]) for h in hits)
            elif label == "priority":
                assert any(h["rule"] == "TL-D" and h["module"] == "priority_pick" for h in hits)
            elif label in ("stream_frame", "fifo_ready"):
                native_report = (build / f"native_{label}.rpt").read_text()
                branch = re.search(r"net \(fo=256, routed\)\s+([\d.]+)", native_report)
                assert branch and any(h["rule"] == "TL-C" and
                                      any("256 loads" in e for e in h["evidence"]) and
                                      any(branch[1] + " ns" in e for e in h["evidence"]) for h in hits)
        probes[label] = record
    assert set(probes) == {"energy", "priority", "local_control", "stream_frame", "fifo_ready"}
    cells = json.loads((build / "telemetry_fabric.bd").read_text())["design"]
    facts = diagnostics["project_context"]["facts"]
    parsed_cells = {f["subject"] for f in facts if f["kind"] == "bd_ip"}
    assert parsed_cells == cells["components"].keys()
    expected_links = {frozenset(p["interface_ports"]) for p in cells["interface_nets"].values()}
    actual_links = {frozenset([f["subject"], *f["values"]]) for f in facts if f["kind"] == "bd_link"}
    assert actual_links == expected_links
    def instance(endpoint):
        parts = endpoint.split("/")
        return parts[1] if len(parts) > 1 else endpoint
    def classify(endpoint):
        path = measured[endpoint]
        evidence = findings[path["id"]]
        return any(f["rule"] not in ("TL-H", "TL-G") for f in evidence)
    count_complete = sum(diagnostics["detail_coverage"][p["id"]]["complete"] for p in measured.values())
    assert count_complete == len(measured)
    def counts(items):
        return dict(Counter(instance(e) for e in items).most_common())
    result = dict(summary=session["summary"], design_cells=len(parsed_cells), stream_links=len(actual_links),
                  total_native_failures=len(census), measured_endpoints=len(measured), matched_launch_pins=same_start,
                  complete_setup_paths=count_complete, native_failures_by_endpoint_instance=counts(census),
                  capture_by_endpoint_instance=counts(measured), endpoints_with_a_specific_rule=sum(map(classify, measured)),
                  unexplained_by_endpoint_instance=counts(e for e in measured if not classify(e)), probes=probes)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
