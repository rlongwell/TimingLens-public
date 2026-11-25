# Validation on Ubuntu 24.04

Validated with Python 3.12.3, PySide6 6.10.1, Verilator 5.020, and Vivado 2024.2 build 5239630. Vivado was discovered at `/opt/amd/xilinx/Vivado/2024.2/bin/vivado`. All routed examples targeted `xc7z020clg400-1`.

## Reproduce

```bash
./timinglens.sh doctor
./scripts/verify.sh --with-vivado -q
./timinglens.sh demo --run-vivado --max-paths 48 --output results/reproduction
```

The full verification run passed all 34 tests in 8 minutes 34 seconds. It includes six live Vivado cases, four RTL simulations, and the desktop and analysis regressions. The local run log is `results/verified/verification.log`. The examples use timing constraints and have no physical pin assignments or bitstream build step.

## Routed results

| Design | Setup WNS (ns) | Setup TNS (ns) | Setup failing endpoints | Hold worst slack (ns) | Captured failing paths |
| --- | ---: | ---: | ---: | ---: | ---: |
| Deep | −8.225 | −20.325 | 17 | +0.050 | 19 |
| Priority | −8.149 | −32.939 | 31 | +0.051 | 33 |
| Fanout | −7.385 | −80.582 | 93 | +0.087 | 48 |
| Clean | +9.438 | 0.000 | 0 | +0.054 | 0 |

The captured JSON and HTML reports from these runs are in the local `results/verified/` directory. Each row uses 48 paths per check type and at most 3 per endpoint. Failing endpoints come from Vivado across the full design. The top-ranked failing path can be an I/O path on an aggressive clock. The internal datapaths below establish which hardware triggered the intended diagnoses.

- **Deep.** P00002 ran from `u_kernel/launch_reg[1]/C` to `u_kernel/result_reg/D`. Vivado measured −4.484 ns slack, 16 logic levels, 2.440 ns logic, and 4.048 ns route delay. TimingLens applied TL-A and correlated the primitive chain to `deep_kernel`.
- **Priority.** P00002 had −5.515 ns slack. TimingLens verified 15 cascaded mux stages through LUT3 INIT, ordered pin and net connectivity, and source attribution to `priority_select` line 10. TL-B preserves the behavior where a higher numbered asserted request wins.
- **Fanout.** `control_q_reg/Q` drove 192 loads on `control_q`. For P00029, Vivado measured 2.404 ns to `lane[107].active_reg/CE`, 83.4% of the 2.882 ns datapath. TimingLens applied TL-C. Unit tests also exercise high fanout with a short branch delay and verify that TL-C stays silent.
- **Clean.** Vivado reported positive setup and hold slack and zero failing endpoints. TimingLens reported zero findings.
- **Ambiguity.** The synthetic fixture in `tests/fixtures/ambiguous.json` retains a measured-style failing path without source or graph evidence. It yields Unknown correlation and TL-H with neither a source file nor a line number.

## Workflow checks

- A generated XPR was routed in an isolated copy. The original XPR hash stayed identical, and the original project received no run directory. The copied project was then opened read-only and the routed DCP imported independently. The two routed imports produced the same Vivado timing summary.
- A named `synth_1` import reported stage `synthesized`. The clean fixture’s synthesized hold result was −1.022 ns worst slack, and the routed result was +0.054 ns. TimingLens shows synthesis route delays as estimates.
- Verilator ran four self-checking testbenches, including overlapping priority requests and the registered high-fanout control. Simulation suppresses Verilator’s vector-level `UNOPTFLAT` diagnostic for the explicitly forward-only generated bit dependencies.
- The desktop was rendered in both themes under Xvfb. Automated interaction verified background import, selecting a schematic cell, jumping to and searching the attributed RTL line, timing-path filtering, and preference restoration. The shell entry point was also exercised from outside the repository.

## Real DFX checkpoint regression, 2026-11-16

The original release's 34-test run above did not cover Vivado's DFX table columns. Testing the real Zybo hash design exposed a defect: the parser treated Partition/PBlock fields as part of resource names. All 3,572 initially captured arcs lacked detailed delays, and the critical reset net was absent because its sink was outside the 128-load snapshot. Design-wide slack totals remained correct.

After repair, a fresh Vivado 2024.2 read of the unchanged BLAKE2s checkpoint captured all 3,672 consecutive pin links and measured 3,658 arc delays. All 18 failing paths have complete connectivity and delay evidence. The 14 unavailable delays belong to eight passing paths where Vivado renders protected resource labels as `<hidden>`; these remain unknown and produce an explicit coverage warning. The original checkpoint SHA-256 remained `6609dcfa82b058fbb8b270240ce4b7eafa515e1554aaafcfdd13ac98b0b451a2`. Setup WNS/TNS remain −0.011/−0.138 ns, hold WNS +0.016 ns.

