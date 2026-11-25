# Alternate demo review

The accepted v3 remains unchanged (SHA-256 `23cbe3180e97453c429f43dbd3479dd1da7ce39699305115d43c0de45f6be099`). Its first 7,712 compressed video packets are identical in the alternate movie. The first 12,339,200 samples of the accepted 48 kHz PCM mix are reused sample-exactly. The new chapter starts at 4:17.067; new narration starts 0.2 seconds later. Duration is 5:45.067, with all accepted chapters retained and eight seconds of closing credits.

## Picture and export

The final 1920×1080 / 30 fps H.264 export was decoded completely, including every audio packet. It contains 10,352 video frames with continuous frame timestamps, stereo AAC, optional English captions and 16 chapters. `export-verification.json` records the final movie hash and checks. The AAC packets match the reviewed encoded master exactly.

The new chapter's encoded frames were visually inspected at the baseline metrics, constraint introduction, diagram reveals, highlighted diff, Run action, live build, full-core comparison, zero-crossing result graphic, integration check, export confirmation, and closing fade. Full-resolution views confirm readable diff and Lab text. Seven dense frame sequences were inspected for cursor/action alignment, transitions, meaningful signal traversal, the slack animation, export response and credit fade. A brief intermediate register-only view was removed from the comparison switch; the real “Compare global OOC” action and response remain. No result or progress was fabricated.

The GUI was captured directly at 2× device resolution and cropped before a single final downsample. Only tool execution footage is accelerated, with a visible Fast-forward label. Functional validation and real baseline/candidate builds completed before the result was recorded. Timing values in overlays are matched against the fresh comparison JSON and native reports.

## Audio and speech

Encoded integrated loudness: **−16.01 LUFS**; true peak: **−2.75 dBTP**; LRA: **2.50 LU**. The accepted voice and current Jarnathan settings are preserved. PUNK’D is continuous across the edit; a second two-bar, 98 BPM crossfade extends the supplied track. The new ducked music stem has no missing one-second regions outside fades (minimum RMS approximately −49.24 dBFS). The insertion sample step is 0.00127, within the surrounding music waveform's normal variation.

Raw source-take and encoded-mix word-timed ASR are retained. The final encoded mix recovers the key values: 250 MHz, 4 ns, 10,289 cycles, −0.633 to +0.407 ns, 32 failures to zero, 50 to 41 LUTs, and 32 flip-flops. The final spoken sentence ends around 5:36.03, before the credits at 5:37.067. Captions use canonical spelling; raw recognizer output is unchanged.

Review limitation: this review used visual frame sequences, word-timed ASR and audio signal measurements, not a subjective human listening session. ASR spells the spoken phrase “timing closure” as “time enclosure” and “too” as “2”; these homophonic recognizer outputs are retained in the raw record. All measured numeric claims are recovered correctly in the final mix.

## Evidence and product validation

The new `counter32_250` profile has a separately hash-checked 4 ns XDC and exactly the same RTL/testbench as `counter32`. Both sides of the experiment use the same constraints and Default recipe. All **42 relevant unit/integration tests passed**. A fresh GUI-initiated Vivado 2024.2 / Verilator 5.020 run passed the finite 10,289-cycle oracle validation and both routed builds. The baseline and candidate implementations took 109.170 and 105.538 seconds respectively; video fast-forward does not change those measurements.

The full-core OOC comparison passes setup, hold, pulse-width, route, DRC error/critical, source byte and controlled-build checks. Integration stays untested and acceptance stays incomplete. The separate register-only population retains its 0.001 ns positive hold-margin decrease and strict regression verdict in the preserved evidence. This is measured standalone-core timing closure, not board or full-system signoff.

Board connections, board programming, active hash work, existing stress examples, earlier results and the accepted movie were untouched. No commit, push or public upload was performed.
