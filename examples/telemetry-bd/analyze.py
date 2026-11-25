"""Run the installed TimingLens CLI with the sources used to generate this BD."""
import argparse
import json
from pathlib import Path
import subprocess
import sys


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("build", type=Path)
    cli.add_argument("output", type=Path)
    cli.add_argument("--max-paths", type=int, default=100)
    args = cli.parse_args()
    build = args.build.resolve()
    src = Path(__file__).resolve().parent
    bd = build / "telemetry_fabric.bd"
    generated = build / "project/telemetry.gen/sources_1/bd/telemetry_fabric"
    inputs = [src / "telemetry.v", src / "timing.xdc", src / "build.tcl", bd,
              generated / "hdl/telemetry_fabric_wrapper.v", generated / "synth/telemetry_fabric.v"]
    components = json.loads(bd.read_text())["design"]["components"]
    for item in components.values():
        if "reference_info" in item:
            wrapper = item["xci_name"]
            inputs.append(generated / "ip" / wrapper / "synth" / (wrapper + ".v"))
    cmd = [sys.executable, "-m", "timinglens", "analyze", "--checkpoint", str(build / "routed.dcp"),
           "--max-paths", str(args.max_paths), "--paths-per-endpoint", "1", "--output", str(args.output)]
    for path in inputs:
        cmd.extend(("--file", str(path)))
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
