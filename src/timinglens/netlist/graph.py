"""Connectivity graph scoped to captured paths and their incident net branches."""
from __future__ import annotations

from collections import Counter, defaultdict, deque

from ..timing.models import Session, TimingPath


class Graph:
    def __init__(self, session: Session):
        self.session = session
        self.forward: dict[str, set[str]] = defaultdict(set)
        self.reverse: dict[str, set[str]] = defaultdict(set)
        self.paths_by_cell: dict[str, set[str]] = defaultdict(set)
        self.paths_by_net: dict[str, set[str]] = defaultdict(set)
        for net in session.nets.values():
            for driver in net.drivers:
                for sink in net.sinks:
                    self._connect(driver, sink)
        for path in session.paths:
            for name in path.cells:
                self.paths_by_cell[name].add(path.id)
            for name in path.nets:
                self.paths_by_net[name].add(path.id)
            for arc in path.arcs:
                cell = session.cells.get(arc.resource) if arc.kind == "cell" else None
                if cell is None or not cell.sequential:
                    self._connect(arc.source, arc.sink)

    def _connect(self, source: str, sink: str) -> None:
        self.forward[source].add(sink)
        self.reverse[sink].add(source)

    def cone(self, pin: str, *, upstream: bool = True, max_hops: int = 20) -> dict[str, int]:
        if pin not in self.session.pins:
            return {}
        edges = self.reverse if upstream else self.forward
        visited = {pin: 0}
        queue = deque([pin])
        while queue:
            current = queue.popleft()
            if visited[current] >= max_hops:
                continue
            for neighbor in sorted(edges[current]):
                if neighbor not in visited:
                    visited[neighbor] = visited[current] + 1
                    queue.append(neighbor)
        return visited

    def logic_cells(self, path: TimingPath) -> tuple[str, ...]:
        return tuple(dict.fromkeys(name for name in path.cells
                     if not self.session.cells[name].sequential and not self.session.cells[name].hierarchical))

    def logic_depth(self, path: TimingPath) -> int | None:
        if path.levels is not None:
            return path.levels
        if len(path.pins) < 2 or len(path.arcs) != len(path.pins) - 1:
            return None
        return sum(arc.kind == "cell" and not self.session.cells[arc.resource].sequential
                   and not self.session.cells[arc.resource].hierarchical for arc in path.arcs)

    def high_fanout(self, minimum: int) -> dict[str, int]:
        return {name: net.fanout for name, net in sorted(self.session.nets.items())
                if net.fanout is not None and net.fanout >= minimum}

    def shared(self, *, nets: bool = False) -> dict[str, tuple[str, ...]]:
        index = self.paths_by_net if nets else self.paths_by_cell
        return {name: tuple(sorted(paths)) for name, paths in sorted(index.items()) if len(paths) > 1}

    def common_segments(self, paths: list[TimingPath], length: int = 2) -> Counter:
        if length < 1:
            raise ValueError("Segment length must be positive")
        counts: Counter = Counter()
        for path in paths:
            counts.update({tuple(run[i:i + length]) for run in self.segments(path)
                           for i in range(len(run) - length + 1)})
        return Counter({key: value for key, value in counts.items() if value > 1})

    @staticmethod
    def segments(path: TimingPath) -> list[list[tuple[str, str, str, str]]]:
        runs: list[list[tuple[str, str, str, str]]] = []
        current: list[tuple[str, str, str, str]] = []
        for arc in path.arcs:
            if current and current[-1][1] != arc.source:
                runs.append(current)
                current = []
            current.append((arc.source, arc.sink, arc.kind, arc.resource))
        if current:
            runs.append(current)
        return runs

    @staticmethod
    def delay_class(path: TimingPath) -> str:
        if path.logic_ns is None or path.routing_ns is None or path.logic_ns + path.routing_ns <= 0:
            return "unavailable"
        fraction = path.routing_ns / (path.logic_ns + path.routing_ns)
        return "routing-dominated" if fraction >= .6 else "logic-dominated" if fraction <= .4 else "mixed"
