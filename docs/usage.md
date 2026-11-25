# Using TimingLens

Run the commands below from the repository root. For a tour of the desktop with real captures, see the [illustrated user guide](visual-guide.md) and [example walkthroughs](../examples/README.md).

## Start

Use Ubuntu with Python 3.11 or later and `python3-venv`. The desktop uses PySide6. Live timing collection uses a separate Vivado installation with Zynq-7000 device support. The example flow uses the Vivado device model.

```bash
./dashboard.sh
./timinglens.sh doctor
```

The launcher installs pinned direct dependencies into the repository's `.venv` on first use. Dark mode is the initial default. The sidebar switches themes and the execution page accepts a manual Vivado path. The validated Vivado release is 2024.2. The examples target the Digilent Zybo Z7-20 device `xc7z020clg400-1`.

## Analyze a design

```bash
./timinglens.sh analyze --project /path/to/project.xpr --output results/project
./timinglens.sh analyze --checkpoint /path/to/design.dcp --source /path/to/top.sv --output results/checkpoint
./timinglens.sh import --report results/project/analysis.json
./dashboard.sh results/project/analysis.json
```

Project inspection opens the XPR read-only and selects the current completed implementation run first, then the current completed synthesis run. Use `--run` for a named run. Use `--build synth` or `--build route` to create an isolated Vivado project copy and build there. Each operation has a separate `vivado-*` folder containing its log and raw reports. Use a fresh output directory for each export.

Vivado discovery checks the configured executable, `TIMINGLENS_VIVADO`, `XILINX_VIVADO`, `PATH`, and common Linux installation directories. Specify `--vivado /path/to/bin/vivado` on the CLI to override discovery.

Each successful analysis writes three files.

- `analysis.json` with the measurements, graph, source manifest, and thresholds for reopening the session.
- `diagnostics.json` with findings, ranked groups, correlation evidence, and recommendation definitions.
- `report.html` with the summary, measured-delay coverage, path details, recommendations, and raw Vivado evidence.

Set `--max-paths` and `--paths-per-endpoint` to adjust coverage. The CLI exits with 0 for a completed analysis, 1 for an operation failure, 2 for invalid arguments, and 130 for cancellation. The dashboard uses Vivado’s design-wide timing summary for slack totals and failing endpoints. A capped path collection is reported separately. Use `--thresholds threshold-file.json` to override specific rule thresholds. For example, `{"fanout": 96, "logic_levels": 10}`.

The default session includes copies of discovered HDL source within the source size limits. Use `--no-source-text` or clear the corresponding desktop checkbox to omit them. Source identifiers and paths can still appear in Vivado reports. On CLI import, `--resolve-local-sources` allows hash-checked reads of referenced local source files.

## Add project files and get specific fix candidates

The **Project files** desktop page accepts timing reports or a saved session together with RTL, Tcl/BD, XDC, and optional design intent. The equivalent offline command is:

```bash
./timinglens.sh inspect --files reports/paths.rpt reports/timing_summary.rpt \
  rtl/top.sv design.bd constraints/timing.xdc --top top --output results/review
```

Recommendations include release-specific Vivado recipes, semantic comparison-to-enable reviews with exact expression previews, gated interface slice/FIFO reviews, and constraint audits. Supported binary expressions receive review diffs; four-state or unresolved cases receive hypotheses without a patch. The dashboard leads to one investigation, combining symptoms of the same captured path set. Each candidate includes labeled evidence, unknowns and acceptance checks. Timing exceptions require functional intent; negative slack alone never warrants a false path. See the [supported rules and intent format](project-analysis.md) and [semantic review evaluation](semantic-review.md).

### Verify an arithmetic pipeline fix

Open a failing session with its matching RTL and select **Fix recommendations**. When a slow DSP arc maps to a multiply in a free-running arithmetic pipeline, TimingLens traces the dependent operations, finds existing delay registers, and generates a cycle-by-cycle RTL edit. Multiple hardware instances with the same proven source association share one investigation. **Verify RTL fix…** saves both sources and the diff in a new directory and runs Yosys and Z3. The CLI selects the highest-ranked eligible arithmetic fix automatically.

```bash
timinglens verify-fix --session results/dense-zybo/base6/analysis.json --output results/pipeline-proof
```

The proof checks every output bit after pipeline fill for arbitrary binary input sequences and arbitrary initial register states. The rule handles a single-clock, unsigned leaf with fixed widths, one registered output, and enough existing cycles to split the datapath. Designs with reset, enables, feedback, ambiguous source ownership, or incomplete path evidence require review. Check timing with a fresh implementation using the baseline clock, constraints and recipe. Inspect the saved proof in `proof.json`, the generated RTL in `candidate.sv`, and the changes in `candidate.patch`. If both routed Experiment Lab run records are available, add `--routed-pair baseline.run.json candidate.run.json`. TimingLens checks that the only source change is the proven edit, checks the recipe, and evaluates the physical results using the Lab acceptance checks. The comparison and proof are saved together.



