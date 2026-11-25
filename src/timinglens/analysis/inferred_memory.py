"""Recognize a standalone, single-clock, read-first RAM with an optional Vivado mapping hint."""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re

ID = r"[A-Za-z_][A-Za-z0-9_$]*"
MODULE = re.compile(rf"\s*module\s+(?P<module>{ID})\s*\((?P<ports>[^;]+)\)\s*;\s*"
    rf'(?:\(\*\s*ram_style\s*=\s*"(?P<style>block|distributed|auto)"\s*\*\)\s*)?'
    rf"(?P<decl>reg|logic)\s*\[\s*(?P<msb>\d+)\s*:\s*0\s*\]\s*(?P<mem>{ID})\s*"
    rf"\[\s*0\s*:\s*(?P<last>\d+)\s*\]\s*;\s*"
    rf"always(?:_ff)?\s*@\s*\(\s*posedge\s+(?P<clk>{ID})\s*\)\s*begin\s*"
    rf"(?P<body>.+?)\s*end\s*endmodule\s*", re.S)
PORT = re.compile(rf"\s*(input|output)\s+(?:(?:wire|reg|logic)\s+)?(?:\[\s*(\d+)\s*:\s*0\s*\]\s*)?({ID})\s*")


@dataclass(frozen=True)
class Memory:
    file: str
    module: str
    style: str
    offset: int
    width: int
    depth: int
    ports: tuple[str, ...]  # clock, write enable, address, data in, data out
    line: int
    digest: str

    def mapped_source(self, text, style):
        if self.style:
            if text[self.offset:self.offset + len(self.style)] != self.style:
                raise ValueError("Memory declaration changed after source capture.")
            return text[:self.offset] + style + text[self.offset + len(self.style):]
        return text[:self.offset] + f'(* ram_style = "{style}" *) ' + text[self.offset:]


def recognize(source):
    if Path(source.path).suffix.lower() not in {".sv", ".v"} or not source.text:
        return None
    if sha256(source.text.encode()).hexdigest() != source.sha256:
        return None
    # Mask comments without moving any source offsets.
    text = re.sub(r"//[^\n]*|/\*.*?\*/", lambda m: " " * len(m[0]), source.text, flags=re.S)
    m = MODULE.fullmatch(text)
    if not m:
        return None
    declared = {}
    for fragment in m["ports"].split(","):
        p = PORT.fullmatch(fragment)
        if not p or p[3] in declared:
            return None
        declared[p[3]] = (p[1], int(p[2] or 0) + 1)
    mem = re.escape(m["mem"])
    body = re.fullmatch(rf"if\s*\(\s*({ID})\s*\)\s*{mem}\s*\[\s*({ID})\s*\]\s*<=\s*({ID})\s*;\s*"
                        rf"({ID})\s*<=\s*{mem}\s*\[\s*\2\s*\]\s*;", m["body"].strip())
    if not body:
        return None
    ports = (m["clk"], *body.groups())
    width, depth = int(m["msb"])+1, int(m["last"])+1
    if not (2 <= depth <= 4096 and depth & (depth-1) == 0 and 1 <= width <= 64 and len(set(ports)) == 5):
        return None
    expected = dict(zip(ports, (("input",1), ("input",1), ("input",(depth-1).bit_length()),
                                ("input",width), ("output",width))))
    if declared != expected:
        return None
    offset = m.start("style") if m["style"] else m.start("decl")
    return Memory(source.path, m["module"], m["style"] or "", offset, width, depth, ports,
                  1 + source.text.count("\n", 0, offset), source.sha256)
