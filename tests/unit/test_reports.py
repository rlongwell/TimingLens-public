from timinglens.vivado.reports import clock_interactions, detail_rows, design_stage, timing_checks, timing_summary

SUMMARY = """
| Design State : Routed
| Design Timing Summary
    WNS(ns)      TNS(ns)    TNS Failing Endpoints    TNS Total Endpoints  WHS(ns) THS(ns)  THS Failing Endpoints  THS Total Endpoints
    -------      -------   ---------------------   -------------------  ------- ------- --------------------- -------------------
     -4.010       -8.120                       2                    30     0.024   0.000                     0                  30  NA NA NA NA
"""


def test_summary_is_design_wide_with_hold():
    summary = timing_summary(SUMMARY)
    assert summary["setup"].worst_slack_ns == -4.01
    assert summary["setup"].total_negative_slack_ns == -8.12
    assert summary["setup"].failing_endpoints == 2
    assert summary["hold"].worst_slack_ns == .024
    assert summary["hold"].failing_endpoints == 0
    assert not timing_summary(SUMMARY.replace("| Design Timing Summary", "Other Path Groups Table"))
    assert design_stage(SUMMARY, "", "synth") == "routed"


def test_checks_and_clock_pairs():
    assert timing_checks("1. checking no_clock (2)\n9. checking loops (0)") == {"no_clock": 2, "loops": 0}
    headings = ["From Clock", "To Clock", "Edges", "WNS", "TNS", "Fail", "Total", "Req", "Classification", "Constraints"]
    widths = [14, 14, 13, 7, 7, 9, 9, 7, 20, 18]
    data = ["c0", "c1", "rise - rise", "-2.00", "-6", "3", "12", "10", "No Common Clock", "Timed"]
    lines = ["  ".join(field.ljust(size) for field, size in zip(line, widths))
             for line in (headings, ["-" * w for w in widths], data)]
    rows = clock_interactions("\n".join(lines))
    assert rows[0]["classification"] == "No Common Clock"
    assert rows[0]["destination"] == "c1"


def test_timing_detail_rejects_clock_capture_rows():
    text = """
SLICE_X1Y4  FDRE (Prop_fdre_C_Q) 0.478 5.091 r launch/Q
            net (fo=2, routed)  0.412 5.503   bus[0]
SLICE_X1Y3                                  r capture/D
              data arrival time         5.503
            net (fo=21, routed) 1.005 6.000   ignored
"""
    assert detail_rows(text) == [("pin", "launch/Q", .478), ("net", "bus[0]", .412),
                                 ("pin", "capture/D", None)]