The worst path reports the actual 1.058 ns `rp_tkeep[7]` branch, 1.052 ns `rp_resetn` branch and eight carry cells totaling 1.348 ns. Module navigation points to `axis_bytes`, while individual Vivado source tags are explicitly presented as origin hints. The carry's source tag points to the byte-counting loop, illustrating why it must not be treated as the exact critical comparison.

Re-importing the passing SHA-256 checkpoint yielded zero findings and preserved +0.141 ns setup / +0.016 ns hold. Re-importing all four previously routed example sessions preserved their expected rule families; every captured arc in those examples had a measured delay. These imports reused recorded Vivado results; they are not fresh implementation runs.

The updated local suite passed 34 tests in 14.34 seconds with six optional live-build tests deselected. It includes six real-DFX-evidence regressions, four RTL simulations, and GUI/CLI tests. The failing checkpoint was independently re-read through live Vivado. Dark and light GUI views were rendered and inspected with the real 200-path session. Full evidence and source hashes are in the sibling hash repository's `build/timinglens-evaluation/`, including `blake2s-fixed-live/`, `tests-fixed.log`, and `fixed-provenance.json`. No hardware programming was required for these checks.

## Project-aware recommendations and layout, 2026-11-16

The expanded offline suite passes 48 tests with six optional live-build tests deselected. It covers actual DFX guard/recipe selection, report-only reconstruction and duplicate removal, Tcl comments and unresolved expressions, BD path/link matching, FIFO intent bounds, source-revision mismatch, conflicting reports, and negative tests that prevent unsupported constraint templates. GUI integration exercises adding files, asynchronous analysis, candidate/evidence/validation views, command copying and theme preservation. It also retains the existing four RTL simulations.

Two additional fresh Vivado reads used the original failing BLAKE2s DCP and the reimplemented passing DCP. The failure retained −0.011 ns setup / +0.016 ns hold, all 18 failing paths had complete detailed evidence, and native DFX metadata identified `u_hash`. The engine proposed specific implementation recipes and the `axis_bytes.remaining` comparison guard at lines 46–47. The passing DCP retained +0.110 ns setup / +0.016 ns hold and generated zero timing findings or fix candidates. These were read-only analyses, not new implementation runs or physical-board tests. The passing hash implementation was produced separately with ExtraTimingOpt placement, Explore physical optimization and Explore routing; that is a custom recipe, not the exact built-in Performance_ExtraTimingOpt recipe's NoTimingRelaxation routing.

The desktop now presents an issue list beside a single candidate, with numbered next steps and separate Suggested change, Evidence, and Tcl & validation tabs. Copy Tcl preserves commented constraint templates and executes nothing. Both themes were rendered and inspected. Local evidence lives under the hash repository's `build/timinglens-evaluation/{project-failing,project-passing,project-offline-final,gui-project}`. Installed Vivado 2024.2 help also confirmed the report_exceptions coverage/ignored and detailed CDC options.

These tests establish parsing, evidence gates and presentation behavior. They do not establish that every proposed RTL/BD/constraint change is functionally valid or that any suggested strategy will improve an arbitrary design.

## Semantic review, source previews and independent evaluation, 2026-11-16

The baseline was rechecked at 48 passed / six optional Vivado tests deselected. The final offline suite passes **83 tests / six deselected in 30.95 seconds**. New coverage includes semantic width/signedness boundaries, reversed comparisons, reset/data-selection versus hold enables, parameter/generate hierarchy, duplicate modules, missing includes/macros, source-hash conflicts, asynchronous events, multiple/partial writers, byte-exact diffs, bounded compilation/input reads, malformed BD atomicity, clock/reset/boundary gates, deduplication and investigation ranking. GUI tests exercise source/path navigation, keyboard activation, filters, independent diff copying, asynchronous responsiveness, error recovery and theme preservation.

Separate fresh validation ran four Vivado implementations for two before/after expression edits, two newly implemented stream and memory/DSP holdout designs, and a read-only register-path recheck of the four experiment checkpoints. No physical board or active hash build was touched. Both counter edits pass cycle simulation and improve internal setup WNS in those runs; neither closes setup. The 64-bit result increases failing internal endpoint pins from 126 to 128. Full OOC boundary timing remains unvalidated. A Vivado four-state simulation reproduces an X-propagation counterexample and supports refusing that patch.

Nine evaluation captures retain all expected labeled diagnoses, unknown evidence and negative-edit labels. The initial streaming slice overreach was recorded and corrected; that case is no longer held out for the BD rule. Both themes were rendered and inspected at 1350×880 and 980×740, including actual DFX hypotheses and a measured-kernel review diff. The dashboard now scrolls at small sizes instead of compressing timing cards. Detailed metrics, corpus partitions, retained regressions, reproduction commands and limits are in [semantic-review.md](semantic-review.md).
