# TimingLens · Closing timing on a 250 MHz counter

This 106.5-second cut follows the guided counter from a failed routed path to a measured standalone timing pass. The original and proposed RTL expressions stay side by side. Two binary examples show how the split comparison works. The recorded GUI keeps one framing throughout. The accelerated run shows the live stage indicator at 2× during validation and approximately 30× during implementation.

## Recorded evidence

The 32-bit unsigned counter and 4-bit subtraction amount are from TimingLens’s counter32_250 job, counter32_250-20261117T092729Z-b24fadcc. The first routed setup path launches from remaining_reg[0], crosses a LUT4, four CARRY4 cells and a LUT3, and ends on remaining_reg[3]/CE. The routed report gives 4.720 ns required and 5.353 ns arrival. The 0.633 ns difference includes the timing checks on that path.

The rewrite accepts a request when any bit of remaining[31:4] is set or the low nibble covers the amount. The original acceptance, reset, load and subtraction logic keep their cycle behavior. The isolated finite test checked both versions against the reference model over 10,289 cycles. Vivado 2024.2 routed both versions on xc7z020clg400-1 with the same 4.000 ns clock, interface budgets and Default recipe.

The full out-of-context setup summary went from −0.633 ns to +0.407 ns WNS and from 32 to 0 failing endpoints. Physical LUTs went from 50 to 41. Full-system integration remains to be checked. The evidence folder contains the first routed path, the RTL diff, the original constraints and both design timing and utilization summaries.

## Reproduce the cut

Extract the edit-source ZIP retaining its directory structure. The edit uses Python 3.12 with Pillow and PyAV, FFmpeg with libx264, Lato and DejaVu Sans Mono. See requirements.txt for the original media environment. The compact prepared footage and the reviewed AAC mix are in work/demo-video-v6. From the extracted root, run these commands in order.

```sh
python media/demo-v6/edit.py
python media/demo-v6/finalize.py
python media/demo-v6/verify.py
```

The finished MP4 includes seven chapters and optional English captions. Its source takes, typography, framing, scene times, clicks and build speed are specified in the edit scripts. The prepared selects are cropped once from the 3840 × 2086 v5 GUI recording. To retrim them, provide the v5 recording at work/demo-video-v5/capture/gui-source.mkv and run prepare_capture.py. Build output in the recording is from the existing measured job.

The new narration uses the established ElevenLabs Jarnathan voice, Eleven v4, stability 0.62, similarity 0.75 and clone strength 0. The music is the user's PUNK’D recording by Out of Flux. To remix the music, supply that original MP3 at work/demo-video-v3/audio/Out of Flux - PUNKD.mp3 and run mix.py before finalize.py. The supplied mix is sufficient for the standard render.

The final video was decoded frame by frame. The encoded review checked the transitions into the runner and Lab, the placement of both action pointers, and the alignment of the displayed examples and measurements. The speech checks used word-timed transcripts of the original take and encoded mix. verification.json records measured audio levels and duration.
