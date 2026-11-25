from pathlib import Path
import shutil
import subprocess

import pytest

from timinglens.demo import TOPS


@pytest.mark.parametrize("design", TOPS)
def test_example_testbench(design, tmp_path):
    simulator = shutil.which("verilator")
    if not simulator:
        pytest.skip("Verilator unavailable")
    example = Path(__file__).resolve().parents[2] / "examples" / design
    result = subprocess.run(
        [simulator, "--binary", "--timing", "-Wno-UNOPTFLAT", "-j", "2", "--top-module", "tb",
         "--Mdir", str(tmp_path / "obj"), str(example / "design.sv"), str(example / "tb.sv")],
        cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stdout
    sim = subprocess.run([str(tmp_path / "obj" / "Vtb")], cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert sim.returncode == 0, sim.stdout + sim.stderr
    assert "Verilog $finish" in sim.stdout
