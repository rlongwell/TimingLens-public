# Counter experiment runner

The runner executes the bundled binary counter comparison fixes, using fresh baseline and candidate copies. It is available from **Counter runner** in the sidebar, **Run counter…** in Experiment Lab, and the `experiment` CLI command. All build work is local software/tool execution. The runner has no hardware-manager, UART, network deployment, bitstream generation, board programming, or active-project input path.

## Supported experiments

| Example | Original expression | Candidate |
| --- | --- | --- |
| `counter32` | `remaining >= amount` | `((\|remaining[31:4]) \|\| (remaining[3:0] >= amount))` |
| `counter32_250` | Same 32-bit expression, 250 MHz core constraints | Same 32-bit candidate |
| `counter64` | `remaining > amount` | `((\|remaining[63:4]) \|\| (remaining[3:0] > amount))` |

All profiles use unsigned two-state counters, a four-bit amount, synchronous reset, load priority, and the existing acceptance condition. The change affects one exact expression span. The runner verifies the bundled source, XDC and testbench hashes, elaborates the counter with the existing semantic engine, and checks width, signedness, two-state behavior, context and the exact source span before producing the candidate. Changed bundles or unresolved preconditions stop the job. Imported patches, arbitrary RTL and arbitrary Tcl are not execution inputs.

The target is `xc7z020clg400-1`, OOC synthesis, and two threads. The original `counter32` and `counter64` stress profiles use a 2 ns clock. The separate `counter32_250` profile uses a 4 ns clock (250 MHz), input delays of 0.300 ns maximum / 0.200 ns minimum, and output delays of 0.300 ns maximum / −0.300 ns minimum. Its RTL and 10,289-cycle testbench are identical to `counter32`; its separately hash-checked XDC is identical between baseline and candidate. Choosing this profile never rewrites an existing experiment or changes constraints between variants. The single-recipe mode uses default optimization/placement/routing, no physical optimization or seed override. Baseline and candidate use identical constraints, compile settings, extraction scripts and implementation directives in that mode. **Strategy sweep** adds two candidate implementation recipes while preserving candidate RTL and constraints; see [strategy sweeps](strategy-sweeps.md). Each job runs sequentially at reduced CPU priority when `nice` is available. A workspace file lock prevents simultaneous counter jobs from the GUI and CLI sharing the same TimingLens root. Existing unrelated processes are never cancelled or modified.

## Lifecycle and records

1. Reserve a new job directory, record `job.json`, and stage separate baseline/candidate source and constraints. Existing output directories, including dangling symlinks, are refused.
2. Record source-exact `candidate.patch`, `plan.json`, and the hashes of staged source, constraints, testbench and scripts. Staged inputs are read-only and checked again around tool execution.
3. Probe Vivado and Verilator. This recipe requires Vivado 2024.2. Executable paths can be configured; there are no shell command strings or project hooks.
4. Compile and run a deterministic 10,289-cycle Verilator comparison. The testbench checks both variants against each other and an independent behavioral oracle, exercising reset, loads, stalls, all small-operand values, equality/adjacent values, zero, maximum values and seeded sequences. Failure stops the job before implementation. This is finite binary validation, not formal or netlist equivalence.
5. Synthesize, place and route baseline, then candidate. Each build retains a checkpoint, command/log, default-ruledeck DRC, utilization, route and timing reports. Global and register-only detailed captures are separate. Register summaries use up to 10,000 worst-per-endpoint paths and reject an exhausted limit; detailed captures allow 400 paths per check, one per endpoint. No unmeasured endpoint is inferred from a capped sample.
6. Decode each completed capture, rejecting foreign source references before the decoder can read them. Create global and register-only `.run.json` records, validate them through the public import path, and generate the two comparison exports. The GUI opens the register comparison automatically. **Compare global OOC** selects the other population.

The job directory contains:

```text
job.json, plan.json, candidate.patch, tool-version logs
simulation/       source copies, oracle testbench, build/run logs, validation.json
baseline/         staged inputs, fixed Tcl, routed.dcp, build-record.json, reports
  internal/       separate register-only structured and detailed capture
candidate/        corresponding candidate evidence
runs/             baseline/candidate × design/register_paths portable records
comparisons/      design and register_paths HTML/JSON exports
```

`job.json` records phases, commands, log paths, status, timing, input hashes and published comparisons. Terminal states are completed, failed and cancelled. A negative timing verdict is a completed experiment, not a tool failure. A failed/cancelled job retains any completed baseline capture and every available log; it never becomes the new Lab comparison automatically. Restart creates a new directory instead of resuming or overwriting a partial job.

