# Counter strategy sweeps

In **Counter runner**, choose the 32-bit or 64-bit example and **Implementation → Strategy sweep · 3 recipes**. Preview shows the exact source rewrite, commands and build count. **Run isolated experiment** performs one finite simulation and four sequential routed builds in a new job directory. Completed results open in **Experiment Lab → Strategy sweeps**. **Open last job** restores the latest runner job; the Lab also has **Open sweep…** and **Open last sweep**.

```bash
./timinglens.sh experiment --example counter64 --sweep --preview
./timinglens.sh experiment --example counter64 --sweep --output results/counter64-sweep-01
```

`--preview` reads the source-pinned example and prints the change and implementation commands; it creates no job and launches no tools. Without `--sweep`, the previous two-build Default workflow remains available. The CLI returns 0 for a completed job, 1 for a partial or failed job, and 130 for cancellation. Completed timing can still fail acceptance.

## Controlled recipes

All builds use Vivado **2024.2**, the **xc7z020clg400-1** target, a **2 ns** clock, OOC synthesis, unchanged constraints and compile settings, **two tool threads**, and no seed override. The original RTL is built once with Default. The three candidate builds use identical factored RTL and the directives below. Synthesis and extraction stay identical.

| Recipe | opt_design | place_design | phys_opt_design | route_design |
| --- | --- | --- | --- | --- |
| Default | default | Default | omitted | Default |
| Performance_Explore | Explore | Explore | Explore | Explore |
| Performance_ExtraTimingOpt | default | ExtraTimingOpt | Explore | NoTimingRelaxation |

These are explicit non-project command sequences for the 7-series flow, using AMD's 2024.2 [opt/place mappings](https://docs.amd.com/r/2024.2-English/ug904-vivado-implementation/Directives-Used-by-opt_design-and-place_design-in-Implementation-Strategies) and [phys-opt/route mappings](https://docs.amd.com/r/2024.2-English/ug904-vivado-implementation/Directives-Used-by-phys_opt_design-and-route_design-in-Implementation-Strategies). They are not arbitrary strategy names passed to a project. The default build script is byte-identical to the previous runner. Recipes are allowlisted; imported scripts and sweep records cannot supply executable commands.

The independent 10,289-cycle Verilator oracle validates the original and factored RTL once. Its evidence is reused across candidate recipes because their source bytes are identical, with staged hashes verified around each execution. This validates finite RTL behavior, not formal or post-route equivalence. Every completed implementation retains its own checkpoint digest, command log, recipe script, reports and run records.

## Reading the Lab

The population selector chooses **Register paths** or **Global OOC**. These have separate summaries and rankings. Each recipe has two distinct comparisons:

- **Recipe effect:** the candidate with that recipe versus the same candidate RTL with Default. This isolates the intended implementation settings change within the captured build context.
- **Overall effect:** the candidate with that recipe versus the original RTL with Default. Both RTL and directives may differ, so this comparison cannot attribute the change solely to the recipe.

Pulse width, routing, DRC and utilization are whole-build checks in both views. **Seconds** is the elapsed Vivado subprocess time, including synthesis, implementation and capture; simulation and import time are separate in the job log.

Select a row to see its measured regressions. The explanation names worsening summary checks, passing-to-failing captured endpoints, and up to six worst captured endpoint changes. When available, it reports logic, routing, clock skew and uncertainty deltas. If the worst launch point changes, the explanation explicitly says these are different launch paths. Endpoint names and clock pairs establish correspondence; path IDs are evidence references, not matching keys. Component deltas do not establish an optimization's physical cause. Unmatched or uncaptured paths do not prove an endpoint was added, removed or fixed.

Implementation can also change the reported endpoint population, for example when physical optimization replicates logic. The explanation lists that population change alongside failure totals. Count growth is not proof of added functional behavior or newly failing matched endpoints. Captured components may not account for the entire slack change.

**Compare recipe to Default** and **Compare to original RTL** open the existing Lab measurements, checks, endpoints and path/source inspection. Opening and exporting a sweep revalidates the manifest and referenced run digests. Drilldown also revalidates; an altered file leaves the previous view intact with an error. No source path, checkpoint or script embedded in a record is executed or resolved for inspection.

## Ranking rule `sweep.rank.v1`

