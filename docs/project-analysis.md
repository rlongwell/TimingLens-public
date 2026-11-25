# Project-aware recommendations

Add a TimingLens JSON session **or** Vivado timing reports, then the corresponding RTL, block-design Tcl/`.bd`, build Tcl, and XDC. In the desktop, open **Project files**, add or drop the files, and choose **Analyze selected files**. To supplement an already-open DCP/session, select **Use the current timing session**. Results appear in **Fix recommendations**, including project/constraint reviews even when there are no captured failing paths.

```bash
./timinglens.sh inspect --files results/capture/analysis.json \
  rtl/top.sv scripts/design.tcl scripts/build.tcl constraints/timing.xdc \
  --output results/project-review

./timinglens.sh inspect --files reports/timing_summary.rpt reports/paths.rpt \
  reports/check_timing.rpt reports/clock_interaction.rpt \
  rtl/top.sv rtl/worker.sv design.bd --top top \
  --output results/report-review
```

Live DCP/XPR collection also accepts repeatable `--file` (alias `--source`) arguments for these context files. Offline inspection does not require a Vivado license or an AI service. It never runs supplied Tcl, follows its `source` commands, or modifies the project. Literal Tcl declarations are parsed conservatively; unresolved expressions and control flow are reported. Generated `.bd` JSON is often a better source of concrete connections than a scripted BD with many variables.

Each input is captured with its content hash. Selecting a different revision of a source already in the session suppresses its direct source tags and RTL fix candidates. A hash identifies captured bytes; it does not prove those bytes built a separately supplied DCP. Keep reports and sources from the same implementation. Report-only import reconstructs only printed path connectivity and delays, deduplicates identical paths, and reports missing native hierarchy/fanout/source metadata. Hidden rows remain unknown. Design-wide totals require a timing-summary report. Conflicting design metadata or timing totals are rejected where available.

The capture limits are 64 MB per report/session/BD, 4 MB per other source, and 256 MB total. Direct session reads also enforce 64 MB. Syntax indexing uses a 256 KB/file and 2 MB total budget; larger files remain text context. VHDL remains context. The bounded slang semantic worker elaborates supplied Verilog/SystemVerilog hierarchy, parameters and generate constructs, but does not follow ambient includes or recreate Vivado compile-unit macros. Inline macro expansions cannot become exact edit spans. Missing context remains explicit. See [the semantic scope and limits](semantic-review.md).

## What is specific today

| Evidence | Candidate |
| --- | --- |
| Complete failing routing-dominated path | Post-route `Explore`, or fresh `Performance_ExtraTimingOpt` / `Performance_NetDelay_high` recipes with their actual place/phys-opt/route directives |
| Connected deep/mux/carry path | `Performance_ExploreWithRemap`, plus source review appropriate to the observed topology |
| Slow high-fanout branch in a placed/routed design | `AggressiveFanoutOpt` experiment |
| Measured DSP delay above threshold, native multiply source tag, matching RTL digest and a feed-forward register chain | A generated arithmetic pipeline with aligned operands and the original cycle count. **Verify RTL fix…** runs a source-specific Yosys/Z3 proof. |
| Mapped block RAM on a failing path | `Performance_WLBlockPlacement`, alongside RAM latency/register review |
| Placed/routed hold failure | `ExploreWithHoldFix`; synthesis hold estimates first require implementation |
| Carry chain reaching register CE, unique register/module, elaborated clocked comparison/hold guard | Exact expression and type evidence; a bounded unsigned comparison preview with zero added latency. Review diff only for the supported two-state, nonparameterized, fully elaborated case; otherwise a design hypothesis or mapping request |
| Literal BD link, complete failing path, shared declared aclk/aresetn, captured clock source, and slow measured cross-instance branches | Conditional AXI4-Stream slice review. Missing domains or internal receiver logic produce an evidence request; different clocks require CDC review |
| Declared unthrottled burst larger than available capacity on a BD link | FIFO capacity review, including in-flight beats, stall bounds and sustained-rate limits |
| Supplied XDC exceptions | Exact file/line audit, coverage and ignored-exception checks |
| Declared asynchronous or multicycle intent matched to captured clocks/endpoints | Conditional constraint review and, where evidence permits, **commented** XDC templates |

A verbose Vivado report can classify a forwarded clock output as a LOW missing-output-delay item. TimingLens checks the named port against a captured generated clock and its master. If this accounts for the entire finding, it keeps an output-interface review and continues diagnosing constrained, internal, same-clock register paths. Unresolved constraints, data outputs with missing delays, and suspect clock relationships still take priority.

The implementation catalog is gated to Vivado **2024.2** and the supported 7 series / UltraScale device families. An unverified release/device produces a compatibility review rather than version-specific commands. Fresh-placement recipes require a synthesized unplaced input; post-place experiments require a placed/routed checkpoint. DFX recommendations preserve locked static logic, partition pins and isolation, and require full `pr_verify`. The tool displays directives found in supplied build Tcl, but cannot infer that a recipe ran successfully from the script alone.

