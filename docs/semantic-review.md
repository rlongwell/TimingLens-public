# Semantic repair review and evaluation, 2026-11-16

This upgrade connects the preexisting semantic index to measured-path recommendations, adds exact review previews and structured provenance, and combines multiple symptoms of the same captured path set. It does not establish arbitrary RTL equivalence or automatically repair a design.

## Audit and scope

The starting suite passed **48 tests, with six optional live Vivado tests deselected**. All source was already untracked in the local repository; no existing implementation is claimed as newly authored. Before edits, a recoverable tar snapshot and file hashes were saved outside the repository under the active Codex workspace's `work/timinglens-upgrade/`. No remote, commit or published history was created.

The three observed gaps were:

1. The existing comparison-to-enable suggestion used syntax guards even though a semantic module already existed. It could not distinguish a reset/data mux from a hold enable, or justify widths and signedness.
2. Suggestions lacked an exact original/proposed expression, byte/hash provenance and a review diff. A source tag could be confused with an exact physical cause.
3. The DFX capture displayed three rule groups for the same 18 paths, and expensive lazy recommendation work could occur during GUI presentation. The first screen did not lead directly to a concrete review.

Changes stay within the local TimingLens project and fresh experiment folders. The connected Zybo, UART, SD card, services, network and active hash sweep were untouched. Completed DFX reports were copied for analysis; no hash-design source/checkpoint was changed or implemented.

## Supported semantic rule

`rtl.compare_enable` v2 requires a complete failing setup path, at least three electrically consecutive carry primitives, a sequential CE endpoint, a surviving register identity, unique source/module association and a supported clocked writer. The semantic IR records exact UTF-8 spans, elaborated register and operand types, dependencies, clock/edge, updates, constant/reset candidates, nested decisions and whether the opposite branch writes the same register.

A comparison qualifies as an enable candidate only on a nonconstant update with an opposite branch that holds the register. Comparisons choosing two writes, including reset/data selections, do not satisfy this rule. Asynchronous event lists, multiple writers, partial assignments, case/loop writers, unresolved hierarchy or compile errors are conservatively unsupported. Reset signal names alone are never a proof of reset semantics.

For a plain unsigned `W`-bit register compared with an implicitly or explicitly zero-extended unsigned `N`-bit named operand, the preview can factor the upper bits and the low comparison. `W >= 16`, `1 <= N <= min(8, W/2)`, and zero-based packed vectors are required. For example:

```systemverilog
// Original
remaining >= amount
// Independent review alternative, for the supported 32-bit / 4-bit case
((|remaining[31:4]) || (remaining[3:0] >= amount))
```

The six operators `> >= < <= == !=`, including reversed operands, are supported. The rule does not narrow the register, alter subtraction/overflow, remove reset, move validation, or add latency. It does not accept a signed operand, arithmetic expression on the narrow side, ambiguous casts, macro-derived edit span or unsupported vector shape as this rewrite.

A unified diff is emitted only with two-state operands, full supplied-project elaboration, nonoverridable parameters and native scope ownership. Even this is **review_diff**, not a proven or approved patch. Other supported expressions may get **design_hypothesis** previews, with no diff. Alternatives remain separate and original files are never written. Hashes identify the captured bytes; they do not prove those bytes built a separately supplied checkpoint.

### A rejected transformation is a result

Vivado xsim 2024.2 reproduced this four-state counterexample:

```systemverilog
remaining = 32'h0000010x;
amount = 0;
// remaining > amount: X
// (|remaining[31:4]) || (remaining[3:0] > amount): 1
```

The tool therefore withholds the patch for ordinary four-state `logic` operands. A known-input hardware contract alone is not automatically an RTL simulation-equivalence proof. The actual `axis_bytes.remaining` DFX review shows the exact expressions at lines 46–47 as hypotheses, while preserving the measured carry-to-CE evidence separately.

The real DFX source set exceeds the full compilation budget. Its small parameter-free `axis_bytes` module can be elaborated in isolation. The evidence explicitly says so; no full-project or exact-cause claim is made. Source/report revision conflicts, duplicate modules and wrong hardware scopes suppress edits.

## BD placement and constraints

A same-clock AXI slice review now needs the declared interface link, a complete failing path crossing both instances, a unique shared literal `aclk`/`aresetn` net, a link to the captured clock source, and captured cross-instance net delay totaling at least 0.45 ns and 20% of the selected datapath. Different/unknown clocks still require CDC investigation. Unsupported pin conventions or unresolved Tcl produce an evidence request. These thresholds are applicability gates, not confidence or predicted benefit.

