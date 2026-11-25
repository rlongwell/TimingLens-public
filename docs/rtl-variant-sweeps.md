# Verified priority-mux RTL sweeps

**Fix recommendations → Priority mux → Open example evidence** selects **Verified RTL variants · 3 candidates**. Click **Try this experiment** to review the frozen trigger, proof scope and each source diff. **Run isolated experiment** starts the sweep. The single balanced rewrite and implementation-only recommendations remain available separately.

The source-pinned catalog contains a balanced binary valid/value tree, four local four-lane selectors followed by group selection, and a per-lane priority mask followed by an OR. All choose the highest asserted request index and return zero when no request is asserted. They preserve ports, input/output registers, cycle behavior, clock and XDC. KEEP accompanies the replacement structures and KEEP_HIERARCHY remains. Structural RTL depth does not promise mapped LUT depth or improved physical timing.

Each candidate independently passes the existing **Yosys 0.69 equivalence gate** before its implementation: exact staged source pair, qualified script, success log, 67 proven matched points and explicit output/state coverage. The scope is `priority_top`, N=16, binary inputs and corresponding register states. Other parameters, four-state behavior, independent hardware power-up states, physical timing and implemented-netlist equivalence are outside this proof. Each branch additionally runs the six-case finite testbench on original and candidate RTL. A complete sweep therefore retains three proofs and six simulation runs; the original simulation is repeated for each branch.

## Controlled implementation

The runner builds one fresh original and three candidates sequentially: **four Vivado implementations**. Each uses Vivado 2024.2, xc7z020clg400-1, the same 2 ns clock and byte-identical Default synthesis/place/route and extraction scripts. Tool processes use two threads and reduced priority. The shared workspace lock excludes other TimingLens runners.

The first successful proof/simulation branch builds the original and rechecks that the recommendation still applies. Later branches copy its verified native outputs and checkpoints into their own directories; the original build's hashes and process provenance are retained explicitly as `baseline_reuse`. There is no second implementation disguised as the original, and no hardlink to a live project. Every Lab row compares to the exact same original portable record. A failed candidate proof, simulation or implementation stays visible while independent candidates continue. A shared-original failure or changed shared evidence stops remaining work. Cancellation stops only the runner's process group and retains completed results.

Inputs are staged below a new job directory. Bundled sources, constraints and existing jobs are never overwritten. The runner neither accesses a board nor interacts with active hash work. It accepts only this qualified catalog, not arbitrary imported RTL or Tcl.

## Lab tradeoffs

Results open in **Experiment Lab → RTL variants**. The table and clickable plot include the original and all candidates. **Register paths** and **Full example** are separate populations. Select a candidate to inspect the source diff, endpoints, timing/hold/pulse/DRC gates, proof and build context in the existing comparison workspace.

The timing/LUT frontier contains every comparable point for which no other point has at least as good setup WNS and no more logical LUT primitives, with at least one strict improvement. Ties remain on the frontier. The original participates, so a more expensive candidate that is slower than the original cannot appear competitive. Hold, FF count, other resources and acceptance are deliberately separate from this two-axis calculation and remain visible in the table and explanations.

**Review limits** flags summary regressions, newly failing matched endpoints and an optional logical LUT limit. An unset limit means no area budget. Changing the limit never hides rows or changes the measured frontier. **Within limits** only means these review guards passed; it does not mean timing closure. Acceptance remains blocked by failing timing, hold, pulse, DRC or other existing gates. A candidate may lie on the timing/LUT frontier and still have a regression or blocked acceptance.

Missing context, missing measurements or failed required validation produce **Not comparable**, never a zero measurement or a frontier point. Failed, cancelled and unstarted rows remain visible with their reason. Explanations report measured changes and endpoint evidence without claiming that one optimization caused them. One implementation per variant does not establish repeatability.

## Portable evidence

`rtl-sweep.json` references eight self-contained run records (original plus three candidates, each with two populations). Every completed candidate embeds its exact proof source pair, result, script, graph and logs. Import checks the manifest and record hashes, catalog/source identity, Default script, qualified context and attached proof. Paths must name expected records within the export. Hashes detect changed bytes; they do not establish producer authenticity.

**Export sweep…** writes a new directory containing the manifest, completed records, `tradeoffs.json` and `report.html`. Partial and cancelled sweeps can also be exported. A variant that passed proof but failed implementation retains a separately hashed proof bundle; an unbuilt row cannot claim a passed gate without that evidence. The report preserves both populations, selected LUT limit, regressions, frontier and acceptance. Loading, comparing and exporting never run a tool or resolve descriptive source paths. **Open last job** restores the retained sweep; Lab history and LUT preferences are stored under `.settings/gui.json` alongside existing counter history and theme settings.

```bash
./timinglens.sh try-experiment --session results/verified/priority/analysis.json --plan rtl.priority_sweep --preview
./timinglens.sh try-experiment --session results/verified/priority/analysis.json --plan rtl.priority_sweep --output results/recommendations/priority-sweep-01
```

The CLI accepts `--yosys`, `--vivado`, `--verilator` and `--timeout`. It returns 0 for a completed sweep, 1 for partial/failed and 130 for cancelled. Completion means evidence was collected, not that acceptance passed. Reopening an existing job does not resume or overwrite it; start a new directory for another trial.
