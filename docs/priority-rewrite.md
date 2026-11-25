# Balanced priority-mux experiment

**Fix recommendations → Priority mux → Open example evidence** defaults to the [verified variant sweep](rtl-variant-sweeps.md). Select **Balanced priority tree · RTL rewrite** for the single-candidate experiment. **Try this experiment** opens the exact source diff and proof scope. **Run isolated experiment** creates fresh source copies, proves equivalence, simulates both versions and routes both with the same Default recipe. The source in `examples/priority` stays untouched.

## Candidate and controlled comparison

The original 16-lane priority chain selects the data bit associated with the highest asserted request index, or zero when no request is asserted. The candidate pairs adjacent requests into a balanced tree. Each node carries a valid flag and a selected value; the right subtree contains higher request indices and wins whenever valid. Sixteen leaves reduce through four binary merge levels. This describes the RTL structure, not a promise of four mapped LUT levels.

The top-level ports, `req_q`, `data_q`, output register, clock and original XDC remain unchanged. A request/data sample is captured on one rising edge and its selected result appears on the following rising edge. No pipeline stage, retiming or constraint exception is added. The serial `selected` wire is replaced by `priority_valid` and `priority_value` wires with KEEP attributes; KEEP_HIERARCHY is retained. The exact before/after source hashes are pinned in the runner.

Both implementations use byte-identical build and extraction scripts: synthesis of `priority_top` for `xc7z020clg400-1`, `opt_design`, `place_design -directive Default`, placement checkpoint, and `route_design -directive Default`. Both use Vivado 2024.2, the same 2 ns clock, two threads and the same compile context. This experiment measures the RTL change under that shared recipe. Each job contains one trial per variant; repeatability is not established.

The imported capture selects the experiment. A fresh original-RTL baseline is measured again, and the selected recommendation must still apply before the candidate implementation starts. Detailed endpoint samples and full register summaries remain separate. Register and full-example Lab comparisons retain their normal regression and acceptance checks; equivalence alone does not establish timing closure or board readiness.

## Equivalence gate

The qualified tool is **Yosys 0.69**, bundled for the desktop through the pinned `yowasp-yosys==0.69.0.0.post1233` package. The GUI and CLI can select a compatible executable explicitly. A missing or unqualified tool is an error; simulation never substitutes for the proof. First-time WebAssembly compilation runs at reduced priority on at most two available CPUs.

Yosys reads the exact staged baseline and candidate SystemVerilog. Its formal intermediate representations are flattened, then compared with `equiv_make`, `equiv_simple` and `equiv_status -assert`. Only hierarchy attributes in the formal representation are cleared to allow flattening; the staged source and Vivado preservation attributes remain intact. All 67 output, state and matched alias points must be proven. A successful exit alone is insufficient: the runner checks the completion log, the proof graph, the output/state coverage and source/script hashes before any Vivado implementation can run.

This proof is scoped to the bundled `priority_top` at **N=16**, binary inputs and corresponding register states. The unchanged state structure and proven transition functions preserve cycle behavior under that correspondence. It does not establish independent FPGA power-up state equality, four-state X/Z equivalence, other parameterizations, physical timing or implemented-netlist equivalence. These limits are visible in the preview and Lab check.

The method follows the official Yosys documentation for [equivalence checking passes](https://yosyshq.readthedocs.io/projects/yosys/en/stable/cmd/index_passes_equiv.html). [YoWASP](https://yowasp.org/) documents its Python tool distribution and executable names. No external solver service or network upload is used during a proof.

The original six-case priority testbench also runs separately against each staged RTL version. It covers competing requests and no request. These finite simulations supplement the proof. The narrowly scoped Verilator UNOPTFLAT warning handling remains necessary for forward dependencies represented within vectors; other diagnostics retain their normal behavior.

## Retained evidence and failure behavior

Each job retains its frozen trigger and selected recommendation, `source.patch`, the empty implementation `recipe.patch`, both source/constraint copies, two simulation logs, implementation logs, reports and checkpoints. The `equivalence` directory contains both actual RTL inputs, the Yosys script and version, complete log, proven graph and `result.json` with hashes and proof scope. Proof artifacts become checked inputs for subsequent phases, so a later alteration aborts the job.

Both portable Lab records embed the proof. Importing a declared passed equivalence check validates the retained proof, its source pair, the output/state points and the result metadata. The Lab's **Checks and context** tab shows **RTL equivalence** alongside timing, DRC and other checks; **Change preview** shows the RTL patch; **Evidence and sources** exposes proof details. Record hashes detect changed bytes, not producer authenticity or independent checkpoint equivalence.

Failure, timeout, cancellation, missing evidence or an incomplete proof stops implementation and retains the job. A failed restore cannot replace the current Lab comparison. Completed jobs reopen without rerunning tools. The existing workspace lock prevents overlapping counter and recommendation experiments. No board, UART, SSH, hardware server, deployment or active hash-project work is involved.

## CLI

```bash
./timinglens.sh try-experiment --session results/verified/priority/analysis.json --plan rtl.priority_balanced --preview
./timinglens.sh try-experiment --session results/verified/priority/analysis.json --plan rtl.priority_balanced --output results/recommendations/priority-balanced-01
```

Use `--yosys`, `--vivado`, `--verilator` and `--timeout` to select tools and a per-tool timeout. Output must be a new directory. A CLI-only installation can install `timinglens[formal]` to obtain the qualified Yosys package. GUI settings preserve the formal executable alongside existing runner history without replacing counter or Lab preferences.
