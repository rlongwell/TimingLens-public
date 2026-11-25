"""Machine-readable derived results, kept separate from source measurements."""
from dataclasses import asdict
import json
from pathlib import Path

from ..analysis.engine import Analysis
from ..rules.library import RULES
from ..timing.io import atomic_text


def write_diagnostics(path: Path, result: Analysis) -> None:
    def association(link):
        return {**asdict(link), "confidence": link.confidence.label}

    def finding(item):
        return {**asdict(item), "confidence": item.confidence.label}

    def group(item):
        return {**asdict(item), "confidence": item.confidence.label,
                "findings": [finding(found) for found in item.findings]}

    document = {
        "schema_version": 2,
        "time_unit": "ns",
        "thresholds": result.thresholds.model_dump(),
        "collected_failing_paths": result.failing_paths,
        "detail_coverage": {key: {**asdict(c), "complete": c.complete} for key, c in result.coverage.items()},
        "warnings": list(result.warnings),
        "fix_plans": {key: [asdict(plan) for plan in plans] for key, plans in result.fix_plans.items()},
        "investigations": [asdict(item) for item in result.investigations],
        "source_provenance": [{"path": s.path, "sha256": s.sha256, "file_type": s.file_type}
                              for s in result.session.sources],
        "source_provenance_limit": "Hashes identify captured bytes, not RTL/checkpoint equivalence.",
        "project_context": asdict(result.project_context),
        "project_plans": [asdict(plan) for plan in result.project_plans],
        "findings": [finding(item) for item in result.findings],
        "groups": [group(item) for item in result.groups],
        "path_source": {key: association(link) for key, link in result.paths.items()},
        "cell_source": {key: association(link) for key, link in result.cells.items()},
        "rules": {key: asdict(rule) for key, rule in RULES.items()},
    }
    atomic_text(path, json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
