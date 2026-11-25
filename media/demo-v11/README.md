# TimingLens counter timing walkthrough

The 2 minute 33.5 second film opens with the counter's native Vivado block. From 0:09 to 0:22, the animation follows a changing signal through the comparison logic and its routing to the register enable. The lower waveform shows the enable change arriving after the required setup time. The clock and enable use the same capture-clock reference as the routed report.

For the baseline path P00001, Vivado reports a required arrival of 4.720 ns, a destination clock edge at 4.924 ns and an actual data arrival of 5.353 ns. The setup miss is 0.633 ns. The animation slows down the transition for illustration. It uses the report's timing relationships and the four CARRY4 elements on the data path.

The input diagram, actual experiment, and passing standalone result follow. At the experiment button, the narration says “Choose Review counter experiment.” The closing card shows the result and the remaining integration check.

## Reproduce the cut

Extract the edit archive preserving its directory layout. With FFmpeg, Pillow, PyAV, Lato and DejaVu Sans Mono installed, run these commands from the extracted root.

```sh
python media/demo-v11/render.py
python media/demo-v11/finalize.py
python media/demo-v11/verify.py
```

The archive includes the prior picture, the new spoken take, timed words, checked audio mix, ready-to-use counter block, render sources and verification evidence. mix.py can rebuild the mix in the original TimingLens checkout using its retained narration and music stems. verification.json records the encoded media checks. The engineering evidence comes from counter32_250-20261118T193343Z-6fbe63d4. The 3,436 GUI walkthrough frames match the earlier cut pixel for pixel.
