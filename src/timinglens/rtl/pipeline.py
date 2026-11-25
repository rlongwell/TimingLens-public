"""Schedule a restricted, straight-line unsigned datapath into its existing register budget."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import re

import pyslang as sv


class Unsupported(ValueError):
    """The source falls outside the leaf transformation's contract."""


def require(condition):
    if not condition:
        raise Unsupported()


def syntax_items(items):
    return (item for item in items if isinstance(item, sv.SyntaxNode))


IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
RANGE = r"(?:\[\s*([0-9]{1,3})\s*:\s*0\s*\])?"


def declared_name(item):
    require(not len(item.dimensions) and re.fullmatch(IDENT, item.name.rawText))
    return item.name.rawText


@dataclass(frozen=True)
class Expression:
    text: str
    # Each offset addresses an identifier token, excluding select bounds and literals.
    identifiers: tuple[tuple[int, str], ...]
    multiply_lines: tuple[int, ...]
    arithmetic: bool

    @property
    def dependencies(self):
        return tuple(dict.fromkeys(name for _, name in self.identifiers))

    def at(self, stage, names):
        value = self.text
        for offset, name in reversed(self.identifiers):
            value = value[:offset] + names[name, stage] + value[offset + len(name):]
        return value


def expression(node, text, widths):
    start = node.sourceRange.start.offset
    identifiers, multiply = [], []
    arithmetic = False

    def visit(part, depth=0):
        nonlocal arithmetic
        require(depth < 24)
        kind = part.kind.name
        if kind in {"IdentifierName", "IdentifierSelectName"}:
            name = part.identifier.rawText
            require(name in widths)
            if kind == "IdentifierSelectName":
                require(len(part.selectors) == 1)
                bounds = re.fullmatch(r"\[\s*(\d{1,3})(?:\s*:\s*(\d{1,3}))?\s*\]", str(part.selectors[0]).strip())
                require(bounds and 0 <= int(bounds[2] or bounds[1]) <= int(bounds[1]) < widths[name])
            identifiers.append((part.identifier.location.offset - start, name))
        elif kind in {"MultiplyExpression", "AddExpression", "SubtractExpression"}:
            arithmetic = True
            require(not len(part.attributes))
            if kind == "MultiplyExpression":
                multiply.append(text.count("\n", 0, part.operatorToken.location.offset) + 1)
            visit(part.left, depth + 1)
            visit(part.right, depth + 1)
        elif kind == "ConcatenationExpression":
            for child in syntax_items(part.expressions):
                visit(child, depth + 1)
        elif kind == "ParenthesizedExpression":
            visit(part.expression, depth + 1)
        else:
            require(kind == "IntegerVectorExpression" and
                    re.fullmatch(r"[1-9]\d{0,2}'[bBoOdDhH][0-9a-fA-F_]+", str(part).strip()))
    visit(node)
    require(identifiers)
    return Expression(text[start:node.sourceRange.end.offset], tuple(identifiers), tuple(multiply), arithmetic)


@dataclass(frozen=True)
class Pipeline:
    module: str
    clock: str
    output: str
    inputs: tuple[tuple[str, int], ...]
    output_width: int
    stages: int
    start: int
    end: int
    body: str
    schedule: tuple[str, ...]
    multiply_lines: tuple[int, ...]


def _interface(header):
    widths, inputs, outputs = {}, [], []
    direction = None
    for port in syntax_items(header.ports.ports):
        require(port.kind.name == "ImplicitAnsiPort" and not len(port.attributes) and not port.declarator.initializer)
        name = declared_name(port.declarator)
        spec = str(port.header).strip()
        if spec:
            match = re.fullmatch(r"(input|output)\s*(?:(wire|reg|logic)\s*)?" + RANGE, spec)
            require(match and (match[1] == "input" or match[2] in {"reg", "logic"}))
            direction, width = match[1], int(match[3] or 0) + 1
        require(direction and name not in widths)
        widths[name] = width
        (inputs if direction == "input" else outputs).append(name)
    require(len(outputs) == 1 and len(inputs) <= 32)
    return widths, inputs, outputs[0]


