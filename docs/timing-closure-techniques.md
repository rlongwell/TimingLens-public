# Timing-closure techniques in TimingLens

Start with the failing endpoint and its clock requirement. A comparison feeding a clock enable, a multiply followed by an adder, and a control net spanning a device can all miss the same deadline for different reasons. Use the path’s cells, net delays and source evidence to choose an experiment. [TimingLens overview and timer video](../README.md#worked-example-of-a-250-mhz-countdown-timer)

Open **Start here → Review counter experiment** for the timer or **Fix recommendations → Priority mux** for the selector. Both open their results in Experiment Lab. For a supported static Vivado project, open **Add design → Automatic fixes** to try arithmetic or resource-mapping changes in a project copy. The repository includes the measured examples and their build instructions. [Automatic-fix guide](automatic-fixes.md) · [Dense-design examples](../examples/dense-suite/README.md) · [Resource-mapping examples](../examples/resource-balance/README.md)

All timings below are post-route Vivado 2024.2 results for the XC7Z020-1 used on the Zybo Z7-20, unless the baseline failed placement.

## Shorten a wide comparison on a clock enable

The timer accepts a subtraction only when the unsigned 32-bit count can cover the unsigned four-bit request. The original enable compares all 32 bits. If any bit in `remaining[31:4]` is set, the count is at least 16 and already exceeds every possible request. Otherwise the comparison depends only on the low nibble. The two tests can run in parallel.

```systemverilog
// Original
accept && (remaining >= amount)
// Candidate
accept && ((|remaining[31:4]) || (remaining[3:0] >= amount))
```

The rewrite preserves the comparison operator, synchronous reset, load priority and subtraction cycle. The source matcher checks widths, unsignedness and two-state semantics. Four-state unknowns can make the expressions behave differently. Both versions passed an independent 10,289-cycle Verilator scoreboard. With the same 4 ns clock and Default recipe, whole-core setup slack went from −0.633 to +0.407 ns, hold from +0.080 to +0.095 ns, and all 32 setup failures cleared. At the harder 2 ns target, a related 64-bit rewrite improved worst register setup slack while increasing failing endpoints from 126 to 128. [Timer runner and reproduction](counter-runner.md) · [Semantic checks and counterexamples](semantic-review.md)

## Restructure a priority selector

A 16-input priority chain can put many dependent selections in one clock cycle. Three rewrites preserve the rule that the highest asserted request wins. A **balanced tree** merges valid/value pairs through four levels. **Grouped selection** resolves four groups of four locally and then chooses the winning group. A **priority mask** suppresses each lower-priority lane when a higher request is present, then ORs the surviving contributions.

| 2 ns priority example | Worst register setup slack | Logical LUTs |
| --- | ---: | ---: |
| Original chain | −5.515 ns | 16 |
| Balanced tree | −1.825 ns | 42 |
| Grouped selection | −1.651 ns | 24 |
| Priority mask | −1.336 ns | 26 |

Each candidate passed a separate Yosys equivalence proof for the 16-lane binary-input configuration, plus simulation. The three candidates shared one routed baseline, target and Default recipe. The mask gave the best register slack, but every implementation still missed the clock. The balanced rewrite also increased the full example’s failing endpoints from 31 to 33. Experiment Lab shows both populations and the timing/area tradeoff. [Variant sweep and CLI](rtl-variant-sweeps.md) · [Proof and source transformation](priority-rewrite.md)

## Remap a deep logic chain

If the failing path crosses many connected LUTs, muxes or carry cells, Vivado can try different primitive mappings while keeping the RTL. The deep-logic experiment runs `ExploreWithRemap` during logic optimization, then Explore placement and physical optimization followed by `NoTimingRelaxation` routing. The register path improved from −4.484 to −0.737 ns. Whole-design worst setup slack improved only from −8.225 to −8.163 ns. Remapping helped the targeted path, but the design still missed timing. [Recipes, controls and reproduction](recommendation-experiments.md)

## Reduce the routing delay of a high-fanout control

Fanout counts how many inputs a signal drives. A high count becomes a timing clue when the *particular branch on a failing path* also takes substantial time. On the bundled fanout example, a control drove 192 loads. One branch to a clock-enable pin consumed 2.404 ns of a 2.882 ns datapath. TimingLens tried Vivado’s `AggressiveFanoutOpt` on a copy of the baseline’s placed checkpoint, then rerouted with the original constraints and preservation attributes. Register worst setup slack got worse, from −0.664 to −0.759 ns. The experiment keeps that outcome available for review. [Branch measurements](validation.md#routed-results) · [Physical optimization experiment](recommendation-experiments.md)

## Sweep placement and routing strategies

Once the RTL is fixed, a recipe sweep isolates what physical implementation contributes. TimingLens compares Default, Performance_Explore and Performance_ExtraTimingOpt on the same counter candidate. On the 64-bit, 2 ns example, Explore improved register setup slack from −2.043 to −1.931 ns relative to Default. Over the full standalone design, total negative hold slack worsened from −0.195 to −0.210 ns. The Lab ranks register and whole-design results separately and keeps hold, endpoint and area regressions visible. [Directives, rankings and all measurements](strategy-sweeps.md)

## Redistribute arithmetic across existing pipeline stages

TimingLens recognizes unsigned, single-clock, feed-forward arithmetic followed by registers that merely delayed a completed result. It moves operations into those existing cycles and delays each sample’s operands, bias and scale together. Feedback, enables, or ambiguous source matches require engineering review. The proof compares outputs on the same cycle after the pipeline fills, for arbitrary binary inputs.

In the 104-lane calibration example, the original critical path started at block RAM and crossed a multiplier and five carry blocks. The generated schedule used four existing cycles to capture inputs, multiply, add the bias, and rescale. It kept one result per clock and four-cycle latency. A Yosys/Z3 proof checked the leaf module, full-design simulation checked 266,240 lane results per build, and the design was rerouted at the original 125 MHz. LUT use rose from 44,860 to 46,524. [Calibration benchmark and reproduction steps](../examples/dense-zybo/README.md) · [Generated RTL diff](measurements/calibration-pipeline.patch)

| 125 MHz whole design | Existing cycles used | Worst setup slack, before → after | Failing setup endpoints |
| --- | ---: | ---: | ---: |
| 104-lane calibration | 4 | −2.600 → +2.015 ns | 1,872 → 0 |
| I/Q power estimator | 4 | −1.945 → +0.935 ns | 1,152 → 0 |
| Quadratic tone curve | 5 | −9.725 → +1.952 ns | 3,328 → 0 |

The I/Q and tone-curve rewrites also passed equivalence. Their independent streaming scoreboards checked 18,432 and 26,624 lane results per implementation, respectively. All three whole designs passed routed setup, hold and pulse-width checks. [I/Q and tone-curve measurements](measurements/dense-projects.json)

## Map multipliers between logic and DSP blocks

A wide multiply built out of lookup tables can consume logic and route across a crowded device. A DSP48 is a dedicated arithmetic block. In the pixel-gain experiment, TimingLens traced the failing path to a Xilinx Multiplier Generator v12.0 in the block design and changed its implementation, keeping widths, unsigned full-product behavior and latency. It updated the block design and its linked IP configuration together. XSim checked 4,096 products per configuration against a scoreboard.

In the 112-lane pixel-gain timing experiment, moving one-cycle multipliers into 112 DSPs reduced occupied slices from 91.32% to 16.98%. Worst setup slack went from −1.004 to +1.480 ns and all 1,462 failing endpoints cleared. The preserved latency left internal DSP pipeline registers unused, and Vivado reported 336 related advisories. A separate resource-pressure run reduced total LUTs from 39,979 to 5,372 and cleared 1,376 endpoints. [Dense timing experiment](measurements/dense-projects.json) · [Resource-pressure experiment](measurements/resource-mapping.json)

The reverse direction also helps when DSP sites are scarce. A design requiring eight DSPs had only four usable sites and failed placement. Mapping the multipliers into fabric produced a routed design at +2.873 ns setup slack with zero DSPs. There is no routed baseline slack for that case. Two larger fabric candidates generated 13 additional LUT-packing warnings each and were held for review. [Mapping decisions and available capacity](measurements/resource-mapping.json)

## Map memories between block RAM and distributed RAM

Short, shallow stores can exhaust whole block RAM tiles. Deeper stores built from memory-capable LUTs can exhaust that pool instead. TimingLens changes the synthesis mapping for a supported synchronous, single-port, read-first RAM, checks capacity in the destination, and confirms the new primitive family and actual resource use after routing. XSim checks the original and candidate synthesized memories, including disabled writes and same-address reads and writes.

| 125 MHz workload | Resource tradeoff | Worst setup slack, before → after |
| --- | --- | ---: |
| Shallow stores to distributed RAM | Block RAM tiles 140 → 0. Memory LUTs 160 → 2,400. | +1.453 → +2.447 ns |
| Deeper stores to block RAM | Memory LUTs 16,384 → 0. Block RAM tiles 0 → 32. | +1.067 → +1.901 ns |

Both baselines already met timing. The objective was to free a scarce resource while retaining memory behavior and timing margin. TimingLens checked total LUTs, memory LUTs, block RAM and DSP capacity before accepting either mapping. [Resource counts and validation decisions](measurements/resource-mapping.json)

## When a finding needs an engineer

A failing path at a stream boundary may justify testing a register slice or FIFO. Either can change latency or backpressure. A proposed clock exception needs design intent and clock-domain evidence. Changing an exception changes what Vivado checks. On a 25-block telemetry design, TimingLens matched all 715 failing setup endpoints against a native Vivado query, gave a specific diagnosis for 708, and left seven for investigation. That run tested diagnosis only. [Telemetry benchmark](../examples/telemetry-bd/README.md) · [Project, stream and constraint checks](project-analysis.md) · [How to read Lab comparisons](experiment-lab.md)