Ranking is a deterministic review order, not a predicted speedup, acceptance, or a weighted quality score. Only completed comparable builds qualify. Required evidence includes full setup/hold measurements, pulse width, routing and DRC measurements, matching source bytes versus the Default candidate, explicit compatible build context, recipe-matching directives, and passed routed/routing/DRC/source/functional/provenance checks. A deficient Default reference leaves every recipe unranked. Failed, cancelled, pending, unstarted, incompatible or incomplete entries stay visible as **Unranked**, with missing values shown as **Not tested**.

Eligible recipes are ordered lexicographically:

1. No worsening summary/check metrics or newly failing captured endpoints versus candidate Default.
2. Fewer hold failures, then fewer pulse failures, then fewer setup failures.
3. Better setup TNS, then setup WNS, then hold TNS, then hold WNS.

Identical keys share a rank. Physical LUT use and implementation runtime are reported tradeoffs and do not break ties. The regression guard includes loss of positive timing margin; a hold-margin reduction can be a regression even when hold still passes. Other worsening captured endpoint margins are explained but do not by themselves override the summary guard unless they cross from passing to failing. Unknown measurements never become zero. Captured-corner mismatches remain conservative context exclusions.

Setup/hold failures can appear in ranked completed results; their acceptance remains **blocked**. OOC/register-only evidence does not establish integrated timing signoff. A single implementation per recipe does not measure repeatability or justify a universal winner. The original and all candidates can fail the 2 ns goal.

## Failures, cancellation and evidence

Original-baseline or candidate-Default failure stops the sweep, since later recipe comparisons depend on those references. An alternative recipe failure or timeout is recorded and later recipes continue. Source/script hash changes stop the whole job. Cancellation terminates only the runner's child process group and stops future recipes. Completed records survive, incomplete recipes receive no fabricated measurements, and the GUI can open retained partial/failed/cancelled sweep evidence. A failed preflight is also visible without ranking any recipe.

The workspace lock, fresh directories, source-pinned counter inputs, two-thread limits and sequential execution remain in force. The runner has no board, UART, hardware-manager, deployment or active-project input path.

Each sweep adds `sweep.json` (versioned, hashed manifest with run-file digests), `ranking.json`, and `sweep.html` to the job. The eight run records hold the two populations for the original and three candidates. Native build folders retain checkpoints and full logs. Partial failures retain their error and tool logs. The Lab's **Export sweep…** writes a fresh directory with `sweep.json`, the referenced self-contained run records, recomputed `ranking.json`, and `report.html`; it does not copy executable caches or full checkpoints. The original job retains those. Digest checks detect changes, not authenticity. Existing evidence and export directories are never overwritten.

## Retained live validation

The two sweeps on November 16, 2026 used Vivado 2024.2 and Verilator 5.020: eight routed builds and two successful 10,289-cycle simulations. Staged input hashes, executed directives, checkpoint digests and portable replay were checked. These are single trials on the bundled examples, not a cross-design benchmark.

Register-path results:

| Counter | Rank | Candidate recipe | Setup WNS ns | Setup TNS ns | Setup failing / total | Hold WNS ns |
| --- | --- | --- | --- | --- | --- | --- |
| counter32 | 1 | Default | -1.659 | -80.414 | 64 / 64 | 0.547 |
| counter32 | 2 | Performance_Explore | -1.237 | -61.892 | 64 / 64 | 0.295 |
| counter32 | 3 | Performance_ExtraTimingOpt | -1.328 | -65.342 | 64 / 64 | 0.356 |
| counter64 | 1 | Performance_Explore | -1.931 | -188.896 | 128 / 128 | 0.294 |
| counter64 | 2 | Default | -2.043 | -216.968 | 128 / 128 | 0.294 |
| counter64 | 3 | Performance_ExtraTimingOpt | -2.094 | -250.032 | 159 / 160 | 0.314 |

All candidates remain blocked for acceptance. The 32-bit Explore and ExtraTimingOpt recipes improve setup relative to candidate Default but reduce positive hold margin. The 64-bit Explore recipe improves register setup without changing register hold margin, while its global OOC hold TNS worsens from −0.195 to −0.210 ns. ExtraTimingOpt worsens 64-bit setup and increases the captured physical endpoint population. Global ranking is Default, ExtraTimingOpt, Explore for 32 bits; Default, Explore, ExtraTimingOpt for 64 bits.

Compared with the original 64-bit RTL, all three candidates have more failing register endpoints. The original has 126 / 128; Default and Explore have 128 / 128; ExtraTimingOpt has 159 / 160. These overall comparisons include the RTL rewrite and must not be attributed solely to strategy selection. Full OOC I/O timing context and integrated signoff remain outside this validation.
