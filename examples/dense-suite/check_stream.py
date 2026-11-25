"""Exercise every lane of a routed benchmark's source project in native XSim."""
from argparse import ArgumentParser
from pathlib import Path
import re
import subprocess

from timinglens.experiments.auto_project import Project
from timinglens.vivado.runner import discover


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    layout = Project.read(args.project)
    name = layout.xpr.stem
    if name not in {"iq_power", "tone_curve", "pixel_gain"}:
        parser.error("Choose a dense-suite example.")
    args.output.mkdir(parents=True,exist_ok=False)
    vivado = discover()
    sources = [layout.xpr.parent/f for f in layout.files if f.suffix == ".v"]
    libraries = ["-L","unisims_ver"]
    commands = []
    if name == "pixel_gain":
        generated = layout.xpr.with_suffix(".gen")
        wrapper, = generated.glob("**/gain_tile_gain_product_0/sim/*.vhd")
        library, = re.findall(r"^LIBRARY (mult_gen_v[0-9_]+);",wrapper.read_text(),re.I|re.M)
        libraries.extend(["-L",library])
        commands.append(["xvhdl","--work","xil_defaultlib",wrapper])
        netlist, = generated.glob("**/gain_tile/sim/gain_tile.v")
        sources.append(netlist)
    tb = Path(__file__).with_name("check_stream.sv").resolve()
    glbl = vivado.resolve().parents[1]/"data/verilog/src/glbl.v"
    commands.extend([["xvlog","--sv","--work","xil_defaultlib","-d",name.upper(),*sources,tb,glbl],
        ["xelab","--mt","2","--timescale","1ns/1ps",*libraries,"xil_defaultlib.glbl","xil_defaultlib.check_stream","-s","stream_check"],
        ["xsim","stream_check","-runall"]])
    for tool,*arguments in commands:
        log = args.output/(tool+"-output.log")
        with log.open("w") as stream:
            subprocess.run([vivado.parent/tool,*arguments],cwd=args.output,stdout=stream,stderr=subprocess.STDOUT,check=True)
    passed = next((line for line in log.read_text().splitlines() if line.startswith("TIMINGLENS_STREAM_PASS ")),None)
    if not passed:
        raise SystemExit(f"No passing scoreboard in {log}")
    print(passed)


if __name__ == "__main__":
    main()
