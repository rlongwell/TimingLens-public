# Timing evidence fixtures

`zybo_dfx_path.json` is a reduced capture of one real routed Vivado 2024.2 path from the local `fpga-dfx-hash-accelerator` project (MIT license). It preserves the original broken arc extraction, native path pins, capped-net omission, timing text, and relevant source snapshots so import must recover the measured delays. Source paths were made relative, unrelated pins/cells were removed, and sinks were marked incomplete after reduction. The original checkpoint SHA-256 is recorded in `docs/validation.md`. The complete capture is retained in the hash project's local build evidence.

`ambiguous.json` is a synthetic fixture with no defensible source association.
