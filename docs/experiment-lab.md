# Experiment Lab

The comparison workspace operates on completed evidence. It supports the retained counter experiments and DFX captures as well as imported native TimingLens sessions. The separate [Counter runner](counter-runner.md), available through **Run counter…**, can now execute the two bundled counter fixes in isolated copies and feed completed results into this workspace. Imported evidence and change previews are never executed.

## Desktop workflow

1. Open **Experiment Lab** in the sidebar. Select an example and **Load example**, or **Import runs…** to load saved JSON evidence.
2. Choose baseline and candidate. **Compare** computes a deterministic result in a worker thread. Changing selectors leaves the last result labeled with its original pair and disables export until the new selection is compared.
3. Inspect measurements, captured endpoint changes, acceptance checks, comparison context, source/report evidence, and a recorded change preview. The endpoint search supports names and clock pairs. **Inspect baseline/candidate path** opens the embedded session in the existing path viewer, with its graph and source navigation.
4. **Export comparison…** creates a new numbered directory under the selected parent. It contains `baseline.run.json`, `candidate.run.json`, `comparison.json`, and `report.html`. Reimport the run files on another machine to reproduce the result without the original project tree.

Imports and exports run off the UI thread. An operation failure preserves the last comparison. Closing during work waits for worker cleanup. A bounded history of 24 records is stored as file paths and selections in the existing ignored `.settings/gui.json`; **Restore history** explicitly reloads those paths. No history file is read as a command. There is a 64 MB per-record input limit and a 256 MB per-import limit.

## Verdicts and scope

The **observed outcome** is improved, regressed, unchanged, inconclusive, or not tested. Known incompatible device, tool release, integration mode, clock model, captured timing corners, constraints, compile context, declared design identity, or summary population makes the result inconclusive. Missing context makes numeric comparisons provisional and prevents acceptance readiness. RTL and implementation-directive changes are shown separately because those may be the intended experiment; neither proves causation.

Worsening comparable WNS, TNS, failing endpoint counts, pulse checks, routing checks or DRC counts takes precedence over improvements. A captured endpoint moving from passing to failing is also a regression. Other endpoint deltas remain available for review. Resource counts are tradeoffs, with no area budget inferred. The **Regression guard** explains the checks that block acceptance even if all final timing values are positive.

**Acceptance** is blocked by a failed check or regression, incomplete when required evidence is missing, and review ready only when the supplied scoped checks pass. It never means automatic approval or general equivalence. Checks cover comparison context, routed stage, setup, hold, pulse width, routing, DRC, embedded source bytes, scoped functional validation, exact source/checkpoint correspondence, DFX compatibility where applicable, and integrated design scope. A non-DFX declaration only makes DFX compatibility inapplicable. A functional check declared inapplicable does not count as a pass.

Native imports cannot establish complete build context, constraint coverage, source/checkpoint correspondence or functional equivalence. These remain missing unless independently captured in a run record. A digest proves byte identity, not authenticity or which sources built a checkpoint. Imported pass/fail check declarations require a scope and evidence description; they are records of supplied evidence, not independently rerun tests.

## Captured paths versus summary populations

Design-wide metrics use the native session summary. Register-only counter metrics use the separately retained internal-path TSV, whose bytes and summaries are validated. Internal TNS is rounded to the original review's three-decimal-nanosecond precision. The populations are never mixed. The register-only counts describe endpoint pins (including D and CE), not numbers of registers. Global counter summaries include OOC I/O paths and have separate selectable pairs.

Endpoint correspondence uses the analysis type, exact captured endpoint name, and launch/capture clock names, then chooses the worst captured slack for each group. Path IDs are local identifiers and are never used for correspondence. Changed launch points are disclosed. Missing names or clocks produce ambiguous rows; unmatched paths mean only that they were not captured on the other side. They cannot establish creation, removal or repair. In particular, the two additional failing endpoints in the 64-bit internal summary are not individually identified by the retained capped detailed sample. The empty regression filter explains this limitation.

New counter-runner jobs also collect a separate register-only detailed path set. The validated 64-bit job captured all 128 endpoint groups per check and identified two passing-to-failing setup matches: `remaining_reg[1]/D` (+0.321 → -0.905 ns) and `remaining_reg[0]/D` (+0.646 → -0.588 ns). This is additional measured evidence from a new run, not a retroactive inference about the older capped capture.

Source text and reports are displayed as plain text. Source paths, origins and checkpoint references are descriptive and are never followed by Lab imports or path inspection. An embedded source/hash mismatch is rejected unless the text contains lossy decoding replacements, in which case byte verification remains not tested and the limitation is retained. The older DFX capture contains one such vendor-IP source snapshot.

## Retained results

These are already completed captures copied under TimingLens. Preparing this catalog does not invoke Vivado, run a simulation, access the board, or read the active hash project's files.

| Pair | Setup WNS, ns | Failing setup endpoints | Observed outcome | Acceptance |
| --- | --- | --- | --- | --- |
| 32-bit counter, registers | -2.377 → -1.659 | 64 → 64 | Improved | Blocked: setup still fails; integration unvalidated |
| 64-bit counter, registers | -3.030 → -2.043 | 126 → 128 | Regressed | Blocked |
| 32-bit counter, global OOC | -2.377 → -1.659 | 96 → 96 | Regressed: hold TNS/count worsen | Blocked |
| 64-bit counter, global OOC | -3.030 → -2.043 | 190 → 192 | Regressed: setup count and hold worsen | Blocked |
| Retained DFX routed captures | -0.011 → +0.110 | 18 → 0 | Improved, provisional | Incomplete |

Physical LUT use falls **50 → 42** for the 32-bit counter and **98 → 82** for the 64-bit counter. Logical LUT primitive counts separately fall **97 → 73** and **193 → 145**. They are different quantities because physical implementation may combine logical LUTs.

The finite counter simulations compared 10,289 cycles per kernel; they are not arbitrary formal equivalence or exact checkpoint correspondence proofs. Both kernels remain OOC with incomplete port/clock-source placement context. DFX lacks XDC and full implementation context, utilization/DRC reports, functional validation and `pr_verify` evidence. Its measured timing improvement cannot establish compatibility or identify a proven cause.

On this development checkout the prepared ten runs live in `work/experiment-lab/catalog/`. On another checkout, import exported records. If the completed `work/semantic-review/` captures are present, create a fresh catalog with:

```bash
.venv/bin/python scripts/prepare_experiment_lab.py --output work/experiment-lab/catalog
```

The script reads only fixed TimingLens-local capture paths. It embeds supporting TSV, Tcl, manifests and simulation text; it hashes checkpoints without opening them in Vivado. Raw bitstreams/checkpoints are not duplicated in exports. Existing output directories are refused.

## File contract

Run records use `timinglens_run: 1`, a canonical SHA-256 and a strict `run` object. The object contains the native session, explicit metric population, timing summaries, additional metrics with measurement labels, build context, scoped checks, artifact digests, embedded supporting attachments, notes and an optional recorded diff. Known report measurements must agree with imported metric values; design summaries must match the native session; register summaries must match one embedded and hashed `register_timing` TSV. Missing reports are not interpreted as zero violations.

Comparison documents use `timinglens_comparison: 1` and rule version `lab.compare.v1`. They retain both run fingerprints, metric deltas, context checks, acceptance checks, endpoint correspondence and limitations. The accompanying HTML escapes all evidence and contains no executable script. CLI exit 0 means comparison/export completed, not that the candidate passed acceptance; read the verdict fields for that decision.
