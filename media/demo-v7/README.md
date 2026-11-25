# TimingLens guided counter walkthrough

This cut follows the structure of the earlier guided experiments demo. It introduces the tool, the supported inputs and the analysis model, then follows the baseline counter through Project files, Overview, Fix recommendations, the raw Vivado path and correlated RTL. The original guard and the factored guard are explained before the runner starts. The last chapters show the measurements, validation scope and portable HTML report.

The new application captures were made with the actual TimingLens Qt widgets at double resolution. The file chooser, analysis, path navigation, comparison and report export use the product’s normal controls or import handlers. The editor holds the resulting screens to give viewers time to read them. Desktop views share one scale and origin. The two implementation clips are accelerated approximately 28×. File-picker navigation and wait time are elided.

## Evidence and audio

The footage of the live build and its run records come from the retained counter32_250-20261117T092729Z-b24fadcc experiment. The captured baseline session, original SystemVerilog and original XDC were loaded through the desktop for this cut. Its first recommendation is to shorten the comparison-to-enable path. The selected path is P00001, from remaining_reg[0]/C to remaining_reg[3]/CE. Its six logic levels include four CARRY4 cells, with 1.578 ns logic delay and 2.802 ns routing delay. The routed report gives 4.720 ns required and 5.353 ns arrival.

The baseline and candidate use identical interface budgets, a 4.000 ns clock, and the Default recipe in Vivado 2024.2. A finite 10,289-cycle check compares both implementations' RTL behavior against the counter model. The whole standalone core goes from −0.633 ns to +0.407 ns setup slack, 32 to 0 failing setup endpoints and 50 to 41 physical LUTs. Integrated design validation remains untested. The exported comparison folder contains both complete run records, comparison.json and report.html.

The opening uses the accepted introduction voice track. New walkthrough narration uses Jarnathan with the existing Eleven v4 settings (stability 0.62, similarity 0.75, clone strength 0). Playback is 0.96× with pitch preserved. The PUNK’D arrangement by Out of Flux runs throughout. verification.json records the encoded media measurements. Speech verification used the raw take and final AAC word-timed transcripts. The supplied final AAC matches the reviewed mix byte-for-byte at the packet level.

## Recreate the movie

Extract the source ZIP preserving the media and work directories. The included captures and mixed AAC are sufficient to generate the complete export. Use the versions in requirements.txt, plus FFmpeg, Lato and DejaVu Sans Mono. From the extracted root run the following commands.

```sh
python media/demo-v7/edit.py
python media/demo-v7/finalize.py
python media/demo-v7/verify.py
```

The timeline, control coordinates and framing are encoded in edit.py, opening.py and capture/actions.json. The archive also includes the spoken script, captions, narration take, timing transcripts, actual portable comparison and visual review sheets. For a new audio mix in the original project checkout, mix.py reads the v5 intro voice stem and its existing edited music bed. prepare_run.py can rebuild the three live shots from the original v5 lossless recording. capture.py can repeat the walkthrough against the retained job using the TimingLens product environment with QT_QPA_PLATFORM=offscreen. The bundled report image was rendered directly from the exported report.html.
