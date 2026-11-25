"""Parse SystemVerilog and Verilog with slang's lossless syntax tree."""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
import re

import pyslang as slang

from ..timing.models import Source


@dataclass(frozen=True)
class Construct:
    kind: str
    first: int
    last: int
    signals: tuple[str, ...]


@dataclass(frozen=True)
class Guard:
    first: int
    last: int
    branch: str
    text: str
    signals: tuple[str, ...]


@dataclass(frozen=True)
class RegisterUpdate:
    signal: str
    first: int
    last: int
    guards: tuple[Guard, ...]


@dataclass(frozen=True)
class Declaration:
    signal: str
    first: int
    width: int | None


@dataclass(frozen=True)
class Module:
    name: str
    file: str
    first: int
    last: int
    instances: tuple[tuple[str, str], ...]
    constructs: tuple[Construct, ...]
    declarations: tuple[Declaration, ...] = ()
    updates: tuple[RegisterUpdate, ...] = ()


@dataclass
class SourceIndex:
    modules: dict[str, list[Module]] = field(default_factory=dict)
    files: dict[str, list[Module]] = field(default_factory=dict)
    texts: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def source_text(source: Source, trust_manifest_paths: bool = False) -> str | None:
    if source.text is not None:
        return source.text
    if trust_manifest_paths and source.sha256:
        try:
            path = Path(source.path)
            if not path.is_file():
                return None
            with path.open('rb') as stream:
                data = stream.read(4_000_001)
            if len(data) > 4_000_000:
                return None
        except OSError:
            return None
        if sha256(data).hexdigest() == source.sha256:
            return data.decode("utf-8", errors="replace")
    return None


def _base(node: slang.SyntaxNode) -> str:
    if isinstance(node, (slang.IdentifierNameSyntax, slang.IdentifierSelectNameSyntax)):
        return node.identifier.valueText
    return ""


def _signals(node: slang.SyntaxNode) -> tuple[str, ...]:
    names = set()

    def visit(member):
        if name := _base(member):
            names.add(name)

    node.visit(visit)
    return tuple(sorted(names))


def _selection(node: slang.SyntaxNode) -> bool:
    if not isinstance(node, slang.BinaryExpressionSyntax) or node.kind != slang.SyntaxKind.AssignmentExpression:
        return False
    target, rhs = node.left, node.right
    if not isinstance(rhs, slang.ConditionalExpressionSyntax):
        return False
    # A next-element assignment that falls back to the previous selected value
    # encodes priority. A stand-alone ternary or an exclusive case does not.
    if isinstance(rhs.right, slang.ConditionalExpressionSyntax):
        return True
    return (
        isinstance(target, slang.IdentifierSelectNameSyntax)
        and isinstance(rhs.right, slang.IdentifierSelectNameSyntax)
        and _base(target) == _base(rhs.right)
        and not target.isEquivalentTo(rhs.right)
        and isinstance(node.parent, slang.ContinuousAssignSyntax)
    )



def _assignment_target(statement):
    if not isinstance(statement, slang.ExpressionStatementSyntax):
        return None
    expr = statement.expr
    if not isinstance(expr, slang.BinaryExpressionSyntax) or expr.kind not in {
        slang.SyntaxKind.AssignmentExpression, slang.SyntaxKind.NonblockingAssignmentExpression
    }:
        return None
    return expr.left


def _priority_if(statement) -> bool:
    if not isinstance(statement, slang.ConditionalStatementSyntax):
        return False
    if not statement.elseClause or not isinstance(statement.elseClause.clause, slang.ConditionalStatementSyntax):
        return False
    target = _assignment_target(statement.statement)
    if target is None:
        return False
    current = statement
    while isinstance(current, slang.ConditionalStatementSyntax):
        flavor = current.uniqueOrPriority.rawText
        branch = _assignment_target(current.statement)
        if flavor in {"unique", "unique0"} or branch is None or not target.isEquivalentTo(branch):
            return False
        if not current.elseClause:
            return False
        current = current.elseClause.clause
    fallback = _assignment_target(current)
    return fallback is not None and target.isEquivalentTo(fallback)


