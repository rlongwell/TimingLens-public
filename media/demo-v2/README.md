# TimingLens demo — PUNK'D revision

The same 4:25 engineering demo, now using the user's selected **PUNK'D by Out of Flux** download. The accepted Jarnathan narration, chapter timing, real application walkthrough, and engineering results are preserved. The closing credit names the new soundtrack. The original movie remains in `media/demo-v1`; this revision is `media/demo-v2/TimingLens-demo-PUNKD.mp4`.

## Music edit

The supplied MP3 contains 183.236625 seconds of decoded stereo audio. Onset analysis finds approximately 98.03 BPM. A nominal 98 BPM grid joins two passages with a two-bar, equal-gain S-curve crossfade at 107.755–112.653 seconds. This repeats 85.714 seconds of material without changing its speed. The final music source position is 179.352 seconds; a 2.8-second closing fade finishes the video.

The track receives a fixed −12.97 dB gain, placing the source at approximately −22 LUFS before narration ducking. Sentence-scale ducking preserves the musical arrangement while keeping the voice prominent. The accepted speech stem is reused. Final mastering and encoded measurements are recorded separately.

Source: the user explicitly selected `/home/rl/Downloads/Out of Flux - PUNKD.mp3`. `music-provenance.json` records the filename, SHA-256 and embedded rights notice. The archive includes this user-supplied asset for local reproduction; no publication or independent license verification was performed. The title and artist credit follow the user's selection and download filename.

## Rebuild

The archive preserves the repository-relative `media/demo-v2` and `work/demo-video-v2` paths. Requirements: Python 3.12, FFmpeg/ffprobe, Lato and DejaVu Sans Mono fonts. The final movie is 1920 × 1080 at 30 fps, H.264/AAC, with optional English captions and twelve chapters.

```bash
python3 -m venv work/demo-video-v2/.venv
work/demo-video-v2/.venv/bin/pip install -r media/demo-v2/requirements.txt
mkdir -p work/demo-video-v2/render work/demo-video-v2/stills
OPENBLAS_NUM_THREADS=1 work/demo-video-v2/.venv/bin/python media/demo-v2/music_edit.py
OPENBLAS_NUM_THREADS=1 work/demo-video-v2/.venv/bin/python media/demo-v2/edit.py
OPENBLAS_NUM_THREADS=1 work/demo-video-v2/.venv/bin/python media/demo-v2/mix.py
work/demo-video-v2/.venv/bin/python media/demo-v2/captions.py
work/demo-video-v2/.venv/bin/python media/demo-v2/finalize.py
work/demo-video-v2/.venv/bin/python media/demo-v2/verify_export.py
```

The full edit renderer works from the archived original capture. In the actual revision, `revise_picture.py` instead reused the accepted v1 picture and replaced only the closing eight seconds. It verifies that the first 7,712 coded picture units and every presentation timestamp are retained; the concat mux only repeats codec parameter headers at keyframes. This faster path requires the v1 picture file and is optional for reproduction.

The original voice MP3 and word timestamps are retained. No new TTS request or experiment build is needed. `script-readable.txt` is the readable script; `narration-tts.txt` retains provider pronunciation aliases. `voice-provenance.json` records the unchanged ElevenLabs Jarnathan / Eleven v4 settings and the user's explicit confirmation.

## Evidence retained from the original demo

The genuine Qt walkthrough follows inputs → Analyze → investigation → measured path → correlated source → verified variant sweep → reviewed diff → isolated build → Experiment Lab → regression checks → portable export. Build footage is labeled fast-forward. The fresh recorded sweep is `priority-20261117T054822Z-f51443e2`.

The original and three priority-mux candidates use Vivado 2024.2, xc7z020clg400-1, a 2 ns clock, and the same Default recipe. Each candidate passed the actual N=16 binary RTL equivalence gate and baseline/candidate simulations before its implementation build. The unchanged results are:

| Variant | Register WNS (ns) | LUTs | Full-example WNS (ns) | Full-example TNS (ns) |
| --- | ---: | ---: | ---: | ---: |
| Original | -5.515 | 16 | -8.149 | -32.939 |
| Balanced | -1.825 | 42 | -8.149 | -32.022 |
| Grouped | -1.651 | 24 | -8.211 | -34.194 |
| Priority mask | -1.336 | 26 | -8.149 | -42.617 |

All retain 33 FFs. The mask's register-path gain is 4.179 ns, while full-example TNS worsens and acceptance remains blocked. This is a single trial per variant. RTL proof scope is binary inputs and corresponding register states at N=16; no four-state, power-up, physical-netlist equivalence, or hardware performance claim is made. Diagrams explain RTL structure; physical metrics come from the recorded implementations.

The project code, board, active hash work, and original evidence were not changed for this soundtrack revision. `review.md` records final-file checks. `asset-manifest.json` identifies production assets by SHA-256.
