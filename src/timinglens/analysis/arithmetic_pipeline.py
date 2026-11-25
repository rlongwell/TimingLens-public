"""Tie a source-derived pipeline schedule to measured DSP hardware on the failing path."""
from difflib import unified_diff
from hashlib import sha256
from pathlib import PurePosixPath

from ..rtl.correlate import Confidence
from ..rtl.pipeline import pipeline
from ..rules.library import _arithmetic
from .fixes import CHECKS, ChangePreview, Evidence, FixPlan, Location, dfx_scope, internal_clock_path


def candidates(result):
    session = result.session
    found = {}
    if session.stage not in {"synthesized", "placed", "routed"} or dfx_scope(result):
        return found
    for path in session.paths:
        if (path.analysis != "setup" or path.slack_ns is None or path.slack_ns >= 0 or not result.coverage[path.id].complete
                or not internal_clock_path(session, path)):
            continue
        _, dsps, delay = _arithmetic(path, session)
        if dsps and (plan := recommend(result, path, dsps, delay)):
            found[path.id] = plan
    return found


def recommend(result, path, dsps, delay):
    if not path.datapath_ns or delay / path.datapath_ns < result.thresholds.dsp_fraction:
        return None
    endpoint = result.session.pins.get(path.endpoint)
    if not endpoint or endpoint.port:
        return None
    for name in dsps:
        local_delay = sum(a.delay_ns or 0 for a in path.arcs if a.kind == "cell" and a.resource == name)
        if local_delay < result.thresholds.dsp_fraction * path.datapath_ns:
            continue
        link = result.cells[name]
        tag = result.session.cells[name].source
        if (not tag or tag.provenance != "vivado_cell_file_name_line_number" or link.confidence != Confidence.EXACT
                or not link.file or not link.module or len(result.source_index.modules.get(link.module, ())) != 1):
            continue
        if link.instance:
            if not (endpoint.cell or "").startswith(link.instance + "/"):
                continue
        elif result.session.top != link.module or "/" in name or "/" in (endpoint.cell or ""):
            continue
        if any(result.session.cells[n].properties.get("DONT_TOUCH", "").lower() in {"1", "true"} for n in path.cells):
            continue
        files = [s for s in result.session.sources if s.path == link.file]
        text = result.source_index.texts.get(link.file, "")
        if (len(files) != 1 or files[0].file_type == "UNMATCHED_REVISION" or not text or len(text) > 32768
                or sha256(text.encode()).hexdigest() != files[0].sha256):
            continue
        model = pipeline(text)
        if (not model or model.module != link.module or tag.first_line != tag.last_line
                or tag.first_line not in model.multiply_lines):
            continue
        filename = PurePosixPath(link.file).name
        revised = text[:model.start] + model.body + text[model.end:]
        diff = "".join(unified_diff(text.splitlines(True), revised.splitlines(True), "a/" + filename, "b/" + filename))
        location = Location(link.file, text.count("\n", 0, model.start) + 1, text.count("\n", 0, model.end),
                            f"{model.module} drives {model.output} through {model.stages} register stages.")
        measured = Evidence(f"{path.id}:dsp", "measured",
                            f"{path.id} misses setup by {abs(path.slack_ns):.3f} ns. DSP cell arcs total {delay:.3f} ns on this path.",
                            (path.id,), tuple(dsps))
        source = Evidence(f"{path.id}:multiply", "syntax",
                          f"Vivado tags {name} at {filename}:{tag.first_line}, on a multiply in {model.module}. "
                          f"All arithmetic feeds the first register. The remaining {model.stages - 1} registers only delay its result.",
                          (path.id,), (name,), location)
        change = ChangePreview(location, files[0].sha256, model.start, model.end, text[model.start:model.end], model.body,
                               "review_diff", diff,
                               ("Prove cycle equivalence after pipeline fill and rebuild with the original constraints and directives.",),
                               (f"{model.stages}-edge latency, one result per edge, original widths, truncation and operand alignment.",))
        return FixPlan("rtl.redistribute_arithmetic", f"Pipeline the arithmetic in {model.module} across its {model.stages} existing cycles",
                       "rtl_hypothesis", link.module, (measured.statement, source.statement),
                       "Moving register boundaries between dependent operations shortens the combinational work per cycle. "
                       "Delay each side operand alongside the sample that uses it.",
                       "Try the generated RTL diff in an isolated copy.", checks=CHECKS, source_candidates=(location,),
                       next_steps=(*model.schedule, "Prove the interface and compare a same-recipe route."),
                       evidence_links=(measured, source), changes=(change,),
                       applicability=("Source digest matches the capture. The leaf has one free-running clock and a straight-line unsigned datapath.",),
                       unknowns=("Timing gain requires a new route. Review any hierarchical constraints, probes or external references to internal registers.",))
    return None