def _declarations(members, widths):
    drivers, variables, nets, blocks = {}, set(), set(), []
    for member in members:
        kind = member.kind.name
        require(not len(getattr(member, "attributes", ())))
        if kind in {"AlwaysBlock", "AlwaysFFBlock"}:
            blocks.append(member.statement)
            continue
        if kind == "ContinuousAssign":
            require(not member.delay and not member.strength)
            for assign in syntax_items(member.assignments):
                require(assign.kind.name == "AssignmentExpression" and assign.left.kind.name == "IdentifierName")
                name = assign.left.identifier.rawText
                require(name not in drivers)
                drivers[name] = assign.right
            continue
        require(kind in {"NetDeclaration", "DataDeclaration"})
        if kind == "NetDeclaration":
            require(member.netType.rawText == "wire" and not member.delay and not member.strength)
            match = re.fullmatch(r"(?:logic\s*)?" + RANGE, str(member.type).strip())
        else:
            require(not len(member.modifiers))
            match = re.fullmatch(r"(?:reg|logic)\s*" + RANGE, str(member.type).strip())
        require(match)
        for d in syntax_items(member.declarators):
            name = declared_name(d)
            require(name not in widths)
            if kind == "NetDeclaration":
                nets.add(name)
                if d.initializer:
                    require(name not in drivers)
                    drivers[name] = d.initializer.expr
            else:
                require(not d.initializer)
                variables.add(name)
            widths[name] = int(match[1] or 0) + 1

    require(nets <= drivers.keys() <= nets | variables)
    registers = variables - drivers.keys()
    require(len(blocks) == 1 and len(drivers) <= 32 and 1 <= len(registers) <= 15)
    return drivers, registers, blocks[0]


def _register_chain(block, widths, inputs, registers, output):
    require(block.kind.name == "TimingControlStatement" and not block.label and not len(block.attributes))
    control = re.fullmatch(r"@\s*\(\s*posedge\s+(" + IDENT + r")\s*\)", str(block.timingControl).strip())
    require(control and control[1] in inputs and widths[control[1]] == 1)
    clock = control[1]
    body = block.statement
    require(body.kind.name == "SequentialBlockStatement" and not body.blockName and not body.label and not len(body.attributes))
    assignments = {}
    for item in body.items:
        require(item.kind.name == "ExpressionStatement" and not item.label and not len(item.attributes))
        assign = item.expr
        require(assign.kind.name == "NonblockingAssignmentExpression" and not len(assign.attributes)
                and assign.left.kind.name == "IdentifierName")
        name = assign.left.identifier.rawText
        require(name in registers | {output} and name not in assignments)
        assignments[name] = assign.right
    require(set(assignments) == registers | {output})
    # Trace from the output, so declaration and statement order need not match dataflow.
    chain, name = [], output
    while name in assignments:
        require(name not in chain and widths[name] == widths[output])
        chain.append(name)
        rhs = assignments[name]
        if rhs.kind.name != "IdentifierName" or rhs.identifier.rawText not in registers:
            break
        name = rhs.identifier.rawText
    require(set(chain) == set(assignments))
    return clock, len(chain), rhs


def _schedule(pending, inputs, output, clock, stages):
    # Visit only the output cone, rejecting feedback, extra state and unused drivers.
    depths = {key: 0 for key in inputs if key != clock}
    expressions = {}

    def schedule(key, visiting):
        if key in depths:
            return depths[key]
        require(key in pending and key not in visiting)
        expr = pending[key]
        depths[key] = 1 + max(schedule(dep, visiting | {key}) for dep in expr.dependencies)
        expressions[key] = expr
        return depths[key]

    schedule(output, set())
    require(len(expressions) == len(pending))
    # Spend one existing cycle on input capture when the depth budget allows it.
    require(2 <= depths[output] <= stages)
    require(len({depths[key] for key, expr in expressions.items() if expr.arithmetic}) >= 2)
    capture = int(depths[output] < stages)
    computed = {key: depth + capture for key, depth in depths.items() if key in expressions}
    needed = {key: 0 for key in depths}
    for key, expr in expressions.items():
        for dep in expr.dependencies:
            needed[dep] = max(needed[dep], computed[key] - 1)
    needed[output] = stages
    return expressions, computed, needed


