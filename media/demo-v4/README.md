# TimingLens alternate demo — timing closure ending

The full accepted demo is preserved through 4:17.067. This alternate version adds an 80-second counter experiment before the credits, for a total of 5:45.067. The accepted `media/demo-v3/TimingLens-demo-PUNKD.mp4` and primary latest-video link remain unchanged.

## What the new ending demonstrates

A separate 32-bit counter core targets 250 MHz (4 ns). The original RTL fails timing; TimingLens factors its unsigned wide-to-small comparison, runs both versions against the existing independent behavioral oracle, and implements both with identical XDC and the same Default recipe. This is a new comparison, explicitly introduced in speech and on screen. It does not relax constraints between variants or relabel the earlier priority-mux experiment.

The fresh GUI run `counter32_250-20261117T085217Z-22594287` measured:

| Full standalone-core / global OOC metric | Original | Factored |
| --- | ---: | ---: |
| Setup WNS | −0.633 ns | +0.407 ns |
| Setup TNS | −13.201 ns | 0 ns |
| Failing setup endpoints | 32 | 0 |
| Hold WNS | +0.080 ns | +0.095 ns |
| Hold / pulse-width failures | 0 / 0 | 0 / 0 |
| Physical LUT use | 50 | 41 |
| Flip-flops | 32 | 32 |

Both passed 10,289 finite oracle cycles. Setup, hold, pulse, routing, DRC error/critical, source-byte and controlled-build checks pass. The Lab retains **Integrated design validation: Not tested**, so overall acceptance remains **incomplete**. The film calls this standalone-core timing closure. No board deployment or active hash work was involved.

The separate register-only population retains its 0.001 ns positive hold-margin decrease (0.295 → 0.294 ns, zero failures) and strict regression verdict. Both comparison populations are preserved in the evidence package. No acceptance logic was changed for the video.

## Contents and production

- `TimingLens-demo-timing-closure.mp4`: 1080p, 30 fps H.264/AAC, optional English captions and chapter markers.
- `script-readable.txt` and `narration-tts.txt`: complete scripts, including all accepted chapters.
- `ending-readable.txt`, `ending-tts.txt`, `new-scenes.json`: added chapter.
- `timeline.json`: source cut points, camera crops, reveal timing and chapter placement.
- `evidence-audit.json`: report-backed claims, input hashes and run scope.
- `review.md` / `export-verification.json`: actual export checks and their limits.
- `portable-comparison/`: self-contained HTML/JSON Lab export; open `report.html` locally.
- `TimingLens-demo-v4-sources.zip`: private reproduction bundle, with saved captures, accepted base, new voice, user-supplied music, code, report evidence and product snapshot. Music rights remain with their owners; no publication or license grant is implied.

The existing Jarnathan voice/settings were preserved: Eleven v4, stability 0.62, similarity 0.75, clone strength 0. PUNK’D by Out of Flux continues across the insertion with a beat-aligned two-bar crossfade. The first 257.067 seconds of the accepted PCM mix are reused unchanged. Video packets for the first 7,712 frames are copied exactly from v3.

GUI capture uses the actual Qt app rendered directly at 3840×2086, with real CUA interactions, then a single downsample after each crop. Source and logs retain the accepted syntax highlighting. The long tool run is visibly fast-forwarded; measured runtimes are retained independently. The first capture's GUI-thread instrumentation was replaced by passive main-thread status polling after a recording-only crash; the complete successful run is in `capture-retake`.

## Reproduce from the source bundle

Unzip into a new folder. Its `TimingLens/` directory preserves relative paths. Use a Python environment with the versions in `media/demo-v4/requirements.txt`, FFmpeg, and Lato / DejaVu Sans Mono fonts. The saved footage avoids any need to run Vivado or access hardware when reproducing the edit.

```bash
cd TimingLens
python media/demo-v4/mix.py
python media/demo-v4/edit.py
ffmpeg -v error -y -i media/demo-v3/TimingLens-demo-PUNKD.mp4 \
  -map 0:v:0 -c:v copy -frames:v 7712 -an -map_metadata -1 -map_chapters -1 \
  work/demo-video-v4/render/accepted-prefix.mp4
python media/demo-v4/finalize.py
python media/demo-v4/verify_export.py
```

Run `edit.py --stills` for review stills. `record_gui.py` is retained as capture source, not a prerequisite for reproduction. To record another take, first give it a fresh capture directory. Product source and the added example are included separately in the bundle; see `docs/counter-runner.md` for running a new local counter experiment.

Original provenance: `media/demo-v3/voice-provenance.json`, `music-provenance.json`, `music-edit.json`; new voice provenance: `media/demo-v4/voice-provenance.json`. The downloaded song's original metadata reads “All Rights Reserved to www.Art-list.io.” The user's explicit instruction selected it for this local demo; no remote publication took place.
