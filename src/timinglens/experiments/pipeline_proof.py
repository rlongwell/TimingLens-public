"""Prove a generated leaf rewrite for every binary input stream after pipeline fill."""
from __future__ import annotations

import ctypes
from ctypes.util import find_library
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import subprocess

from ..rtl.pipeline import Pipeline, pipeline
from ..vivado.runner import VivadoError, discover
from .equivalence import command_prefix, discover_yosys
from .models import canonical


PROOF_PREFIX = "pipeline-proof/"
PROOF_FILES = ("baseline.sv", "candidate.sv", "baseline.smt2", "candidate.smt2",
               "baseline.ys", "candidate.ys", "check.smt2", "solver.txt")
SCOPE = "Leaf output after pipeline fill, arbitrary binary inputs each edge and independent arbitrary initial states."


@dataclass(frozen=True)
class Candidate:
    source: str
    revised: str
    model: Pipeline
    filename: str
    diff: str
    path_id: str
    trigger_sha256: str


def trigger_digest(session, path_id):
    path = next((p for p in session.paths if p.id == path_id), None)
    if not path:
        raise ValueError("The baseline record is missing the path that triggered the recommendation.")
    evidence = session.model_dump(include={"top", "part", "vivado", "stage", "clocks", "summary"})
    evidence["path"] = path.model_dump()
    return sha256(canonical(evidence)).hexdigest()


def prepare(result, plan):
    if not plan or plan.id != "rtl.redistribute_arithmetic" or len(plan.changes) != 1:
        raise ValueError("Select an arithmetic pipeline recommendation with a source diff.")
    change = plan.changes[0]
    source = result.source_index.texts[change.location.file]
    model = pipeline(source)
    if (not model or sha256(source.encode()).hexdigest() != change.source_sha256 or
            (change.start_byte, change.end_byte, change.original, change.proposed) !=
            (model.start, model.end, source[model.start:model.end], model.body)):
        raise ValueError("The suggested edit no longer matches the captured source.")
    path_id = plan.evidence_links[0].path_ids[0]
    return Candidate(source, source[:model.start] + model.body + source[model.end:], model,
                     change.location.file, change.unified_diff, path_id, trigger_digest(result.session, path_id))


def _input_order(smt, design, model):
    # Read the constructor order from Yosys. Declaration order in the RTL can differ.
    fields = re.findall(r"^\s*\(" + design + r"_Inputs_(\w+) \(_ BitVec (\d+)\)\)", smt, re.M)
    if len(fields) != len(model.inputs) or {k: int(w) for k, w in fields} != dict(model.inputs):
        raise ValueError("Yosys input ports differ from the captured module interface.")
    outputs = re.findall(r"^\s*\(" + design + r"_Outputs_(\w+) \(_ BitVec (\d+)\)\)", smt, re.M)
    if outputs != [(model.output, str(model.output_width))]:
        raise ValueError("Yosys output ports differ from the captured module interface.")
    return [key for key, width in fields]


def miter(models, model):
    lines = ["(set-option :timeout 60000)"]
    orders = {}
    for design, smt in models.items():
        orders[design] = _input_order(smt, design, model)
        for line in smt.splitlines():
            if design == "baseline" or not line.startswith("(declare-datatypes ((Pair "):
                lines.append(line)
        lines.append(f"(declare-const {design}_s0 {design}_State)")
    for step in range(model.stages + 1):
        inputs = {}
        for index, (name, width) in enumerate(model.inputs):
            if name == model.clock:
                inputs[name] = "#b1"  # formalff has converted the sole clock to an implicit edge.
            else:
                inputs[name] = f"input_{index}_{step}"
                lines.append(f"(declare-const {inputs[name]} (_ BitVec {width}))")
        for design, order in orders.items():
            ports = " ".join(inputs[key] for key in order)
            pair = f"{design}_p{step}"
            lines.extend((
                f"(define-fun {pair} () (Pair {design}_Outputs {design}_State) "
                f"({design} ({design}_Inputs {ports}) {design}_s{step}))",
                f"(define-fun {design}_s{step+1} () {design}_State (second {pair}))",
                f"(define-fun {design}_q{step} () (_ BitVec {model.output_width}) "
                f"({design}_Outputs_{model.output} (first {pair})))",
            ))
    # The pre-fill query checks that independent starting states can actually differ.
    # Arbitrary starting state at the beginning of any N-edge window covers all later cycles.
    for edge in (model.stages - 1, model.stages):
        lines.extend(("(push)", f"(assert (distinct baseline_q{edge} candidate_q{edge}))", "(check-sat)", "(pop)"))
    return "\n".join(lines) + "\n"