## Compare experiments

Open **Experiment Lab** in the desktop sidebar. Choose a retained counter or DFX example and click **Load example**, or **Import runs…** to select native `analysis.json` captures or self-contained `.run.json` records. Select a baseline and candidate, then **Compare**. Endpoint rows open in the existing path viewer; the evidence tab includes captured RTL, reports, manifests and scoped validation logs. History and theme preferences stay under `.settings/`.

```bash
./timinglens.sh compare --baseline before.run.json --candidate after.run.json --output results/comparison-01
```

Comparisons distinguish measured improvements from acceptance readiness. A better WNS cannot hide more failing endpoints, a hold regression, or a failed validation check. Missing measurements stay **Not tested**. Exports contain both complete run records, `comparison.json`, and a standalone HTML report; existing export directories are never overwritten. Comparison and path inspection use embedded evidence without opening checkpoints, running Vivado, executing Tcl or resolving referenced source paths. See [Experiment Lab](experiment-lab.md) for evidence semantics and the retained example results.

## Automatically try and apply a timing or resource fix

Open **Add design…**, select a local Vivado project (`.xpr`), and choose **Automatic fixes**. Select **Apply verified fixes in a project copy** to keep the candidate separately or **Update the selected project after verification** for an in-place change with an original-file backup. Click **Run and apply verified fixes**. The choice persists across sessions.

TimingLens routes the baseline, identifies a supported change from failing paths, validates its behavior, then routes the candidate using the same clock constraints and implementation recipe. Supported edits include redistributing arithmetic across existing RTL pipeline cycles and changing a Xilinx Multiplier Generator in IP Integrator from LUTs to DSPs. A successful run opens its before/after evidence in Experiment Lab.

```bash
./timinglens.sh auto-fix --project design/top.xpr --output results/fix-01 --apply-to-source
```

Turn on **Rebalance overused resources** and choose a utilization limit to free device capacity, including on projects that already meet timing. The runner can move a Xilinx multiplier between DSPs and LUTs, or a supported inferred memory between block RAM and distributed RAM. It checks the receiving resource, simulates the edited block, routes the whole design, and records the measured tradeoff in Experiment Lab. The CLI equivalent is `--resource-limit 85`. Try the [resource-balancing examples](../examples/resource-balance/README.md).

See [automatic fix behavior and supported inputs](automatic-fixes.md) and the [dense Zybo examples](../examples/dense-suite/README.md).

## Run a counter experiment

Choose **Show tools and details → Counter experiment** in the sidebar, or **Run counter…** from Experiment Lab. Review the 32-bit or 64-bit comparison rewrite and click **Run isolated experiment**. The runner validates baseline and candidate against an independent finite simulation oracle, then builds and routes each in a fresh directory. Completed register results open automatically in the Lab; **Compare whole core** opens the separate full-design summary. Cancellation stops only the runner's tool process group and retains the job evidence.

```bash
./timinglens.sh experiment --example counter32 --preview
./timinglens.sh experiment --example counter32 --output results/counter32-01
./timinglens.sh experiment --example counter64 --output results/counter64-01
```

The runner supports the 32-bit and 64-bit stress profiles and the separate 32-bit 250 MHz profile with Vivado 2024.2 and Verilator. It uses two threads per tool, sequential implementations, a per-tool timeout, and a workspace lock. It does not accept arbitrary projects, imported Tcl, or patches. Source copies, diffs, logs, checkpoints, job state, four portable run records, and both comparison reports stay in the job directory. A completed experiment can still be regressed or blocked by the Lab. See [counter runner details](counter-runner.md).

Choose **Implementation → Strategy sweep · 3 recipes** to try Default, Performance_Explore and Performance_ExtraTimingOpt. The runner builds the original RTL once with Default and the same factored candidate with each recipe, sequentially. Results open in **Experiment Lab → Strategy sweeps**, where register and global OOC rankings remain separate. Select a row to read measured regression explanations, compare it against the candidate's Default build or the original RTL, or export the complete sweep.

```bash
./timinglens.sh experiment --example counter32 --sweep --preview
./timinglens.sh experiment --example counter32 --sweep --output results/counter32-sweep-01
```

Ranking favors avoiding regressions before timing gains; it never approves a design change. Failed or incomplete recipes remain visible and unranked. See [strategy sweep recipes, ranking and limitations](strategy-sweeps.md).

