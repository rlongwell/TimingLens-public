# TimingLens demo — sharp GUI retake

The 4:25 demo retains the accepted Jarnathan narration and engineering story, uses the user-selected **PUNK’D by Out of Flux**, and replaces the application walkthrough beginning at 1:38 with new real GUI footage.

## What changed

- GUI and code text increased to 16 px; navigation widened; timing-table headers fit their labels; schematics open at a readable zoom.
- Source diffs show RTL syntax, file/hunk headers, additions and removals. Live logs distinguish stages, warnings, failures, successes, IDs and numbers. Both themes are supported.
- The real application was rendered directly into a 3840×2086 capture of its 1920×1043 window. The edit crops from these original pixels and downsamples once to 1080p. It does not shrink the GUI and then enlarge it.
- A fresh isolated priority-mux sweep supplies genuine proof, simulation, implementation and Lab footage. Build time is visibly fast-forwarded; dialogs and idle navigation are trimmed.
- Music runs continuously, ducked below speech. The final AAC track is copied exactly from the checked PUNK’D mix; the narration has not been regenerated.

The board and active hash work were not accessed. Original demo exports remain available.

## Viewing

Open `index.html` for the movie, optional captions, chapter navigation, and actual portable Lab comparison. The MP4 also includes embedded English subtitles and chapter markers.

## Engineering evidence

Inputs: saved timing evidence plus matching `design.sv` and `timing.xdc`. The introduction also explains Vivado projects/checkpoints and report-based input workflows.

The sweep uses priority_top, N=16, xc7z020clg400-1, a 2 ns clock, OOC implementation, and Vivado 2024.2 Default for all four builds. Three candidates must pass RTL equivalence and simulation before implementation. Equivalence covers binary inputs and corresponding register states, not four-state behavior, power-up or the implemented netlist.

Measured register WNS / logical LUTs: original −5.515 ns / 16; balanced −1.825 / 42; grouped −1.651 / 24; mask −1.336 / 26. The mask improves register WNS by 4.179 ns, while full-example WNS remains −8.149 ns and TNS worsens from −32.939 to −42.617 ns. Acceptance remains blocked. This is one trial per variant, not a repeatability claim.

## Editable production sources

The ZIP preserves scripts, timeline, original narration, music, final AAC, captions, native capture, real click/phase timestamps, experiment evidence, GUI changes and checks. Unzip at one root so `media/` and `work/` remain siblings. The media Python environment is separate from the TimingLens application environment. Reproduction also requires FFmpeg and the Lato / DejaVu Sans Mono system fonts.

```bash
python3 -m venv work/demo-video-v3/.venv
work/demo-video-v3/.venv/bin/pip install -r media/demo-v3/requirements.txt
mkdir -p work/demo-video-v3/render work/demo-video-v3/stills
OPENBLAS_NUM_THREADS=1 work/demo-video-v3/.venv/bin/python media/demo-v3/edit.py
work/demo-video-v3/.venv/bin/python media/demo-v3/finalize.py
work/demo-video-v3/.venv/bin/python media/demo-v3/verify_export.py
```

The full renderer reproduces the entire movie without a provider login, voice generation, Vivado rerun, or access to the board. `music_edit.py` and `mix.py` preserve the soundtrack edit and mastering recipe. `record_gui.py` documents the live capture process. Fresh capture requires TimingLens/PySide; fresh experiment builds require the local Vivado and Yosys toolchain.

Production: AI-assisted scripting, graphics, editing and verification. Narration: ElevenLabs, Jarnathan voice. Music: PUNK’D · Out of Flux, supplied by the user from their local download; source provenance is recorded in the soundtrack edit metadata. No public upload was made.
