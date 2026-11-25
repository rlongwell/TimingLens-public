"""Source-exact, deliberately narrow comparison-to-enable review rule.

The algebra holds for unsigned binary values. Four-state relational comparisons
have different X propagation; those receive a review example and no patch.
No code here writes design files or establishes RTL/checkpoint equivalence.
"""
from difflib import unified_diff
from hashlib import sha256
from pathlib import PurePath
import re

from .fixes import CHECKS, ChangePreview, Evidence, FixPlan, Location


def factored(comparison):
    w, n = comparison.wide, comparison.narrow
    width, low = comparison.operand_type.width, comparison.narrow_width
    if not w or not n or not low:
        return None
    high = f"(|{w}[{width - 1}:{low}])"
    lower = f"({w}[{low - 1}:0] {comparison.operator} {n})"
    if comparison.operator in (">", ">=", "!="):
        return f"({high} || {lower})"
    return f"(!{high} && {lower})"


def _preview(result, register, comparison, native):
    proposed = factored(comparison)
    if not proposed:
        return None
    span = comparison.span
    data = result.source_index.texts[span.file].encode()
    if data[span.start:span.end].decode() != span.text:
        return None
    gates = []
    if comparison.unknowns_possible:
        gates.append("Four-state operands can change X/Z propagation. Prove known operands at every evaluation; no patch is emitted.")
    if register.parameterized:
        gates.append("The source has overridable parameters. Check every elaborated instance before using numeric bit slices; no patch is emitted.")
    if register.elaboration != "Supplied project hierarchy":
        gates.append("Only the isolated module elaborated. Full project/include/macro context is unresolved; no patch is emitted.")
    if not native:
        gates.append("Module ownership is inferred from report names or source tags; native scope mapping is missing. No patch is emitted.")
    status = "design_hypothesis" if gates else "review_diff"
    diff = ""
    if not gates:
        changed = (data[:span.start] + proposed.encode() + data[span.end:]).decode()
        # Safe informational filenames: the design's absolute path remains in
        # the location record. These diffs are never applied by TimingLens.
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", PurePath(span.file).name)
        diff = "".join(unified_diff(data.decode().splitlines(keepends=True), changed.splitlines(keepends=True),
                                    fromfile=f"a/{name}", tofile=f"b/{name}", n=3))
    return ChangePreview(Location(span.file, span.first, span.last, span.text), sha256(data).hexdigest(),
                         span.start, span.end, span.text, proposed, status, diff,
                         tuple(gates) or ("Review the source/checkpoint association, then validate this isolated expression change before use.",),
                         ("No register width, update ordering, reset assignment, handshake condition, or pipeline stage is changed.",
                          "For known unsigned operands, the comparison truth value is preserved; added latency is zero.",
                          "Area, routing, and physical timing benefit remain unmeasured for this design."))


