"""Coverage of detailed evidence, independent of design-wide timing totals."""
from dataclasses import dataclass

from .models import TimingPath


@dataclass(frozen=True)
class Coverage:
    expected_links: int
    captured_links: int
    measured_delays: int
    captured_arcs: int

    @property
    def complete(self) -> bool:
        return (self.expected_links > 0 and self.captured_links == self.expected_links
                and self.measured_delays == self.captured_arcs)


def path_coverage(path: TimingPath) -> Coverage:
    pins = list(path.pins)
    if path.startpoint and (not pins or pins[0] != path.startpoint):pins.insert(0, path.startpoint)
    if path.endpoint and (not pins or pins[-1] != path.endpoint):pins.append(path.endpoint)
    expected = set(zip(pins, pins[1:]))
    captured = {(a.source, a.sink) for a in path.arcs}
    return Coverage(len(expected), len(expected & captured),
                    sum(a.delay_ns is not None for a in path.arcs), len(path.arcs))


def coverage_note(rows: list[Coverage]) -> str:
    return (f"Detailed evidence: {sum(c.measured_delays for c in rows)}/{sum(c.captured_arcs for c in rows)} "
            f"arc delays measured; {sum(c.captured_links for c in rows)}/{sum(c.expected_links for c in rows)} "
            "consecutive pin links captured.")