def _emit(module, widths, output, clock, stages, expressions, computed, needed, notes):
    names, declarations = {}, []
    occupied = set(widths) | {module}
    per_stage = [[] for _ in range(stages + 1)]
    for key in needed:
        first = computed.get(key, 0)
        for stage in range(first, max(first, needed[key]) + 1):
            if stage == 0:
                names[key, 0] = key
                continue
            if key == output and stage == stages:
                dest = output
            else:
                dest = f"{key}_s{stage}"
                while dest in occupied:
                    dest += "_"
                occupied.add(dest)
                size = f" [{widths[key]-1}:0]" if widths[key] > 1 else ""
                declarations.append(f"    reg{size} {dest};")
            names[key, stage] = dest
            rhs_text = (expressions[key].at(stage - 1, names) if key in expressions and first == stage
                        else names[key, stage - 1])
            per_stage[stage].append(f"        {dest} <= {rhs_text};")
    lines = ["", *notes, *declarations, "", f"    always @(posedge {clock}) begin"]
    for stage in range(1, stages + 1):
        lines.extend(per_stage[stage])
        if stage < stages:
            lines.append("")
    lines.extend(["    end", ""])
    steps = []
    for stage in range(1, stages + 1):
        operations = [f"{key} = {expressions[key].text}" for key in computed if computed[key] == stage]
        action = ", ".join(operations) or ("register inputs" if stage == 1 else "register aligned data")
        steps.append(f"Cycle {stage}: {action}.")
    return "\n".join(lines), tuple(steps)


# Strip only lexical trivia in the parser copy. Offsets and line numbers must agree
# with the source snapshot because Vivado tags identify expressions by source line.
COMMENTS = re.compile(r'//[^\n\r]*|/\*[\s\S]*?\*/')
DIRECTIVES = re.compile(r"^[ \t]*`(?:timescale\s+\d+\s*(?:s|ms|us|ns|ps|fs)\s*/\s*\d+\s*(?:s|ms|us|ns|ps|fs)|default_nettype\s+(?:wire|none))[ \t]*$", re.M)
TOOL_HINT = re.compile(r"translate_(?:off|on)|\b(?:synthesis|synopsys|synplify|verilator|yosys|pragma|full_case|parallel_case)\b|\bsyn_\w+", re.I)


def _mask(match):
    return re.sub(r"[^\r\n]", " ", match[0])


def parse_pipeline(text):
    require(len(text) <= 32768 and text.isascii())
    comments = list(COMMENTS.finditer(text))
    require(all(not TOOL_HINT.search(c[0]) for c in comments))
    clean = COMMENTS.sub(_mask, text)
    directives = list(DIRECTIVES.finditer(clean))
    clean = DIRECTIVES.sub(_mask, clean)
    require("`" not in clean and "(*" not in clean and '"' not in clean)
    tree = sv.SyntaxTree.fromText(clean)
    module = tree.root
    require(not len(tree.diagnostics) and module.kind.name == "ModuleDeclaration")
    header = module.header
    require(header.moduleKeyword.rawText == "module" and not header.parameters and not len(header.imports)
            and header.ports and header.ports.kind.name == "AnsiPortList")
    name = header.name.rawText
    require(re.fullmatch(IDENT, name))
    start, end = header.semi.range.end.offset, module.endmodule.location.offset
    require(all(d.end() <= header.moduleKeyword.location.offset or d.start() >= module.endmodule.range.end.offset
                for d in directives))
    widths, inputs, output = _interface(header)
    drivers, registers, block = _declarations(module.members, widths)
    clock, stages, first_value = _register_chain(block, widths, inputs, registers, output)
    drivers[output] = first_value
    pending = {key: expression(expr, clean, widths) for key, expr in drivers.items()}
    expressions, computed, needed = _schedule(pending, inputs, output, clock, stages)
    notes = ["    " + c[0] for c in comments if start <= c.start() < end]
    body, steps = _emit(name, widths, output, clock, stages, expressions, computed, needed, notes)
    if "\r\n" in text and "\n" not in text.replace("\r\n", ""):
        body = body.replace("\r\n", "\n").replace("\n", "\r\n")
    return Pipeline(name, clock, output, tuple((key, widths[key]) for key in inputs), widths[output],
                    stages, start, end, body, steps,
                    tuple(line for expr in expressions.values() for line in expr.multiply_lines))


@lru_cache(maxsize=32)
def pipeline(text):
    try:
        return parse_pipeline(text)
    except Unsupported:
        return None