def compare_enable(result, path, carry):
    session = result.session
    endpoint = session.pins.get(path.endpoint or "")
    cell = session.cells.get(endpoint.cell or "") if endpoint else None
    if (path.analysis != "setup" or not endpoint or endpoint.ref_pin != "CE"
            or not cell or not cell.sequential or len(carry) < 3):
        return None
    measured = Evidence(f"{path.id}:carry-to-ce", "measured",
                        f"{len(carry)} electrically consecutive carry primitives lie on the captured path to {path.endpoint}; slack {path.slack_ns} ns.",
                        (path.id,), (*carry, path.endpoint))

    def unresolved(reason):
        return FixPlan("rtl.mapping", "Resolve the RTL association for this carry-to-enable path", "evidence_review",
                       path.endpoint, (measured.statement,),
                       "Measured connectivity reaches a register enable, but the source operation is unresolved.",
                       "Cross-probe the endpoint and supply the matching top, module definitions and compile context.",
                       rule_version="2", evidence_links=(measured, Evidence(f"{path.id}:mapping", "unsupported", reason)),
                       unknowns=(reason,), limitations=("No RTL rewrite is emitted from an unresolved source association.",))

    link = result.cells[cell.name]
    modules = [m for m in result.source_index.modules.get(link.module or "", ()) if m.file == link.file]
    if len(modules) != 1:
        return unresolved("A unique source module is unavailable or duplicated.")
    module = modules[0]
    data = result.source_index.texts[module.file].encode()
    sources = [s for s in session.sources if s.path == module.file]
    if (len(sources) != 1 or sources[0].file_type == "UNMATCHED_REVISION"
            or (sources[0].sha256 and sources[0].sha256 != sha256(data).hexdigest())):
        return unresolved("The source bytes conflict with the captured manifest or source revision.")
    leaf = (cell.original_name or cell.name).rsplit("/", 1)[-1]
    match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_$]*)_reg(?:\[\d+\])*", leaf)
    if not match:
        return unresolved("The surviving endpoint name does not identify a plain register.")
    if not link.instance and "/" in cell.name:
        return unresolved("A source tag without a unique hardware instance cannot resolve register ownership.")
    register, reason = result.semantic_index.resolve(module, link.instance, match[1])
    if not register:
        return unresolved(reason)
    decisions = register.enable_decisions
    if not decisions:
        return None  # A comparison that chooses reset/data is not a hold enable.
    # Multiple guards can share a comparison; one preview per exact source span.
    comparisons = {c.span.start: c for d in decisions for c in d.comparisons}
    native = (bool(link.instance) and session.cells.get(link.instance)
              and session.cells[link.instance].properties.get("EVIDENCE_ORIGIN") != "RTL hierarchy inference")
    native = bool(native or (not link.instance and "/" not in cell.name and session.top == module.name))
    changes = tuple(p for c in comparisons.values() if (p := _preview(result, register, c, native)))
    locations = tuple(Location(d.span.file, d.span.first, d.span.last, f"{d.branch} branch: {d.span.text}") for d in decisions)
    name = f"{module.name}.{register.signal} ({register.type.width} bits)"
    links = [measured,
             Evidence(f"{path.id}:signal", "inferred", f"Surviving endpoint name associates the register with {register.instance}.{register.signal}; this is not netlist equivalence.", (path.id,), (cell.name,)),
             Evidence(f"{path.id}:type", "elaborated", f"{register.elaboration} {register.type.width}-bit {'signed' if register.type.signed else 'unsigned'} {'four-state' if register.type.four_state else 'two-state'} register; clock {register.updates[0].clock} ({register.updates[0].edge}).")]
    links += [Evidence(f"{path.id}:guard:{d.span.start}", "syntax", "Exact guard syntax; opposite branch holds this register.", location=l)
              for d, l in zip(decisions, locations)]
    unknowns = ("Source hashes identify captured bytes; they do not prove these sources built the supplied checkpoint.",
                "The measured carry-to-CE path does not identify which source comparison synthesized into those carries.")
    if register.elaboration != "Supplied project hierarchy":
        unknowns += (register.elaboration,)
    action = ("Review each bounded-operand comparison independently. Factor the upper-bit nonzero test and low-bit comparison only under the preview's conditions. "
              "Keep acceptance, error and reset logic in place; no buffering or validation pipeline is inserted.") if changes else (
              "Inspect the exact enable guard and its elaborated types. No supported bounded unsigned expression rewrite is available. "
              "Do not narrow the counter, remove reset, change signedness, or move validation across an acceptance boundary without a separate protocol proof.")
    return FixPlan("rtl.compare_enable", f"Shorten the comparison-to-enable path for {name}", "rtl_hypothesis",
                   f"{link.instance or module.name}; {path.endpoint}", tuple(e.statement for e in links),
                   "The clocked update has a comparison-dependent hold decision, and measured carries reach CE. The source association is a causal hypothesis; the exact syntax and elaborated widths are recorded separately.",
                   action, prerequisites=("Confirm optimized endpoint/module ownership in Vivado and match the captured source revision.",),
                   checks=(*CHECKS,
                           "Test comparison equality and adjacent values, zero, maximum values, and reset/enable combinations. Use equivalence for the complete changed cone when available.",
                           "For streaming logic, assert accepted-beat ownership, valid/data/sideband alignment, stability under backpressure, packet boundaries and invalid-beat suppression. Include outstanding beats, reset/abort and recovery.",
                           "Do not treat finite simulation or the binary expression identity as proof of arbitrary sequential equivalence or CDC safety."),
                   limitations=("Each preview is an independent alternative. No source files are changed and no timing gain is predicted.",),
                   source_candidates=locations,
                   next_steps=(f"Cross-probe {path.endpoint} to {name} and inspect the exact guard.",
                               "Review the proposed expression and its applicability conditions in Change preview." if changes else "Resolve the guard's functional contract; no safe expression preview is available.",
                               "Validate behavior in an isolated copy, then compare implementation under identical constraints and directives."),
                   rule_version="2", evidence_links=tuple(links),
                   applicability=("Complete measured setup path with at least three connected carry primitives terminating at sequential CE.",
                                  "One supported clocked writer; comparison guard has a holding opposite branch, rather than a reset or data-selection write."),
                   unknowns=unknowns, changes=changes)
