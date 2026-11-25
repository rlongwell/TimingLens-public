# TimingLens session format, version 1

`analysis.json` contains one schema-versioned object. `time_unit` is always `ns`. Signed measurements are numeric. A missing measurement is null or omitted. Source hashes are SHA-256 digests of the file bytes captured by the application. Path IDs are opaque identifiers within one session.

See [session-v1.schema.json](session-v1.schema.json) for the machine-readable schema. A minimal session can contain a single measured path.

```json
{
  "schema_version": 1,
  "time_unit": "ns",
  "name": "example",
  "paths": [
    {"id": "P1", "analysis": "setup", "slack_ns": -0.35}
  ]
}
```

| Field | Meaning |
| --- | --- |
| `vivado`, `part`, `stage`, `timestamp`, `top`, `origin`, `run` | Tool and design provenance. The collection timestamp uses UTC. |
| `summary` | Vivado’s design-wide setup and hold worst slack, total negative slack, failing endpoints and total endpoints. |
| `path_limit_per_type`, `paths_per_endpoint` | Requested collection bounds. |
| `paths` | Measured path metrics, ordered pins/cells/nets, and verified arcs. `requirement_ns` is the path budget and `required_ns` is the STA arrival deadline. |
| `cells`, `pins`, `nets` | Shared objects keyed by actual design names. Arc resources refer to these objects. A net can have display aliases for its hierarchical segments. |
| `clocks` | Clock periods, waveforms, generated-clock flags, and source objects when present. |
| `sources` | Identifiers, Vivado file types, and optional digest-checked source snapshots. |
| `timing_checks`, `clock_interactions`, `reports` | Structured constraint findings and authoritative Vivado report text. |
| `warnings` | Collection and attribution limitations observed in this session. |
| `rule_thresholds` | Analysis thresholds used for the export. Absent keys use release defaults. |

A `net` arc connects a timed output or launch port to the sink of one actual net branch. A `cell` arc runs between pins of a single timed primitive. `delay_ns` can be absent even when connectivity is known. `fanout` counts leaf loads, with top-level output ports counted as external loads. `sinks_complete=false` means that only a bounded set of side branches was retained.

`diagnostics.json` has its own `schema_version: 1`, plus `thresholds`, `collected_failing_paths`, `findings`, `groups`, `path_source`, `cell_source`, and the human-readable `rules` catalog. Each finding references a rule and optional path ID and contains its measured evidence, anchors, source-confidence label, and estimated fraction of measured delay when available. TimingLens imports primary evidence from the session and regenerates the diagnostics file.

To regenerate the session schema after a deliberate model change, run `python scripts/write_schema.py` in an installed development environment. Existing version 1 records are validated at import. Session and diagnostics outputs can contain RTL, design names, and local paths. Review contents before sharing.