def _module(node, tree, file: str) -> Module:
    manager = tree.sourceManager
    instances = []
    constructs = []
    declarations = []
    updates = []

    def lines(member):
        bounds = member.sourceRange
        if bounds.start.buffer != node.sourceRange.start.buffer:
            return None
        return manager.getLineNumber(bounds.start), manager.getLineNumber(bounds.end)

    def visit(member):
        if isinstance(member, slang.DataDeclarationSyntax) and (span := lines(member)):
            # Only literal packed widths are known without elaboration. Do not
            # pretend to resolve parameterized dimensions or typedefs.
            packed = str(member.type).strip()
            match = re.fullmatch(r"(?:logic|reg|bit)(?:\s+(?:signed|unsigned))?\s*\[\s*(\d+)\s*:\s*(\d+)\s*\]", packed)
            width = abs(int(match[1]) - int(match[2])) + 1 if match else (1 if packed in {"logic", "reg", "bit"} else None)
            for decl in member.declarators:
                if isinstance(decl, slang.DeclaratorSyntax):
                    declarations.append(Declaration(decl.name.valueText, span[0], width))
        if (isinstance(member, slang.BinaryExpressionSyntax)
                and member.kind == slang.SyntaxKind.NonblockingAssignmentExpression
                and (signal := _base(member.left)) and (span := lines(member))):
            guards = []
            child, parent = member, member.parent
            while parent is not None and parent is not node:
                if isinstance(parent, slang.ConditionalStatementSyntax) and (bounds := lines(parent.predicate)):
                    branch = "else" if isinstance(child, slang.ElseClauseSyntax) else "then"
                    guards.append(Guard(*bounds, branch, str(parent.predicate).strip(), _signals(parent.predicate)))
                child, parent = parent, parent.parent
            updates.append(RegisterUpdate(signal, *span, tuple(guards)))
        if isinstance(member, slang.HierarchyInstantiationSyntax):
            for instance in member.instances:
                if isinstance(instance, slang.HierarchicalInstanceSyntax) and instance.decl:
                    instances.append((instance.decl.name.valueText, member.type.valueText))
        kind = None
        if _selection(member) or _priority_if(member):
            kind = "priority selection candidate"
        elif isinstance(member, slang.ConditionalExpressionSyntax):
            kind = "conditional expression"
        elif isinstance(member, slang.BinaryExpressionSyntax) and member.kind != slang.SyntaxKind.NonblockingAssignmentExpression:
            op = member.operatorToken.rawText
            kind = {"+": "addition", "-": "subtraction", "*": "multiplication",
                    "<": "comparison", ">": "comparison", "<=": "comparison", ">=": "comparison",
                    "==": "comparison", "!=": "comparison"}.get(op)
        if kind and (span := lines(member)):
            constructs.append(Construct(kind, *span, _signals(member)))

    node.visit(visit)
    first, last = lines(node)
    return Module(node.header.name.valueText, file, first, last, tuple(instances), tuple(constructs),
                  tuple(declarations), tuple(updates))


def build_index(sources: list[Source], trust_manifest_paths: bool = False) -> SourceIndex:
    result = SourceIndex()
    options = slang.Bag()
    preprocessing = slang.PreprocessorOptions()
    # Compile captured files without following ambient filesystem include directives.
    preprocessing.maxIncludeDepth = 0
    options.preprocessorOptions = preprocessing
    parsed_bytes = 0
    for source in sources:
        text = source_text(source, trust_manifest_paths)
        if text is None:
            continue
        result.texts[source.path] = text
        if source.sha256 and sha256(text.encode()).hexdigest() != source.sha256:
            result.warnings.append(f"{source.path}: source bytes conflict with the captured hash; syntax attribution suppressed.")
            continue
        if Path(source.path).suffix.lower() not in {".sv", ".v"}:
            continue
        size = len(text.encode())
        if size > 256_000 or parsed_bytes + size > 2_000_000:
            result.warnings.append(f"{source.path}: syntax budget exceeded (256 KB per file / 2 MB total); text retained as context only.")
            continue
        parsed_bytes += size
        try:
            tree = slang.SyntaxTree.fromText(text, slang.SourceManager(), name=source.path, options=options)
            if tree.diagnostics:
                result.warnings.append(f"{source.path}: slang reported {len(tree.diagnostics)} parse diagnostics.")
            def visit(node):
                if not isinstance(node, slang.ModuleDeclarationSyntax) or node.kind != slang.SyntaxKind.ModuleDeclaration:
                    return
                module = _module(node, tree, source.path)
                if module.name:
                    result.modules.setdefault(module.name, []).append(module)
                    result.files.setdefault(module.file, []).append(module)
            tree.root.visit(visit)
        except (RuntimeError, ValueError) as error:
            result.warnings.append(f"{source.path}: source index unavailable ({error}).")
    return result
