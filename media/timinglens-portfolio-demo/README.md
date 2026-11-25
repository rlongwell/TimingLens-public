# TimingLens demo

[Watch the 1:50 film](timinglens-demo.mp4)

The source is the [counter experiment film](../demo-v12/README.md). The 1.040 ns gain is the change in worst setup slack on the standalone counter. Both runs used the same 4 ns constraint and Default recipe. This cut uses the recorded application, Jarnathan narration and the PUNK’D soundtrack by Out of Flux from the earlier edit.

## On-screen script

| Time | Scene | Overlay |
| --- | --- | --- |
| 0:00 | TimingLens | Closing timing at 250 MHz. Follow a late counter enable from the Vivado path report to a verified RTL edit. |
| 0:05 | Baseline | The original counter misses its setup deadline. −0.633 ns |
| 0:09 | Triage | Start with a failing endpoint and inspect its register enable. 32 failing endpoints |
| 0:23 | Timing path | Four carry blocks sit on the path to the counter enable. Vivado routed path |
| 0:38 | RTL change | Split the wide guard into a high-bit test and a low-bit comparison. |
| 0:56 | Functional check | Compare each implementation against the same counter model. 10,289 cycles |
| 1:06 | Matched experiment | Route both versions with the same constraints and recipe. 4 ns clock |
| 1:17 | Routed result | Worst setup slack improves by 1.040 ns. 32 → 0 failing endpoints |
| 1:39 | Reviewable evidence | Export the patch, run records and measured timing together. HTML comparison |

## Evidence and reproduction

- [README.md](../demo-v12/README.md)
- [experiment-lab.md](../../docs/experiment-lab.md)

[Verification](verification.json) records the exported file hash, frame count, full decode and source-audio alignment. The source picture and sound are from the recorded project. Titles, overlays and editing were AI-assisted.
