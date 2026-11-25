import sys
from pathlib import Path

from .vivado.runner import Request, VivadoError

TOPS = {"deep": "deep", "priority": "priority_top", "fanout": "fanout", "clean": "clean"}


def example_path() -> Path:
    candidates = (Path(__file__).resolve().parents[2] / "examples",
                  Path(sys.prefix) / "share" / "timinglens" / "examples")
    for candidate in candidates:
        if (candidate / "deep" / "design.sv").is_file():
            return candidate
    raise VivadoError("Bundled TimingLens examples could not be located")


def request_for(name: str, output: Path, **kwargs) -> Request:
    root = example_path() / name
    return Request("demo", root / "design.sv", output, top=TOPS[name],
                   xdc=root / "timing.xdc", **kwargs)