Run checks distinguish finite functional validation, controlled source/checkpoint build provenance, and broader acceptance. The source/checkpoint check records the exact staged inputs, fixed script, successful process, unchanged before/after hashes and newly created checkpoint digest. It does not claim independent netlist equivalence. OOC integration and port/clock-source placement remain unvalidated, so the passing simulation and successful route do not imply signoff.

## Controls and recovery

GUI work runs on a worker thread with a bounded live-log view, phase progress and cancellation. The default timeout is 900 seconds per tool process; the CLI allows 1–7200 seconds. Each child gets a new process group. Cancellation and timeout terminate that group, escalate if necessary, and leave unrelated processes alone—even when a tool is quiet or has closed stdout. Closing the desktop cancels an active counter job and waits for cleanup. CLI Ctrl-C and SIGTERM preserve a cancelled manifest when staging has begun.

The GUI stores example, output parent, timeout, configured Vivado and last job under `.settings/gui.json`. **Open last job** validates a completed manifest and its records, restores the correct example, displays bounded log tails, and opens its comparison. Failed jobs are preserved at the displayed path; a new run starts a fresh job. Theme changes preserve the current form and preview.

CLI usage:

```bash
./timinglens.sh experiment --example counter32 --preview
./timinglens.sh experiment --example counter32 --output results/counter32-01 \
  --vivado /opt/amd/xilinx/Vivado/2024.2/bin/vivado --timeout 900
```

`--verilator` overrides Verilator discovery. Preview requires no output directory and launches no tools. A run requires a new output directory. CLI exit 0 means the experiment completed, 1 means failure, and 130 means cancellation; inspect the comparison's outcome and acceptance fields before considering a change. CLI outputs can be imported into the Lab from `runs/`.

## Validation in this session

Real Vivado 2024.2 and Verilator 5.020 completed both counter jobs, including two simulations and four routed builds. The 32-bit register case reproduced -2.377 → -1.659 ns WNS, -112.901 → -80.414 ns TNS, and 64 → 64 failures. The 64-bit case reproduced -3.030 → -2.043 ns WNS and -245.407 → -216.968 ns TNS but regressed from 126 → 128 failing endpoints. Both remain blocked for acceptance. Global OOC comparisons also retain the hold regressions. Physical LUT use is 50 → 42 and 98 → 82; logical LUT primitive counts remain a separately labeled quantity.

The complete new register path samples identify two 64-bit setup regressions that the older capped captures could not identify: `remaining_reg[1]/D` (+0.321 → -0.905 ns) and `remaining_reg[0]/D` (+0.646 → -0.588 ns). Matching names and clock pairs establish captured correspondence, not formal netlist equivalence.

Tests cover immutable source spans, tampered templates and staged inputs, foreign source references, concurrent jobs, missing tools, failures, cancellation between variants, timeouts after stdout closes, child-process cleanup, portable record validation, GUI handoff/restoration and theme persistence. An additional real Verilator negative test gives both variants the same incorrect comparison and confirms that the independent oracle rejects their shared bug. Opt-in `vivado` tests exercise both complete counter recipes without any board connection.

An initial preflight job rejected the lowercase Vivado version banner. Its failed manifest/logs remain in `work/counter-runner/counter32-live-01`; the parser was corrected before the successful `counter32-live-02` and `counter64-live-02` jobs. Original counter templates, previous Lab evidence, and the active hash project were not modified by execution.

## 250 MHz closure example

The separate `counter32_250` profile completed a fresh GUI-initiated run on 2026-11-17 with Vivado 2024.2 / Verilator 5.020. Both variants passed the existing 10,289-cycle independent behavioral oracle, then used the same Default recipe and the same 4 ns XDC. The full-core OOC comparison measured setup WNS **−0.633 → +0.407 ns**, TNS **−13.201 → 0 ns**, and **32 → 0** failing setup endpoints. Hold WNS was **0.080 → 0.095 ns**, with zero hold failures; pulse-width WNS was 1.500 ns with zero failures. Physical LUT use was **50 → 41**, with 32 FFs in each. Routing and DRC error/critical checks passed.

This is standalone-core timing closure, not integrated-system signoff. The Lab retains `Integrated design validation: Not tested`, making overall acceptance `incomplete`. Its separate register-only comparison also retains a tiny positive-margin hold decrease (0.295 → 0.294 ns, zero failures) and the corresponding strict regression verdict. Both populations remain available; neither is altered for the film. Full evidence is in `work/demo-video-v4/runs/counter32_250-20261117T085217Z-22594287`, with a portable export alongside the alternate demo. The original 2 ns stress examples and their evidence remain unchanged.

```bash
./timinglens.sh experiment --example counter32_250 --preview
./timinglens.sh experiment --example counter32_250 --output results/counter32-250-01
```
