# TimingLens counter experiment

The 2:46 demo follows a standalone 32-bit FPGA counter from a failed 250 MHz build to a routed pass. At 2:26.7, an animated recap traces the late enable, splits the wide comparison into an upper-bit test and a four-bit comparison, and shows the validation and routed results. The final frame holds on the measured pass.

Both versions used the same 4 ns clock and Default recipe. The simulation compared 10,289 cycles. Worst setup slack improved from −0.633 ns to +0.407 ns, and the count of failing setup endpoints fell from 32 to zero. These are the results for the standalone core in run `counter32_250-20261118T193343Z-6fbe63d4`.

## Rebuild the edit

Extract the edit archive and run the following from its root using Python with Pillow and PyAV, FFmpeg and FFprobe, and the Lato and DejaVu fonts.

```sh
python media/demo-v12/render.py
python media/demo-v12/finalize.py
python media/demo-v12/verify.py
```

The archive contains the previous picture master, closing animation source, narration take, timed words, mixed stereo audio and engineering evidence. The verification script checks the decoded picture before the edit against the previous cut, compares the animated frames with the artwork, and checks the captions, audio and reported measurements. To remix in the original TimingLens checkout, run `mix.py` with NumPy, SciPy and SoundFile. It reads the retained premaster and music stem.