## Try a Fix recommendation

In **Fix recommendations**, choose **Deep logic**, **Priority mux** or **High fanout**, then **Open example evidence**. Select the suggested implementation recipe and click **Try this experiment**. Review the frozen source, clock and recipe before **Run isolated experiment**. The runner simulates the unchanged example, builds a fresh Default baseline, checks that the recommendation still applies, and runs the candidate in its own directory. Completed register results open in Experiment Lab; **Compare design** shows the separate full-example population.

Deep logic starts with Performance_ExploreWithRemap. Priority mux starts with the verified RTL sweep described below. High fanout starts with AggressiveFanoutOpt on a copy of the fresh baseline's placed checkpoint. RTL, constraints and preservation attributes stay intact. Results can regress; the Lab retains acceptance checks and separate populations. **Open last job** reloads evidence without executing tools.

```bash
./timinglens.sh try-experiment --session results/verified/deep/analysis.json --plan vivado.remap --preview
./timinglens.sh try-experiment --session results/verified/deep/analysis.json --plan vivado.remap --output results/recommendations/deep-01
```

See [supported recommendations, validation scope and retained evidence](recommendation-experiments.md). This first version runs the pinned bundled examples with Vivado 2024.2; it does not apply arbitrary RTL edits or deploy hardware.

The priority example also offers **Balanced priority tree · RTL rewrite**. It previews a source-exact four-level tree, proves RTL equivalence with Yosys 0.69, simulates both versions and builds both with the same Default recipe. A missing, failed or incomplete proof stops the job before Vivado implementation. The Lab includes an **RTL equivalence** check, the source diff and the embedded proof. The desktop dependencies include the qualified Yosys package; CLI-only installations can use the `formal` extra or `--yosys`.

```bash
./timinglens.sh try-experiment --session results/verified/priority/analysis.json --plan rtl.priority_balanced --preview
./timinglens.sh try-experiment --session results/verified/priority/analysis.json --plan rtl.priority_balanced --output results/recommendations/priority-balanced-01
```

See [balanced rewrite, proof scope and comparison controls](priority-rewrite.md).

Priority mux now defaults to **Verified RTL variants · 3 candidates**: balanced tree, grouped selection and priority mask. Review each diff, then run three independent equivalence gates and same-recipe implementations against one shared original build. **Experiment Lab → RTL variants** shows the original and candidates on a clickable timing/LUT plot, their measured frontier, optional LUT limits, regressions and separate acceptance checks. Failed candidates remain visible; complete evidence exports and reopens offline.

```bash
./timinglens.sh try-experiment --session results/verified/priority/analysis.json --plan rtl.priority_sweep --preview
./timinglens.sh try-experiment --session results/verified/priority/analysis.json --plan rtl.priority_sweep --output results/recommendations/priority-sweep-01
```

See [verified variants, shared baseline, tradeoff policy and proof limits](rtl-variant-sweeps.md).

## Run the examples

```bash
./timinglens.sh demo --run-vivado --output results/demo
./timinglens.sh demo --run-vivado --design deep --build synth --output results/synth-deep
./scripts/verify.sh
./scripts/verify.sh --with-vivado
```

The examples include synthesizable RTL, timing XDC, and self-checking SystemVerilog testbenches. The verification script runs simulation when Verilator is installed. The Vivado tests are opt-in and exercise synthesis, placement, routing, project and checkpoint imports, and cancellation.

For a whole-design example, the [25-block telemetry fabric](../examples/telemetry-bd/README.md) recreates a routed IP Integrator design and checks TimingLens against independent Vivado queries for all 715 failing setup endpoints.

The [dense Zybo Z7-20 example](../examples/dense-zybo/README.md) closes 125 MHz timing on a 104-lane design occupying 99.67% of the slices. It includes the failing and passing RTL, functional checks and a reproducible Experiment Lab comparison.

## Integrate with Python

```python
from pathlib import Path
from timinglens import analyze, read_session

session = read_session(Path("results/project/analysis.json"))
result = analyze(session)
for group in result.groups:
    print(group.rule, group.anchor, group.worst_slack_ns, group.path_ids)
```

Install `pip install .` for the CLI and analysis API or `pip install '.[gui]'` for the desktop. See [architecture](architecture.md), [the session format](session-format.md), and [validation results](validation.md).

TimingLens supports the additional Partition/PBlock columns in Vivado DFX path reports. Missing detailed delays are reported explicitly even when design-wide timing totals are available. Source line tags are navigation hints; optimized hardware may combine multiple expressions. Use the measured graph and raw path to confirm a proposed change, then rerun implementation and functional checks.
