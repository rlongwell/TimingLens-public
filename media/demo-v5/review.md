# Production review

The new movie retains the first four explanatory chapters and replaces the application walkthrough with the redesigned interface. Its complete running time is 305.167 seconds. The original v3 and v4 movies remain byte-identical to the accepted versions, verified by SHA-256.

## Product behavior

The initial commit `1b58f8a` saved the pre-change project before implementation. The product suite reports **259 passed, 6 skipped** in 1071.85 seconds. The skipped tests are six opt-in Vivado example tests. The final scope-label change was followed by **3 passed** focused GUI tests. The separate recorded counter experiment completed Verilator validation and two Vivado routed builds; all command return codes were zero.

The real desktop interface was inspected at 1920×1043 and 1350×880. Start, the guided counter, collapsed/expanded advanced settings and both themes were checked. Final Lab summary renders were also inspected at 1350×880. Text remains legible, primary actions remain visible and detailed tables scroll within the available area. Theme changes preserve edits. Automatic handoff opens the intended whole-core population.

## Evidence and claims

`audit_evidence.py` verifies identical constraints and scripts, eleven frozen input hashes, oracle success, measured timing/area results, retained integration uncertainty and the portable export reopened through the product importer. It also validates the retained priority sweep's proof bundles and its exact timing/LUT tradeoffs and full-example regression.

The counter is a distinct 250 MHz standalone OOC experiment. Positive setup WNS is not represented as complete system acceptance. The priority sweep is described as reopened completed evidence. Its scoped formal RTL equivalence is not conflated with the counter's finite simulation. Register-only and whole-design results are kept separate.

No board APIs, serial access, programming, deployment, active hash project edits or bitstream operations were used.

## Picture and timing

Real GUI interactions were captured directly from Qt at 3840×2086. The editor crops native pixels before one final downsample to 1080p. Text is not enlarged from a low-resolution desktop video. The source diff and log colors come from the product. File-picker navigation and idle periods are elided; the counter build is explicitly marked 16× fast-forward. Stationary holds retain actual captured frames.

The source capture, action frames, wall times and phase transitions are retained. The source Matroska has a readable 1,034.1-second index; the selected footage was decoded during editing. Closing the window ended the recording. The successful run and all chosen footage precede the end of the capture. No missing result or progress was synthesized.

The final MP4 verification decodes all picture/audio data, checks continuous 30 fps timestamps, verifies its 15 chapters and English subtitle stream, rejects unexpected sampled black frames, and confirms audio packets match the reviewed AAC master. Frame samples and dense nine-frame temporal strips cover the opening splice, navigation, source/experiment handoff, point selection, scope change, guided launch, run click, automatic Lab handoff, validation tabs and export.

## Audio

The new narration uses the existing user-selected Jarnathan voice, Eleven v4, stability 0.62, similarity 0.75 and clone strength 0. The first downloaded generation take is used. The accepted opening speech stem is retained through the end of its fourth chapter; the new paragraph begins at 98.167 seconds.

PUNK’D continues across the full movie using a two-bar, 98 BPM crossfade and smooth speech ducking. Encoded AAC measures **−16.02 LUFS integrated**, **−3.22 dBTP**, **2.50 LU loudness range**. The music stem is present throughout, excluding deliberate endpoint fades. Raw ASR and encoded-mix ASR are retained separately; captions correct orthography without rewriting the raw recognition records. Numerical claims and paragraph transitions are checked against both the script and measured evidence. No subjective human listening review is claimed.

## Retained limits

The movie demonstrates supported examples and one physical implementation trial per candidate. It does not establish repeatability, arbitrary automatic RTL repair, post-synthesis formal equivalence, four-state behavior or complete system validation. The portable evidence and native logs remain available for engineering review.

Final encoded review: all 9,155 video frames and 14,647,968 decoded audio samples passed validation. All eleven temporal strips and the full contact sheet were inspected. The encoded source diff, highlighted build log and result summary were inspected individually at 1920×1080; text and numbers are readable, the cursor follows the recorded actions, the automatic comparison transition is present, and no unintended light-theme flash or empty result replaces the final evidence.
