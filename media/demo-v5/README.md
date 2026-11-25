# TimingLens — guided experiments

A complete 5:05 demo of the easier desktop workflow, with the accepted opening explanation, a newly captured GUI walkthrough, and a fresh 250 MHz counter experiment. The accepted v3 and v4 videos are preserved unchanged.

## What changed in the tool

- **Start here** offers your own design or a guided counter experiment, and explains the input → investigation → comparison workflow.
- **Choose design files** routes Vivado projects/checkpoints and report/source bundles to the appropriate review screen. Selecting files does not start a tool.
- Four primary navigation choices keep the workflow visible; detailed tools remain available through one disclosure.
- The counter experiment opens with its highlighted RTL change. Advanced settings are collapsed; validation and recipe details have their own tab. Progress names the four stages.
- The guided 250 MHz run opens the whole-core comparison automatically. The Lab shows slack, failing endpoints and LUT use, plus the checks still needing attention. Register-only results and the existing acceptance policy remain available.
- Dark and light themes retain edits, with blue accents and neutral surfaces.

## What the movie demonstrates

Bring a Vivado project/checkpoint, or captured timing evidence plus matching RTL and XDC. Follow a priority-mux diagnosis through its measured path, source and reviewable experiment. Reopen completed, verified RTL variants to inspect timing/area tradeoffs and a design-wide regression. Then run the separate guided counter example in isolated copies.

The fresh counter run measured:

| Whole standalone core, global OOC | Original | Candidate |
| --- | ---: | ---: |
| Setup WNS | −0.633 ns | +0.407 ns |
| Setup TNS | −13.201 ns | 0 ns |
| Failing setup endpoints | 32 | 0 |
| Physical LUTs | 50 | 41 |
| Flip-flops | 32 | 32 |
| Hold WNS | +0.080 ns | +0.095 ns |

Both versions passed 10,289 finite behavioral-oracle cycles, followed by routed builds using identical 4 ns constraints and Default implementation scripts. This is standalone-core timing closure. Full-system integration remains untested and Lab acceptance remains incomplete. The separate register population preserves its 0.001 ns hold-margin regression and blocked verdict. No acceptance rules were changed.

The priority sweep is explicitly described as reopened evidence from the earlier completed experiment. Its binary-input, N=16 RTL equivalence scope is distinct from counter simulation and physical implementation. The mask improves register setup WNS by 4.179 ns with 26 logical LUTs versus 16; the full example's WNS stays at −8.149 ns and TNS worsens. The video keeps that blocked result visible.

## Deliverables and verification

`TimingLens-demo-guided-experiments.mp4` is 1920×1080, 30 fps H.264/AAC, with optional English captions and 15 chapters. `script-readable.txt`, `timeline.json`, `evidence-audit.json` and `review.md` document the story, actual footage, claims and QA. `portable-comparison/report.html` opens locally; its JSON runs can be imported into the Lab. `TimingLens-demo-v5-sources.zip` contains the edit scripts, captures, narration, music, native run evidence and product snapshot.

The product suite passed 259 tests; six opt-in Vivado example tests were skipped. The fresh counter run in the movie separately completed real Verilator validation and two real Vivado builds. The final small scope-label adjustment passed the three focused GUI tests again. The real interface was checked at 1920×1043 and 1350×880 in both themes. Board and active hash work were untouched.

The existing Jarnathan voice and PUNK’D by Out of Flux continue in this edition. The new walkthrough uses the first downloaded take from one ElevenLabs generation; settings and hashes are in `voice-provenance.json`. Audio content is checked with raw and encoded ASR and loudness measurements; no subjective listening review is claimed. The user selected the local music file; no remote publication occurred.

## Reproduce the saved edit

Unzip the source bundle into a new directory. Its `TimingLens/` folder preserves relative paths. Use Python with `media/demo-v5/requirements.txt`, FFmpeg and Lato / DejaVu Sans Mono fonts. No Vivado or hardware is needed to rebuild the video from saved footage.

```bash
cd TimingLens
mkdir -p work/demo-video-v5/render work/demo-video-v5/stills
python media/demo-v5/edit.py
python media/demo-v5/mix.py
ffmpeg -v error -y -i media/demo-v3/TimingLens-demo-PUNKD.mp4 \
  -map 0:v:0 -an -frames:v 2939 -c:v libx264 -preset fast -crf 17 \
  -threads 3 -pix_fmt yuv420p -video_track_timescale 15360 \
  -map_metadata -1 -map_chapters -1 work/demo-video-v5/render/accepted-prefix.mp4
python media/demo-v5/finalize.py
python media/demo-v5/verify_export.py
```

The first 2,939 opening frames are re-encoded to an exact cut boundary. The original movies are not modified. All new GUI footage comes from actual interactions captured at 3840×2086 directly from Qt, cropped before one final downsample. The long counter run is labeled 16× fast-forward (actual source ratio 15.76×). File-picker navigation and idle time are elided. Source, diff and log highlighting are part of the application.

`record_gui.py` documents the original capture setup; record into a fresh directory for another take. `audit_evidence.py` additionally requires the product dependencies from `pyproject.toml`. The media bundle is for local use and reproduction; music rights remain with their owners.
