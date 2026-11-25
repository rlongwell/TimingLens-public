"""Collect one whole-design TimingLens session from the frozen build directory."""
import argparse
from pathlib import Path
import subprocess
import sys


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("build", type=Path)
    cli.add_argument("output", type=Path)
    cli.add_argument("--stage", choices=("synthesized", "routed"), default="routed")
    cli.add_argument("--paths", type=int, default=100)
    args = cli.parse_args()
    root = args.build.resolve()
    checkpoint = root / (args.stage + ".dcp")
    generated = root / "project/dense.gen/sources_1/bd/monitor"
    sources = [root / "src" / f for f in ("calibration.v", "fabric.v", "timing.xdc", "build.tcl")]
    sources.extend((root / "monitor.bd", generated / "hdl/monitor_wrapper.v", generated / "synth/monitor.v"))
    for folder in sorted((generated / "ip").glob("monitor_bank_*")):
        sources.append(folder / "synth" / (folder.name + ".v"))
    sources.append(generated / "ip/monitor_readout_0/synth/monitor_readout_0.v")
    cmd = [sys.executable, "-m", "timinglens", "analyze", "--checkpoint", str(checkpoint),
           "--max-paths", str(args.paths), "--paths-per-endpoint", "1", "--output", str(args.output)]
    for file in sources:
        cmd.extend(("--file", str(file)))
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