There is no claim of general RTL optimization or formal correctness. A source-name/topology match remains a hypothesis. The current detailed RTL transformation rule targets comparison-to-enable chains; other patterns retain narrower diagnostic guidance. BD candidates require cross-probing the generated design; no numeric IP settings or rewiring are fabricated. A slice adds latency and registers; a FIFO adds storage and may add latency. Compare setup, hold, DRC, routing, resources and functional behavior after each experiment. Candidate rankings do not predict speedup.

## Design intent and timing exceptions

Copy and edit [the example intent file](../examples/project-context/intent.json), then include it with `--files`. Its values are explicit user assertions, not facts inferred from RTL or timing slack:

- `stream_links`: `source`, `sink`, `max_burst_beats`, `buffer_capacity_beats`, and `reason`. The burst is the maximum unthrottled input burst; the capacity is currently available buffering across the declared link.
- `asynchronous_clocks`: exact `source` and `destination` clock names plus a functional `reason`.
- `multicycle_paths`: exact timing `source`/`destination` pins, integer `cycles >= 2`, and the enable/stability `reason`.

A negative-slack path is never enough to propose a false path. A rare or debug signal is still a timed signal unless the functional operating modes establish otherwise. An exception alters the analysis; it does not make the implementation faster.

Asynchronous templates require both clock names in the capture and no known common root. They remain commented until every crossing, both directions, has been checked. Clock groups override `set_max_delay`: a crossing that needs a bounded delay or bus skew must retain the relevant constraints instead of being hidden by a broad group. The tool does not claim to prove CDC safety. [AMD CDC guidance](https://docs.amd.com/r/2024.2-English/ug903-vivado-using-constraints/About-CDC-Constraints), [asynchronous delay bounds and precedence](https://docs.amd.com/r/2025.1-English/ug903-vivado-using-constraints/Constraining-Asynchronous-Signals).

A multicycle template additionally requires captured matching endpoints on the same clock with explicitly reported rising-edge launch/capture. It emits a paired setup N / hold N−1 template only for that restricted relationship. Prove that the source is stable and the destination does not capture intermediate values under stalls, resets and mode changes. Different clock periods/phases or missing edge evidence require waveform review, not this formula. [AMD setup/hold example](https://docs.amd.com/r/2024.2-English/ug903-vivado-using-constraints/Relaxing-Setup-While-Maintaining-Hold).

Review `check_timing`, `report_clock_interaction`, detailed CDC, and exception coverage/ignored reports in Vivado. Resolve every selector and check the object counts. No automatic RTL, BD or constraint edits are performed.

## Strategy references

The recipes use AMD's [opt/place strategy table](https://docs.amd.com/r/2024.2-English/ug904-vivado-implementation/Directives-Used-by-opt_design-and-place_design-in-Implementation-Strategies), [phys-opt/route strategy table](https://docs.amd.com/r/2024.2-English/ug904-vivado-implementation/Directives-Used-by-phys_opt_design-and-route_design-in-Implementation-Strategies), and [physical optimization command reference](https://docs.amd.com/r/2024.2-English/ug835-vivado-tcl-commands/phys_opt_design). AXI4-Stream buffering guidance follows the [infrastructure IP guide](https://docs.amd.com/r/1.1-English/pg085-axi4stream-infrastructure/General-Options); use the installed IP version's customization options.

## Reading the recommendation view

1. Select an issue in the left column. Slack and affected captured-path count stay visible; expand a timing issue to choose an individual path.
2. Select one candidate on the right. **Suggested change** shows numbered next steps, the rationale, scope and source locations.
3. Use **Evidence** for the measurements and limitations. **Tcl & validation** contains prerequisites, detailed engineering guidance, commands and acceptance checks. **Copy Tcl** only copies text; it never runs a command. **Open timing path** leads to the graph and raw Vivado path.
4. **Change preview** shows exact original/proposed expressions, conditions, source hashes and any permitted review diff. Each alternative is separate. **Copy diff** copies one alternative only and edits nothing. Source links open the captured text, including BD/XDC locations.

The issue filter searches titles, rule IDs, timing endpoints and path IDs. Arrow keys navigate the issue tree; Enter/double-click on a path opens it. The dashboard selects an actionable investigation first, then orders by measured slack and endpoint breadth, detail coverage and source specificity. Unexplained failures remain in the list. This ordering predicts neither gain nor correctness. Groups combine when their captured path sets match. A shared arithmetic edit can also group paths across instances when each path independently maps to the same source revision and byte range. The Evidence tab records the distinct paths and hardware instances.

Dark/light theme switching preserves the selection and review contents. The layout keeps the recommendation separate from evidence and unverified assumptions. Reports still export the complete details for review outside the app.
