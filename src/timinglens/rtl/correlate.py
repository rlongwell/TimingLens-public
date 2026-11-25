"""Association confidence is derived from independently observable evidence."""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from ..timing.models import Cell, Session
from .syntax import Construct, Module, SourceIndex


class Confidence(IntEnum):
    UNKNOWN = 0
    PARTIAL = 1
    STRONG = 2
    EXACT = 3

    @property
    def label(self) -> str:
        # Keep the enum value for existing Python callers. A vendor source tag
        # does not establish an exact causal RTL expression after optimization.
        return "Vivado source tag" if self == Confidence.EXACT else self.name.title()


@dataclass(frozen=True)
class Association:
    confidence: Confidence
    reason: str
    instance: str | None = None
    module: str | None = None
    file: str | None = None
    first: int | None = None
    last: int | None = None
    module_line: int | None = None
    constructs: tuple[Construct, ...] = ()


UNKNOWN = Association(Confidence.UNKNOWN, "No verified object source metadata or surviving RTL hierarchy.")


def _ancestors(cell: Cell, session: Session):
    seen = {cell.name}
    parent = cell.parent
    while parent in session.cells and parent not in seen:
        candidate = session.cells[parent]
        yield candidate
        seen.add(parent)
        parent = candidate.parent


def _module_for(cell: Cell, index: SourceIndex) -> Module | None:
    for reference in (cell.original_ref, cell.primitive):
        modules = index.modules.get(reference or "", [])
        if len(modules) == 1:
            return modules[0]
    return None


def correlate(cell: Cell, session: Session, index: SourceIndex) -> Association:
    ancestors = list(_ancestors(cell, session))
    scope = next(((candidate.name, module) for candidate in [cell, *ancestors]
                  if candidate.hierarchical and (module := _module_for(candidate, index))), None)
    link = cell.source
    if link and link.provenance == "vivado_cell_file_name_line_number" and link.file in index.texts:
        modules = [module for module in index.files.get(link.file, [])
                   if module.first <= link.first_line <= link.last_line <= module.last]
        if len(modules) == 1 and link.last_line <= len(index.texts[link.file].splitlines()):
            module = modules[0]
            instance = scope[0] if scope and scope[1] == module else None
            structures = tuple(c for c in module.constructs if c.first <= link.last_line and c.last >= link.first_line)
            # A cell synthesized from this source location can still represent other source logic.
            return Association(Confidence.EXACT,
                               "Vivado FILE_NAME/LINE_NUMBER identify an origin hint, not a proven critical expression. "
                               "Optimization may combine or move logic from other RTL lines.",
                               instance, module.name, module.file, link.first_line, link.last_line,
                               module.first, structures)
    if scope:
        instance, module = scope
        hierarchy_cell = session.cells[instance]
        if hierarchy_cell.properties.get("EVIDENCE_ORIGIN") == "RTL hierarchy inference":
            return Association(Confidence.PARTIAL, "Timing-report hierarchy text matches parsed RTL instances; native optimized module ownership is unverified.",
                               instance, module.name, module.file, module_line=module.first)
        parent = session.cells.get(hierarchy_cell.parent or "")
        parent_module = _module_for(parent, index) if parent else None
        if parent_module is None and hierarchy_cell.parent is None:
            candidates = index.modules.get(session.top or "", [])
            parent_module = candidates[0] if len(candidates) == 1 else None
        instance_leaf = instance.rsplit("/", 1)[-1]
        if parent_module and (instance_leaf, module.name) in parent_module.instances:
            return Association(Confidence.STRONG, "Vivado parent and original module type agree with a parsed RTL instance declaration.",
                               instance, module.name, module.file, module_line=module.first)
        return Association(Confidence.PARTIAL, "Vivado hierarchy identifies the module type. Source expression is unavailable.",
                           instance, module.name, module.file, module_line=module.first)
    known_hierarchy = next((candidate for candidate in [cell, *ancestors]
                            if candidate.hierarchical and (candidate.original_ref or candidate.primitive)), None)
    if known_hierarchy:
        return Association(Confidence.PARTIAL, "Vivado retained the hardware hierarchy. A unique module source is unavailable.",
                           known_hierarchy.name, known_hierarchy.original_ref or known_hierarchy.primitive)
    top = index.modules.get(session.top or "", [])
    if len(top) == 1 and not ancestors:
        module = top[0]
        return Association(Confidence.PARTIAL, "The design top is verified. Optimized cell ownership inside the RTL is ambiguous.",
                           module=module.name, file=module.file, module_line=module.first)
    return UNKNOWN
