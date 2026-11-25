# TimingLens demo revision review

The application walkthrough from 1:38 was recaptured from the real GUI at 3840×2086, with larger text and new source-diff/live-log highlighting. The cut retains the original engineering story and narration and uses the user-selected PUNK’D soundtrack.

## Product checks

- New Qt highlighting tests cover RTL tokens, strings versus comments, independent before/after multiline-comment state, UTF-16 offsets, log severity, incremental append, theme switching, and unchanged evidence text/cursor.
- Fourteen existing targeted GUI checks passed. The two new checks passed after fixing the test helper’s ownership of a borrowed Qt format object.
- After the header/zoom adjustments, the relevant five tests passed again: highlighting, desktop GUI and Lab integration.
- Additional rendering checks confirmed every timing-table header fits and the schematic opens at scale 1.0 or larger. The resulting application render was inspected.
- Real source diffs and live logs were visually inspected in both dark and light themes. Input analysis, source correlation, sweep launch, Lab population switching, comparison inspection and portable export were performed through the application.

## Fresh experiment evidence

The new isolated sweep completed all four physical builds, three 67-point RTL equivalence gates and the baseline/candidate simulations. The final register and full-example values reproduce the narration and charts exactly. The actual exported baseline and candidate were reopened by the Lab loader. Detailed evidence is in `evidence-audit.json` and the source archive.

No board operations, active hash work, commits, remote pushes or public uploads were performed.

## Export checks

- 1920×1080, 30 fps, 7,952 frames, 4:25 duration; H.264 picture and stereo 48 kHz AAC; 12 chapters and 98 caption cues.
- The accepted opening 2,939 coded video frames are unchanged. The new GUI begins at 97.9667 seconds.
- All 12,426 AAC packets and their timestamps match the checked PUNK’D mix exactly. The Jarnathan narration is unchanged. Music remains continuous and ducks under speech.
- Full audiovisual decode, encoded loudness/peak analysis, sampled exported frames and cursor/action sequences are checked. Final output details are in `export-verification.json` and `qa/retake-verification.json` in the archive.
- Audio review uses word-timed ASR and signal analysis of the final encoded track; no subjective human-listening claim is made.

Real build time is visibly fast-forwarded. Idle time and file pickers are trimmed. Camera crops use the native 2× capture directly and a single final downsample; the old shrink-then-enlarge path is removed. Cursor animation follows actual recorded click times.
