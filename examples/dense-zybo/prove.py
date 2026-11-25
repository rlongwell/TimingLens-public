"""Check the four-cycle calibration interface with Yosys and a word-level Z3 miter."""
import argparse
import ctypes
from ctypes.util import find_library
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess


def solve(problem, library):
    if not library and shutil.which("z3"):
        return subprocess.check_output(["z3", "-in"], input=problem, text=True).strip()
    z3 = ctypes.CDLL(library or find_library("z3") or "libz3.so")
    ptr = ctypes.c_void_p
    z3.Z3_mk_config.restype = ptr
    z3.Z3_mk_context.argtypes = [ptr]
    z3.Z3_mk_context.restype = ptr
    z3.Z3_eval_smtlib2_string.argtypes = [ptr, ctypes.c_char_p]
    z3.Z3_eval_smtlib2_string.restype = ctypes.c_char_p
    z3.Z3_del_context.argtypes = [ptr]
    z3.Z3_del_config.argtypes = [ptr]
    config = z3.Z3_mk_config()
    context = z3.Z3_mk_context(config)
    try:
        return z3.Z3_eval_smtlib2_string(context, problem.encode()).decode().strip()
    finally:
        z3.Z3_del_context(context)
        z3.Z3_del_config(config)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ("original", "revised", "output"):
        p.add_argument(arg, type=Path)
    p.add_argument("--yosys", default="yosys")
    p.add_argument("--z3-library", help="optional path to libz3 if the z3 CLI is unavailable")
    args = p.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    lines = ["(set-option :timeout 90000)"]
    hashes = {}
    for name in ("original", "revised"):
        source = getattr(args, name).read_bytes()
        hashes[name] = sha256(source).hexdigest()
        (out / (name + ".v")).write_bytes(source)
        command = (f"read_verilog {name}.v; prep -top calibration; formalff -clk2ff; "
                   f"rename calibration {name}; write_functional_smt2 {name}.smt2")
        with (out / (name + ".log")).open("w") as log:
            subprocess.run([args.yosys, "-p", command], cwd=out, stdout=log, stderr=subprocess.STDOUT, check=True)
        smt = (out / (name + ".smt2")).read_text().splitlines()
        # Both Yosys models declare the same polymorphic Pair datatype.
        lines.extend(x for x in smt if name == "original" or not x.startswith("(declare-datatypes ((Pair "))
        lines.append(f"(declare-const {name}_s0 {name}_State)")
    for step in range(5):
        inputs = [f"{port}{step}" for port in ("a", "b", "bias", "scale")]
        lines.extend(f"(declare-const {port} (_ BitVec 16))" for port in inputs)
        for name in ("original", "revised"):
            args_i = " ".join(inputs)
            pair = f"{name}_p{step}"
            lines.append(f"(define-fun {pair} () (Pair {name}_Outputs {name}_State) "
                         f"({name} ({name}_Inputs #b1 {args_i}) {name}_s{step}))")
            lines.append(f"(define-fun {name}_s{step+1} () {name}_State (second {pair}))")
            lines.append(f"(define-fun {name}_q{step} () (_ BitVec 32) ({name}_Outputs_result (first {pair})))")
    for step in (3, 4):
        lines.extend(["(push)", f"(assert (distinct original_q{step} revised_q{step}))",
                      "(check-sat)", "(pop)"])
    problem = "\n".join(lines) + "\n"
    (out / "check.smt2").write_text(problem)
    answer = solve(problem, args.z3_library)
    (out / "solver.txt").write_text(answer + "\n")
    assert answer.split() == ["sat", "unsat"], answer
    result = dict(status="passed", source_sha256=hashes, arbitrary_initial_state=True,
                  two_state_inputs="a, b, bias, scale are independent 16-bit words at every edge",
                  after_three_edges="mismatching outputs possible from arbitrary internal state",
                  after_four_edges="no 32-bit result mismatch possible")
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
