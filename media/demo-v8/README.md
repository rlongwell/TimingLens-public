# TimingLens — from a failing path to a routed pass

The 2:30 walkthrough follows one 32-bit counter. It opens the failing Vivado evidence, traces the enable path, reviews the suggested SystemVerilog change, runs the experiment and compares the routed builds. The old worked examples have been cut. The explanation of the replacement runs from 1:19 to 1:29. Existing versions of the movie remain available.

## The experiment

Both versions of the standalone counter target the same xc7z020clg400-1 device with a 4 ns clock and the same Vivado 2024.2 Default recipe. The failing enable path contains four CARRY4 primitives. The original checks a 32-bit count against a 4-bit request. The replacement tests whether any upper bit is set or the low four bits cover the request. The register update stays on the same clock edge.

The actual runner checked the two RTL implementations against a counter model over 10,289 simulation cycles, then built and routed both in isolated directories. Build footage is accelerated and the normal interface is held while the narrator explains the evidence.

| Whole-core routed measurement | Baseline | Candidate |
| --- | ---: | ---: |
| Worst setup slack | −0.633 ns | +0.407 ns |
| Failing setup endpoints | 32 | 0 |
| Failing hold endpoints | 0 | 0 |
| Failing pulse-width checks | 0 | 0 |
| Physical LUTs | 50 | 41 |
| Flip-flops | 32 | 32 |

The standalone core meets 250 MHz. Full-system timing remains untested. The behavioral check covers a finite simulation. The portable comparison includes the evidence and recorded scope of each check.

## Picture and audio

Native Qt screens were rendered at twice their logical dimensions. The walk through the application uses real controls, the runner log shows the fresh tool run, and the final HTML views come from the exported report. File pickers and idle time are elided. A single framing is held while reading each diff or log. Cut points and control coordinates are recorded in the edit sources. The underlying application and HTML export highlight source, diffs, script commands, JSON, timing quantities and log messages.

Jarnathan uses the existing Eleven v4 settings, with stability 0.62, similarity 0.75 and clone strength 0. The new take plays at 0.96× with preserved pitch. Tcl is written “tickle” in the speech input and “Tcl” on screen and in captions. Whisper word timing and a separate PocketSphinx acoustic comparison checked the word in the raw take and the encoded final audio. PUNK’D by Out of Flux plays throughout under the narration. The audio and video measurements are in verification.json.

## Rebuild the edit

Extract the edit archive preserving its media and work directories. With FFmpeg, Lato, DejaVu Sans Mono, Pillow, NumPy, SciPy, soundfile and PyAV installed, run these commands from the extracted root.

```sh
python media/demo-v8/edit.py
python media/demo-v8/finalize.py
python media/demo-v8/verify.py
```

The archive includes the accepted take, mixed AAC, word timings, GUI shots, the live log captures with their measured timestamps, the self-contained comparison and the files used to verify the clock, recipe and simulation. Identical PNGs in the live sequence share one image file in the packaged index. The soundtrack is retained in the finished mix.

In the TimingLens checkout, record_run.py starts the real counter experiment. capture.py opens the newly produced baseline capture, reviews the recommendation and exports the pair. capture_report.py records the local HTML with Qt WebEngine at display scale 2. mix.py uses the earlier PUNK’D music stem. check_pronunciation.py uses the system's English PocketSphinx acoustic model and CMU dictionary.