def solve(problem, library=None):
    if not library and (exe := shutil.which("z3")):
        return subprocess.run([exe, "-in"], input=problem, capture_output=True, text=True,
                              check=True, timeout=150).stdout.strip()
    if not library:
        library = find_library("z3")
    if not library:
        try:
            vendor = discover().resolve().parents[1] / "lib/lnx64.o/libz3.so"
            library = str(vendor) if vendor.is_file() else None
        except VivadoError:
            pass
    if not library:
        raise ValueError("Install Z3, or pass the path to libz3 with --z3-library.")
    z3 = ctypes.CDLL(str(library))
    ptr = ctypes.c_void_p
    z3.Z3_mk_config.restype = ptr
    z3.Z3_mk_context.argtypes = [ptr]
    z3.Z3_mk_context.restype = ptr
    z3.Z3_eval_smtlib2_string.argtypes = [ptr, ctypes.c_char_p]
    z3.Z3_eval_smtlib2_string.restype = ctypes.c_char_p
    z3.Z3_del_context.argtypes = z3.Z3_del_config.argtypes = [ptr]
    config = z3.Z3_mk_config()
    context = z3.Z3_mk_context(config)
    # libz3's default error handler may exit the host application. Report solver errors
    # through the returned transcript, just like the CLI backend.
    handler_type = ctypes.CFUNCTYPE(None, ptr, ctypes.c_int)
    handler = handler_type(lambda context, code: None)
    z3.Z3_set_error_handler.argtypes = [ptr, handler_type]
    z3.Z3_set_error_handler(context, handler)
    try:
        return z3.Z3_eval_smtlib2_string(context, problem.encode()).decode().strip()
    finally:
        z3.Z3_del_context(context)
        z3.Z3_del_config(config)


def verify(candidate, output: Path, *, yosys=None, z3_library=None):
    """Write an isolated, replayable proof. Every status other than passed is unverified."""
    output.mkdir(parents=True, exist_ok=False)
    model = candidate.model
    checks = {
        "module": model.module, "source_file": candidate.filename, "path_id": candidate.path_id,
        "trigger_sha256": candidate.trigger_sha256, "latency_edges": model.stages,
        "schedule": model.schedule, "status": "incomplete",
        "scope": SCOPE,
        "timing": "Requires a same-recipe implementation.",
        "source_sha256": {name: sha256(source.encode()).hexdigest() for name, source in
                          (("baseline", candidate.source), ("candidate", candidate.revised))},
    }
    report = output / "proof.json"
    report.write_text(json.dumps(checks, indent=2) + "\n")
    try:
        (output / "candidate.patch").write_text(candidate.diff)
        models = {}
        for design, source in (("baseline", candidate.source), ("candidate", candidate.revised)):
            (output / f"{design}.sv").write_text(source)
        executable = discover_yosys(yosys)
        for design in ("baseline", "candidate"):
            rename = f"rename {model.module} {design}\n" if model.module != design else ""
            script = (f"read_verilog -sv {design}.sv\nprep -top {model.module}\ncheck -assert\nformalff -clk2ff\n"
                      f"{rename}write_functional_smt2 {design}.smt2\n")
            script_file = f"{design}.ys"
            (output / script_file).write_text(script)
            with (output / f"{design}.log").open("w") as log:
                subprocess.run([*command_prefix(), executable, "-s", script_file], cwd=output,
                               stdout=log, stderr=subprocess.STDOUT, check=True, timeout=60)
            models[design] = (output / f"{design}.smt2").read_text()
        problem = miter(models, model)
        (output / "check.smt2").write_text(problem)
        answer = solve(problem, z3_library)
        (output / "solver.txt").write_text(answer + "\n")
        if answer.split() == ["sat", "sat"]:
            checks["status"] = "counterexample"
            raise ValueError("The solver found an output mismatch after pipeline fill.")
        if answer.split() != ["sat", "unsat"]:
            raise ValueError("Equivalence was inconclusive. Inspect solver.txt.")
        checks["files_sha256"] = {name: sha256((output / name).read_bytes()).hexdigest() for name in PROOF_FILES}
        checks["status"] = "passed"
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        checks["error"] = str(error)
        raise ValueError(f"Proof did not pass. {error} Evidence in {output}") from error
    finally:
        report.write_text(json.dumps(checks, indent=2) + "\n")
    return report