The independent streaming design initially exposed an overreach: matching the transmitter and receiver names triggered slice advice even though the slow combinational cone was inside the receiver. The corrected gate returns `bd.boundary_review`: a slice before the already registered transmitter cannot split that receiver cone. This example remains held out for the RTL rewrite but is now development evidence for the BD rule; it is not presented as untouched held-out BD validation.

Even a qualifying slice review still requires interface direction, reset polarity/release, all enabled sidebands, accepted-beat ownership, valid/data alignment, outstanding transfers, stalls, packet boundaries, invalid-beat suppression and legal added latency. A FIFO capacity review remains separate: buffering cannot repair a permanently slower consumer. No BD rewiring or numeric IP configuration is emitted.

Timing exceptions remain intent-gated and commented. Negative slack or rare use never warrants a false path. Clock-group precedence, bounded delays, bus skew, exact selector coverage, same-edge multicycle assumptions and CDC remain review obligations. The existing 2024.2 strategy mappings were rechecked against AMD's [opt/place table](https://docs.amd.com/r/2024.2-English/ug904-vivado-implementation/Directives-Used-by-opt_design-and-place_design-in-Implementation-Strategies) and [phys-opt/route table](https://docs.amd.com/r/2024.2-English/ug904-vivado-implementation/Directives-Used-by-phys_opt_design-and-route_design-in-Implementation-Strategies). Supplied script declarations remain distinct from completed experiment evidence.

## Evaluation corpus

`scripts/evaluate_review_corpus.py` records input hashes, partitions, expected labels, negative reasons, raw rules, plans, unknown mappings, missing detail and top recommendations. Nine captures cover seven RTL designs plus an insufficient-evidence fixture. This is a small labeled local corpus, not a general accuracy benchmark.

| Case | Evidence partition | Expected useful result |
| --- | --- | --- |
| Deep | Existing development regression | Measured deep logic; implementation experiment, no unsupported expression diff |
| Priority | Existing development regression | Connected priority mux evidence; preserve priority, no parallelization patch |
| Fanout | Existing development regression | Slow routed high-fanout branch; no reset removal |
| Clean | Existing development regression | No timing findings or edits |
| BLAKE2s DFX failing | Existing real-design regression | Framing/length comparison hypothesis, complete evidence on 18 failures; no patch |
| DFX passing configuration | Existing real-design regression | No timing findings; eight passing paths still have unavailable arc detail |
| Streaming boundary | New held-out RTL design; BD gate subsequently revised | Internal receiver cone review; reject unsupported slice placement |
| Memory/DSP | New held-out design | Actual RAM/DSP path families; no inferred legal extra latency |
| Insufficient evidence | Existing negative fixture | Explicit evidence request, unknown association, no patch |

The final run has **zero false-positive labels and zero missed expected labels** under these explicit labels. All nine captures correctly withhold a ready diff; positive diff generation is validated separately on development kernels and tests. There is one unknown path association in the insufficient fixture, eight incomplete passing paths in each DFX capture, and zero incomplete failing paths in the DFX failure. These are preserved, not converted into clean results. Two new routed holdout designs use a 2 ns clock, default directives and `xc7z020clg400-1`; streaming setup WNS is −12.370 ns / hold +0.100 ns, memory/DSP setup −11.234 ns / hold +0.074 ns.

Raw diagnostic grouping remains available. Review investigations combine only identical path sets; overlapping but different sets are not merged transitively. Actionable investigations lead the list, followed by measured negative slack × endpoint breadth, detail coverage and source specificity. The earlier severity-only ordering put unexplained I/O paths above actionable internal cases in three original fixtures; those unexplained paths remain visible after the ranking change. The final failing designs have concrete top-ranked reviews; the insufficient case correctly asks for evidence.

## Two isolated RTL experiments

`scripts/validate_semantic_changes.py` generates two comparison edits, retains exact diffs/hashes, compares before/after cycle behavior, and optionally implements four isolated variants. The cases are a 32-bit `>=` counter and a 64-bit `>` counter, both compared against a four-bit amount. They are development experiments, not held-out designs.

