# TimingLens counter IP walkthrough

The first frame shows the seven-port counter symbol exported by Vivado IP Integrator from the measured baseline SystemVerilog. The setup figures beside the block come from the routed 250 MHz standalone counter experiment. At 0:18, the next diagram connects the timing evidence and matching design files to TimingLens. The results block distinguishes the suggested change produced by analysis from the measured comparison produced by an experiment.

The two replacement scenes follow the existing Jarnathan narration. The finished MP4 contains the PUNK’D mix, English captions, chapters and routed comparison. The GUI walkthrough begins at frame 860. The core went from −0.633 ns to +0.407 ns worst setup slack, with 32 failing setup endpoints reduced to zero. Timing in the integrated design is still untested.

## Symbol provenance

The source for the displayed block is baseline/design.sv from counter32_250-20261118T193343Z-6fbe63d4. Its SHA-256 is e24003f3a011fa85a442d27dd7433e66cd8a23e83fe519ccf2e24ad7d8ba32ea. Vivado 2024.2 packaged that source in an isolated project for the opening graphic. The reset is synchronous and active high. The clock parameter is 250 MHz. Vivado's exported SVG supplies all pin geometry and text. The rasterization step applies the movie palette.

## Rebuild

Extract the edit ZIP and run the following commands from its root. The rendering scripts use Pillow, PyAV, FFmpeg, Lato and DejaVu Sans Mono. The archive includes the prior movie and the native symbol.

```sh
python media/demo-v9/render.py
python media/demo-v9/verify.py
```

To regenerate the Vivado SVG, run export_block.tcl in an empty temporary directory with the bundled baseline SystemVerilog as its Tcl argument. A graphical display or Xvfb is required for the layout export. rasterize_symbol.py uses librsvg via Python GI.

verification.json records the checked movie hash, pin count, audio packet comparison and decoded walkthrough frame comparison. The two PNG previews in the delivery folder were extracted from the finished MP4.