def validate_attached_pipeline(run):
    """Validate a portable proof record offline without executing embedded content."""
    def attachment(name):
        value = run.attachments.get(PROOF_PREFIX + name)
        if not value:
            raise ValueError(f"Arithmetic equivalence record is missing {name}.")
        return value

    proof = json.loads(attachment("proof.json"))
    files = {name: attachment(name) for name in PROOF_FILES}
    hashes = {name: sha256(value.encode()).hexdigest() for name, value in files.items()}
    expected = {key: hashes[key + ".sv"] for key in ("baseline", "candidate")}
    if (not isinstance(proof, dict) or proof.get("files_sha256") != hashes or proof.get("source_sha256") != expected
            or proof.get("scope") != SCOPE or proof.get("status") != "passed" or files["solver.txt"].split() != ["sat", "unsat"]):
        raise ValueError("Arithmetic equivalence evidence or solver transcript disagrees with its proof record.")
    baseline = files["baseline.sv"]
    model = pipeline(baseline)
    if (not model or proof.get("module") != model.module or proof.get("latency_edges") != model.stages
            or proof.get("schedule") != list(model.schedule)
            or baseline[:model.start] + model.body + baseline[model.end:] != files["candidate.sv"]):
        raise ValueError("The attached pipeline differs from the generated RTL or its cycle schedule.")
    if (expected["candidate"] not in run.context.sources.values() or
            not any(s.sha256 == expected["candidate"] and s.text == files["candidate.sv"] for s in run.session.sources)):
        raise ValueError("Arithmetic equivalence proof does not cover the routed candidate source.")
    models = {key: files[key + ".smt2"] for key in ("baseline", "candidate")}
    if miter(models, model) != files["check.smt2"]:
        raise ValueError("The attached solver query does not compare these models over the stated latency.")


def compare_routed(candidate, proof_path, before, after):
    """Bind the proven source pair to a controlled physical experiment."""
    from .compare import compare
    from .models import Artifact, Check, Run

    proof_text = proof_path.read_text()
    proof = json.loads(proof_text)
    digests = {key: sha256(text.encode()).hexdigest() for key, text in
               (("baseline", candidate.source), ("candidate", candidate.revised))}
    if trigger_digest(before.session, candidate.path_id) != candidate.trigger_sha256:
        raise ValueError("The routed baseline differs from the capture that triggered this edit.")
    if proof["status"] != "passed" or proof["source_sha256"] != digests or proof.get("trigger_sha256") != candidate.trigger_sha256:
        raise ValueError("The proof does not establish equivalence for this source pair.")
    if (proof_path.parent / "solver.txt").read_text().split() != ["sat", "unsat"]:
        raise ValueError("The solver transcript must establish equivalence after pipeline fill.")
    a, b = before.context.sources, after.context.sources
    changed = [key for key in a if a[key] != b.get(key)]
    if (a.keys() != b.keys() or len(changed) != 1 or a[changed[0]] != digests["baseline"]
            or b[changed[0]] != digests["candidate"]):
        raise ValueError("The routed records must differ by exactly the source edit that passed equivalence.")
    for run, key in ((before, "baseline"), (after, "candidate")):
        if (run.session.stage != "routed" or run.population != "design" or run.context.mode != "integrated"
                or not run.context.checkpoint_sha256 or not any(s.sha256 == digests[key] and s.text is not None
                                                               and sha256(s.text.encode()).hexdigest() == digests[key]
                                                               for s in run.session.sources)):
            raise ValueError("Each record needs integrated, design-wide routed evidence and the matching embedded RTL.")
    if not any(c.name == "source_checkpoint" and c.status == "passed" for c in before.checks):
        raise ValueError("The baseline run requires evidence linking its source to the routed checkpoint.")
    if not before.context.directives or before.context.directives != after.context.directives:
        raise ValueError("The routed records require identical implementation recipes.")
    if any(c.name == "equivalence" and c.status == "failed" for c in after.checks):
        raise ValueError("The candidate record already contains a failing equivalence check.")
    check = Check(name="equivalence", status="passed", scope=proof["scope"],
                  evidence=f"Yosys and Z3 proved the generated {candidate.model.stages}-edge pipeline. See the attached proof.")
    if "equivalence/result.json" in after.attachments:
        raise ValueError("Candidate already contains a proof with a different verification scope.")
    bundle = {PROOF_PREFIX + name: (proof_path.parent / name).read_bytes().decode() for name in (*PROOF_FILES, "proof.json")}
    artifacts = [Artifact(name=key, kind="validation", sha256=sha256(text.encode()).hexdigest()) for key, text in bundle.items()]
    after = after.model_copy(update={
        "checks": [c for c in after.checks if c.name != "equivalence"] + [check],
        "attachments": {**after.attachments, **bundle},
        "artifacts": [a for a in after.artifacts if a.name not in bundle] + artifacts,
        "change_diff": candidate.diff,
    })
    # Revalidate the complete record here and on import. model_copy alone bypasses validators.
    return compare(before, Run.model_validate(after.model_dump()))
