# Export review

Reviewed November 17, 2026. Final movie: 265.067 seconds, 1920 × 1080, 30 fps, H.264/yuv420p, stereo AAC at 48 kHz. Twelve chapters and optional English captions are embedded. `export-verification.json` records the final SHA-256 and measurements.

## Picture

Inspected 36 frames spanning every chapter in the actual encoded MP4, plus full-size source, result-table, and regression frames. Reviewed dense encoded-frame sequences around Analyze, Open timing path, Try this experiment, build completion, the frontier reveal, population switching, export completion, and the closing fade. Cursor endpoints align with the real controls; the actual UI response follows the click. No unrelated desktop, computer-use/debug banners, or duplicate cursors appear in the reviewed footage.

Corrections before final export: preserved transparency in animated reveals, moved the balanced-tree label below its nodes, clarified its input bus, expanded the mask schematic to sixteen lanes, and constrained camera crops to preserve source lines and metric labels. Secondary navigation and off-focus detail may leave the frame during a zoom; the explained value or source line remains visible. The build segment explicitly says fast-forward and shows actual completion followed by the Lab opening.

## Speech and sound

The complete final mixed AAC stream was transcribed locally with Whisper and compared with the narration script, including 5.515 ns, 4.179 ns, 26/16/24/42 LUTs, the proof scope, and the regression explanation. The spoken final sentence ends at approximately 255.34 s; credits and music continue to 265.067 s. Proper terms in the optional captions use the intended spelling rather than ASR capitalization or homophones.

Final encoded integrated loudness is **−16.02 LUFS**, true peak **−3.26 dBTP**, and loudness range **2.50 LU**. The full movie decoded without errors. The ducked score is continuous across the edit; its quietest one-second window outside opening/closing fades is −41.65 dBFS RMS. Separate voice, music, and mixed stems remain in the production workspace.

Review methods were encoded-frame inspection, dense motion sequences, a final-stream transcript, and signal-level audio checks. A human subjective listening review is not claimed; voice timbre and musical taste remain matters for listening preference.

## Evidence

`audit_evidence.py` validated both populations of the fresh completed sweep: eight run records, all three actual proof results, expected LUT/FF counts, comparisons, and acceptance status. It also reopened both portable-export run records. Register WNS improves by 4.179 ns for the mask; design-wide WNS remains −8.149 ns and TNS changes from −32.939 to −42.617 ns. Every candidate remains acceptance-blocked. The chart does not confuse the Pareto frontier with design acceptance.

The run is a standalone N=16 example under the same Default recipe. No board was accessed and no active hash work was modified. No hardware result, repeatability, general-purpose automatic RTL optimization, or four-state equivalence is claimed.

## Reproduction

`README.md` gives the rebuild commands. The source archive includes the accepted voice take, the original GUI capture with event/frame data, procedural score/render/edit code, scripts, word timing, captions, fresh sweep artifacts, portable export, review measurements, and SHA-256 asset manifest. It excludes virtual environments, downloaded speech models, and disposable render intermediates.