Each variant pair uses Vivado 2024.2, `xc7z020clg400-1`, 2.000 ns, identical XDC, OOC synthesis, default opt/place/route directives, no physical optimization, two threads and no seed override. Only one implementation per variant was run. OOC ports lack integration placement/clock-source information; I/O timing is therefore not accepted as full-design signoff. `scripts/measure_internal_paths.py` separately reopens those checkpoints and records register-to-register paths.

| Experiment | Internal setup WNS before → after (ns) | Internal TNS before → after (ns) | Failing internal endpoint pins | Internal hold WNS before → after (ns) | LUT / FF before → after |
| --- | --- | --- | --- | --- | --- |
| 32-bit `>=` | −2.377 → −1.659 | −112.901 → −80.414 | 64 → 64 | +0.293 → +0.547 | 97/32 → 73/32 |
| 64-bit `>` | −3.030 → −2.043 | −245.407 → −216.968 | 126 → 128 | +0.292 → +0.294 | 193/64 → 145/64 |

Endpoint counts include CE/data pins; they are not register counts. Both have zero failing internal hold endpoints, zero BRAM/DSP use, pulse slack +0.500 ns, complete routing of routable nets, zero routing errors and no DRC errors/critical warnings. Each has the retained `ZPS7-1` warning because these isolated kernels omit the PS7. Neither closes setup. The 64-bit result is a regression in failing internal endpoints despite better WNS. The 32-bit result is a promising internal experiment, not an accepted full-design change.

Whole-OOC reports are retained too: 32-bit global hold failures increase 7 → 12 at −0.020 ns worst hold; 64-bit worst hold changes −0.005 → −0.020 ns, while failing hold endpoints change 16 → 15. These involve the incomplete OOC boundary model and are not represented as verified integrated hold behavior. They prevent a full-design acceptance claim. DFX compatibility is not applicable to these kernels; no DFX RTL edit or `pr_verify` was performed.

The two cycle-comparison testbenches each pass 10,289 checks spanning reset, load priority, stalls, zero/max/equality/adjacent values and deterministic randomized cycles. A separate Verilator test exhaustively checks six generated operators over all 16-bit/4-bit binary input pairs (6,291,456 comparisons). This covers those expression domains and finite sequences; it is not arbitrary formal equivalence. Initial simulation harness runs stopped on expected width-extension warnings; those logs were retained, and corrected harness runs suppress only that deliberate warning. Functional failures were not hidden.

The prior hash implementation's +0.110 ns setup / +0.016 ns hold result remains a separately performed implementation experiment with unchanged RTL/constraints. None of these new RTL previews is credited for that result.

## Reproduce and inspect

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -m 'not vivado' -q
.venv/bin/python scripts/validate_semantic_changes.py \
  --output work/my-expression-experiments --with-vivado
.venv/bin/python scripts/measure_internal_paths.py \
  --experiments work/my-expression-experiments --output work/my-internal-reports
.venv/bin/python scripts/build_review_holdout.py --output work/my-heldout
.venv/bin/python scripts/evaluate_review_corpus.py \
  --dfx-inputs work/semantic-review/corpus-inputs \
  --heldout work/my-heldout --output work/my-corpus-review
```

Every output directory must be new. The DFX inputs are completed captures copied locally; they are not downloaded or rebuilt by the evaluation script. Local recorded evidence is under `work/semantic-review/`: `implementation-01`, `simulation-checked`, `internal-paths-01`, `heldout-01`, `corpus-final`, `xstate`, test logs and performance measurements. The xsim counterexample can be rerun there with `xvlog -sv tb.sv`, `xelab tb -s counterexample`, and `xsim counterexample -runall` using the installed Vivado binaries.

The 200-path DFX GUI analysis took approximately 3 seconds including bounded semantic review. The nine-case analysis/export run took approximately 7 seconds and about 164 MiB peak RSS. A separate synthetic 2,000-path stress input took 0.70 seconds for analysis/recommendations, about 77 MiB peak RSS; it reuses graph/source objects and is not a claim about worst-case independent designs. A GUI timer regression checks event-loop progress during semantic work. Child compilation is bounded to 6 seconds / 512 MiB; total application memory also depends on the bounded input capture and Qt views.

Dark/light dashboard, recommendation, evidence and preview screens were rendered at 1350×880 and 980×740. The small dashboard scrolls instead of crushing timing cards. The visible theme switch preserves selection, preview contents and local settings. Source links, issue filters, path navigation, copied Tcl/diffs and schema-v2 JSON/HTML exports have integration coverage. The engine remains offline and deterministic; no LLM or cloud service is used in analysis.
