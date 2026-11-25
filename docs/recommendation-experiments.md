# Try this experiment

Fix recommendations now connect measured issues to reviewable, isolated implementation experiments for the bundled deep-logic, priority-mux and high-fanout examples. Opening a preview does not run tools. A completed job opens its register comparison in Experiment Lab; the runner also offers the separate full-example comparison.

The priority example additionally supports [a balanced RTL rewrite with an equivalence gate](priority-rewrite.md). Its example shortcut selects that rewrite first. The recipe-only experiments described below remain available in the candidate selector.

## Desktop workflow

1. Open **Fix recommendations**. Choose an example and **Open example evidence**, or open a native `analysis.json` with matching embedded evidence. The example shortcut reads the existing `results/verified/<example>/analysis.json`; it never starts a capture.
2. Select an eligible implementation recommendation and click **Try this experiment**. The preview identifies the frozen trigger, exact recipe, build context and finite simulation scope. Unsupported or insufficiently evidenced selections explain why execution is unavailable.
3. Choose a results parent folder and click **Run isolated experiment**. A new timestamped job directory receives private input copies; existing jobs are never overwritten. The experiment uses two threads and runs sequentially at reduced process priority.
4. Review the register comparison in **Experiment Lab**. **Compare design** returns the independent full-example view. Inspect endpoints, gates, the Tcl recipe diff and embedded provenance before drawing conclusions. A timing gain does not approve the candidate.
5. **Open last job** validates and reloads completed records without tools. Failed jobs show their retained error. Cancellation terminates only this runner's process group and keeps completed evidence; closing the window waits for workers to stop.

The repository must already contain completed example evidence for its shortcut. If it is absent, the UI gives the existing `timinglens demo --run-vivado --design ...` command. Installed distributions include source, constraints and testbenches, but do not ship local capture results.

## Supported recipes and exact inputs

| Example | First recipe | Candidate starting point |
| --- | --- | --- |
| Deep logic | Performance_ExploreWithRemap | Fresh synthesis of the pinned example |
| Priority mux | Performance_ExploreWithRemap | Fresh synthesis of the pinned example |
| High fanout | AggressiveFanoutOpt | Byte-verified copy of the fresh Default baseline's placed checkpoint |

Performance_ExtraTimingOpt is also executable when the analysis offers it for one of these examples. All recipes are allowlisted code; imported recommendation commands are never executed.

Performance_ExploreWithRemap runs `opt_design -directive ExploreWithRemap`, `place_design -directive Explore`, `phys_opt_design -directive Explore`, then `route_design -directive NoTimingRelaxation`. The fanout candidate runs `open_checkpoint placement.dcp`, `phys_opt_design -directive AggressiveFanoutOpt`, then `route_design -directive Default`. Its optimization and placement context are inherited from the Default baseline. Each baseline saves its placement before routing.

These command choices follow AMD's Vivado 2024.2 tables for [optimization and placement directives](https://docs.amd.com/r/2024.2-English/ug904-vivado-implementation/Directives-Used-by-opt_design-and-place_design-in-Implementation-Strategies), [physical optimization and routing directives](https://docs.amd.com/r/2024.2-English/ug904-vivado-implementation/Directives-Used-by-phys_opt_design-and-route_design-in-Implementation-Strategies), and the [phys_opt_design command](https://docs.amd.com/r/2024.2-English/ug835-vivado-tcl-commands/phys_opt_design).

The runner requires Vivado 2024.2, `xc7z020clg400-1`, one matching clock and exact embedded source bytes from a supported example. It pins SHA-256 hashes of the packaged RTL, XDC and testbench and checks staged inputs between phases. Extra sources, changed known constraints, DFX context and insufficient analysis are rejected. Missing constraint bytes in an older trigger do not prove that trigger's original build context: imported evidence only selects the experiment, and a fresh pair is built with the pinned constraints. The fresh baseline must independently offer the selected recommendation before the candidate can run.

All RTL, constraints, KEEP, KEEP_HIERARCHY and DONT_TOUCH attributes remain unchanged. The fanout example deliberately preserves registers; this can limit optimization. No preservation attribute is removed automatically. No board, UART, SSH, hardware server, deployment, bitstream programming or active hash project is involved. Counter jobs and recommendation jobs share one local runner lock.

## What validation establishes

The original testbenches execute against the unchanged staged RTL before Vivado. A completion marker is required in addition to exit success.

| Example | Finite RTL checks |
| --- | --- |
| Deep logic | 48 driven samples; 47 checked outputs against a logic-chain oracle after pipeline warmup |
| Priority mux | Six priority-selection cases, including competing requests and no request |
| High fanout | Seven driven cycles; two lane-toggle checks |

The fanout test assumes Verilator zero initialization; it does not validate FPGA power-up or reset behavior. These checks are neither formal equivalence nor implemented-netlist equivalence. Since source is unchanged, one RTL simulation covers both recipe variants; source/checkpoint correspondence comes from controlled build records and hashes. Verilator's vector-level `UNOPTFLAT` warning is disabled only for the pinned deep and priority examples, whose bit dependencies progress forward through the vector. Other diagnostics retain their normal behavior.

Each build captures routed native timing, full register summary, detailed setup and hold paths (up to 400 per analysis), route status, pulse-width checks, DRC, utilization, logical LUT count and routed checkpoint. Register totals and full-example totals remain distinct; detailed endpoint correspondence is limited to captured paths. The full-example mode describes the standalone top, not timing signoff for a larger integrated application or a board deployment.

The Lab reports mixed results and regressions even when headline setup timing improves. It shows reduced positive hold margin as a regression while explicitly distinguishing it from a hold violation. Passing-to-failing endpoint groups can make a result regressed even when aggregate metrics improve. Single builds cannot establish repeatability or prove which optimizer caused a change.

## Retained evidence and CLI

A job retains `trigger.json`, `plan.json`, `recipe.patch`, `baseline-recheck.json`, original staged source and constraints, simulation inputs and logs, tool versions, exact command arrays, scripts, placement and routed checkpoints, native reports and immutable run records. Successful jobs add hash-checked `result.json`, portable comparisons and `explanations.json`. A failed or cancelled job retains its state, error and any completed baseline records without inventing a successful comparison.

```bash
./timinglens.sh try-experiment --session results/verified/priority/analysis.json --plan vivado.remap --preview
./timinglens.sh try-experiment --session results/verified/priority/analysis.json --plan vivado.remap --output results/recommendations/priority-01
./timinglens.sh try-experiment --session results/verified/fanout/analysis.json --plan vivado.fanout --output results/recommendations/fanout-01
```

`--vivado`, `--verilator` and `--timeout` configure tools and per-tool timeout. `--output` must be a new directory. Preview is read-only. Ctrl-C or SIGTERM stops this experiment's child process group. GUI history lives in the existing ignored `.settings/gui.json` under `recommendation_runner`, preserving counter, Lab and unrelated preferences.
