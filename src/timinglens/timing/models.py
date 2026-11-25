"""Versioned, validated interchange for measured timing and hardware evidence."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AnalysisType = Literal["setup", "hold"]
Direction = Literal["IN", "OUT", "INOUT"]
Finite = Annotated[float, Field(allow_inf_nan=False)]
Natural = Annotated[int, Field(ge=0)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Source(Record):
    path: str
    file_type: str = ""
    sha256: str | None = None
    text: str | None = None


class SourceLink(Record):
    """Reserved for a tool-provided, object-level cross-probe mapping."""
    file: str
    first_line: Annotated[int, Field(gt=0)]
    last_line: Annotated[int, Field(gt=0)]
    provenance: str


class Cell(Record):
    name: str
    primitive: str
    parent: str | None = None
    original_ref: str | None = None
    original_name: str | None = None
    location: str | None = None
    bel: str | None = None
    init: str | None = None
    sequential: bool = False
    hierarchical: bool = False
    source: SourceLink | None = None
    properties: dict[str, str] = Field(default_factory=dict)


class Pin(Record):
    name: str
    direction: Direction | None = None
    cell: str | None = None
    ref_pin: str | None = None
    port: bool = False


class Net(Record):
    name: str
    fanout: Natural | None = None
    drivers: list[str] = Field(default_factory=list)
    sinks: list[str] = Field(default_factory=list)
    sinks_complete: bool = False
    aliases: list[str] = Field(default_factory=list)
    properties: dict[str, str] = Field(default_factory=dict)


class Arc(Record):
    source: str
    sink: str
    kind: Literal["cell", "net"]
    resource: str
    delay_ns: Finite | None = None


class TimingPath(Record):
    id: str
    analysis: AnalysisType
    startpoint: str | None = None
    endpoint: str | None = None
    start_clock: str | None = None
    end_clock: str | None = None
    group: str | None = None
    corner: str | None = None
    path_type: str | None = None
    slack_ns: Finite | None = None
    requirement_ns: Finite | None = None
    arrival_ns: Finite | None = None
    required_ns: Finite | None = None
    datapath_ns: Finite | None = None
    logic_ns: Finite | None = None
    routing_ns: Finite | None = None
    skew_ns: Finite | None = None
    uncertainty_ns: Finite | None = None
    levels: Natural | None = None
    pins: list[str] = Field(default_factory=list)
    cells: list[str] = Field(default_factory=list)
    nets: list[str] = Field(default_factory=list)
    arcs: list[Arc] = Field(default_factory=list)
    properties: dict[str, str] = Field(default_factory=dict)


class Clock(Record):
    name: str
    period_ns: Finite | None = None
    waveform_ns: list[Finite] = Field(default_factory=list)
    generated: bool | None = None
    master: str | None = None
    sources: list[str] = Field(default_factory=list)


class Summary(Record):
    worst_slack_ns: Finite | None = None
    total_negative_slack_ns: Finite | None = None
    failing_endpoints: Natural | None = None
    total_endpoints: Natural | None = None


class Session(Record):
    schema_version: Literal[1] = 1
    time_unit: Literal["ns"] = "ns"
    name: str
    vivado: str | None = None
    part: str | None = None
    stage: Literal["synthesized", "placed", "routed", "partially_routed", "unknown"] = "unknown"
    timestamp: str | None = None
    top: str | None = None
    origin: str | None = None
    run: str | None = None
    path_limit_per_type: Natural | None = None
    paths_per_endpoint: Natural | None = None
    sources: list[Source] = Field(default_factory=list)
    clocks: list[Clock] = Field(default_factory=list)
    cells: dict[str, Cell] = Field(default_factory=dict)
    pins: dict[str, Pin] = Field(default_factory=dict)
    nets: dict[str, Net] = Field(default_factory=dict)
    paths: list[TimingPath] = Field(default_factory=list)
    summary: dict[AnalysisType, Summary] = Field(default_factory=dict)
    timing_checks: dict[str, Natural] = Field(default_factory=dict)
    clock_interactions: list[dict[str, str]] = Field(default_factory=list)
    reports: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    rule_thresholds: dict[str, int | Finite] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_references(self) -> Session:
        for objects in (self.cells, self.pins, self.nets):
            if any(key != obj.name for key, obj in objects.items()):
                raise ValueError("Hardware object keys must equal their names")
        if len({path.id for path in self.paths}) != len(self.paths):
            raise ValueError("Timing path IDs must be unique")
        for name, pin in self.pins.items():
            if pin.cell is not None and pin.cell not in self.cells:
                raise ValueError(f"Unknown cell referenced by {name}")
        for net in self.nets.values():
            if any(pin not in self.pins for pin in [*net.drivers, *net.sinks]):
                raise ValueError(f"Unknown pin referenced by {net.name}")
        for path in self.paths:
            for names, objects in ((path.cells, self.cells), (path.pins, self.pins), (path.nets, self.nets)):
                if any(name not in objects for name in names):
                    raise ValueError(f"Unknown hardware object on {path.id}")
            for arc in path.arcs:
                resources = self.cells if arc.kind == "cell" else self.nets
                if arc.resource not in resources or arc.source not in self.pins or arc.sink not in self.pins:
                    raise ValueError(f"Unknown timing arc reference on {path.id}")
        return self
