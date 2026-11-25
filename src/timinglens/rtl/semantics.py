"""Small, source-located semantic model for clocked register controls."""
from dataclasses import dataclass
from pathlib import Path

import pyslang as slang


@dataclass(frozen=True)
class Span:
    file: str
    start: int  # UTF-8 byte offset, end exclusive
    end: int
    first: int
    last: int
    text: str


@dataclass(frozen=True)
class ValueType:
    width: int
    signed: bool
    four_state: bool
    zero_based_vector: bool


@dataclass(frozen=True)
class Comparison:
    span: Span
    operator: str
    operand_type: ValueType
    left: str
    right: str
    dependencies: tuple[str, ...]
    wide: str | None = None
    narrow: str | None = None
    narrow_width: int | None = None
    unknowns_possible: bool = True


@dataclass(frozen=True)
class Decision:
    kind: str
    branch: str
    span: Span
    dependencies: tuple[str, ...]
    comparisons: tuple[Comparison, ...]
    opposite_writes_target: bool


@dataclass(frozen=True)
class Update:
    span: Span
    clock: str | None
    edge: str | None
    constant: bool
    dependencies: tuple[str, ...]
    decisions: tuple[Decision, ...]


@dataclass(frozen=True)
class Register:
    instance: str
    signal: str
    type: ValueType
    elaboration: str
    updates: tuple[Update, ...]
    parameterized: bool = False

    @property
    def enable_decisions(self):
        """A missing opposite write means hold; a reset/data mux is not an enable."""
        decisions = {}
        for update in self.updates:
            if update.constant or not update.clock:
                continue
            for decision in update.decisions:
                if decision.comparisons and not decision.opposite_writes_target:
                    decisions[decision.span.start, decision.branch] = decision
        return tuple(decisions.values())


_OPERATORS = {
    slang.BinaryOperator.GreaterThan: ">",
    slang.BinaryOperator.GreaterThanEqual: ">=",
    slang.BinaryOperator.LessThan: "<",
    slang.BinaryOperator.LessThanEqual: "<=",
    slang.BinaryOperator.Equality: "==",
    slang.BinaryOperator.Inequality: "!=",
}
_REVERSED = {">": "<", ">=": "<=", "<": ">", "<=": ">=", "==": "==", "!=": "!="}
_MAX_PROJECT_BYTES = 2_000_000
_MAX_MODULE_BYTES = 256_000


def _type(expr):
    t = expr.type.canonicalType
    vector = (t.isPackedArray and t.elementType.isScalar
              and t.fixedRange.left == t.bitWidth - 1 and t.fixedRange.right == 0)
    return ValueType(t.bitWidth, t.isSigned, t.isFourState, vector)


def _references(expr):
    names = set()

    def visit(node):
        if isinstance(node, slang.NamedValueExpression):
            names.add(node.symbol.hierarchicalPath)

    expr.visit(visit)
    return tuple(sorted(names))


def _direct_value(expr):
    if isinstance(expr, slang.NamedValueExpression):
        return expr.symbol
    if isinstance(expr, (slang.ElementSelectExpression, slang.RangeSelectExpression)):
        return _direct_value(expr.value)
    return None


def _writes(statement, target):
    if statement is None:
        return False
    found = False

    def visit(node):
        nonlocal found
        if isinstance(node, slang.AssignmentExpression) and _direct_value(node.left) == target:
            found = True
            return slang.VisitAction.Interrupt

    statement.visit(visit)
    return found


def _narrow_operand(expr):
    """Recognize unsigned named values with a proven zero extension."""
    if isinstance(expr, slang.ConversionExpression) and expr.isImplicit:
        if isinstance(expr.operand, slang.NamedValueExpression) and not _type(expr.operand).signed:
            return expr.operand
    if isinstance(expr, slang.ConcatenationExpression) and len(expr.operands) == 2:
        upper, lower = expr.operands
        if (isinstance(upper, slang.IntegerLiteral) and not upper.value.hasUnknown
                and upper.value.countOnes() == 0 and isinstance(lower, slang.NamedValueExpression)
                and not _type(lower).signed):
            return lower
    return None


class _Compilation:
    def __init__(self, texts, top):
        options = slang.CompilationOptions()
        options.topModules = {top}
        options.errorLimit = 20
        options.maxInstanceDepth = 48
        options.maxInstanceArray = 2048
        options.maxGenerateSteps = 4096
        options.maxConstexprSteps = 10_000
        options.maxDefParamSteps = 16
        bag = slang.Bag()
        bag.compilationOptions = options
        preprocessing = slang.PreprocessorOptions()
        preprocessing.maxIncludeDepth = 0
        bag.preprocessorOptions = preprocessing
        self.manager = slang.SourceManager()
        self.compilation = slang.Compilation(bag)
        self.buffers = {}
        for i, (file, data) in enumerate(texts.items()):
            buffer = self.manager.assignText(f"timinglens_buffer_{i}", data.decode())
            self.buffers[buffer.id] = file, data
            self.compilation.addSyntaxTree(slang.SyntaxTree.fromBuffer(buffer, self.manager, bag))
        self.root = self.compilation.getRoot()
        self.complete = not any(d.isError() for d in self.compilation.getAllDiagnostics())

    def span(self, expr):
        start, end = expr.sourceRange.start, expr.sourceRange.end
        entry = self.buffers.get(start.buffer)
        if not entry or end.buffer != start.buffer:
            return None  # includes, macro expansions and synthetic nodes
        file, data = entry
        if not 0 <= start.offset < end.offset <= len(data):
            return None
        raw = data[start.offset:end.offset]
        line = data.count(b"\n", 0, start.offset) + 1
        return Span(file, start.offset, end.offset, line, line + raw.rstrip(b"\n").count(b"\n"), raw.decode())

    def instances(self, expected):
        matches = []

        def visit(node):
            if isinstance(node, slang.InstanceSymbol) and node.isModule:
                scope = node.hierarchicalPath
                if scope == expected:
                    matches.append(node)
                    return slang.VisitAction.Skip
                if not expected.startswith(scope + "."):
                    return slang.VisitAction.Skip
            if isinstance(node, (slang.ProceduralBlockSymbol, slang.SubroutineSymbol)):
                return slang.VisitAction.Skip

        self.root.visit(visit)
        return matches

    def comparison(self, node, target):
        deps = _references(node)
        span = self.span(node)
        left, right = self.span(node.left), self.span(node.right)
        if not span or not left or not right or target.hierarchicalPath not in deps:
            return None
        op = _OPERATORS[node.op]
        operand_type = _type(node.left)
        base = dict(span=span, operator=op, operand_type=operand_type, left=left.text, right=right.text,
                    dependencies=deps)
        for wide, extended, normalized in ((node.left, node.right, op), (node.right, node.left, _REVERSED[op])):
            if not isinstance(wide, slang.NamedValueExpression) or wide.symbol != target:
                continue
            t = _type(wide)
            n = _narrow_operand(extended)
            if (not n or not t.zero_based_vector or t.signed or _type(extended).signed
                    or t.width != extended.type.bitWidth or not 1 <= n.type.bitWidth <= min(8, t.width // 2)
                    or t.width < 16):
                continue
            wide_span, narrow_span = self.span(wide), self.span(n)
            # Limit a replacement to plain identifiers. In particular, keep macro
            # references, hierarchy accesses and comments embedded in expressions intact.
            if (wide_span and narrow_span and wide_span.text == target.name and narrow_span.text == n.symbol.name
                    and not any(s in span.text for s in ("//", "/*", "`", "\\"))):
                return Comparison(**{**base, "operator": normalized}, wide=wide_span.text, narrow=narrow_span.text,
                                  narrow_width=n.type.bitWidth, unknowns_possible=t.four_state or n.type.isFourState)
        return Comparison(**base)

    def register(self, instance, signal, elaboration):
        target = instance.body.find(signal)
        if not isinstance(target, slang.VariableSymbol):
            return None
        updates = []
        uncertain_writer = False
        writers = 0

        def procedure(node):
            nonlocal uncertain_writer, writers
            if isinstance(node, (slang.InstanceSymbol, slang.SubroutineSymbol, slang.ContinuousAssignSymbol)):
                if isinstance(node, slang.ContinuousAssignSymbol) and node.assignment.getSymbolReference() == target:
                    uncertain_writer = True
                return slang.VisitAction.Skip
            if not isinstance(node, slang.ProceduralBlockSymbol):
                return
            if not _writes(node.body, target):
                return slang.VisitAction.Skip
            writers += 1

            body = node.body
            event = body.timing if isinstance(body, slang.TimedStatement) else None
            clock = edge = None
            if (node.procedureKind in (slang.ProceduralBlockKind.Always, slang.ProceduralBlockKind.AlwaysFF)
                    and isinstance(event, slang.SignalEventControl) and event.iffCondition is None
                    and event.edge in (slang.EdgeKind.PosEdge, slang.EdgeKind.NegEdge)
                    and isinstance(event.expr, slang.NamedValueExpression)):
                clock, edge = event.expr.symbol.hierarchicalPath, event.edge.name
            if event:
                body = body.stmt

            def walk(stmt, decisions=()):
                nonlocal uncertain_writer
                if isinstance(stmt, slang.BlockStatement):
                    walk(stmt.body, decisions)
                elif isinstance(stmt, slang.StatementList):
                    for child in stmt.list:
                        walk(child, decisions)
                elif isinstance(stmt, slang.ConditionalStatement) and len(stmt.conditions) == 1:
                    expr = stmt.conditions[0].expr
                    span = self.span(expr)
                    if not span or stmt.conditions[0].pattern is not None:
                        if _writes(stmt, target):
                            uncertain_writer = True
                        return
                    comparisons = []

                    def visit(member):
                        if isinstance(member, slang.BinaryExpression) and member.op in _OPERATORS:
                            if comparison := self.comparison(member, target):
                                comparisons.append(comparison)

                    expr.visit(visit)
                    for branch, child, other in (("then", stmt.ifTrue, stmt.ifFalse),
                                                 ("else", stmt.ifFalse, stmt.ifTrue)):
                        if child and _writes(child, target):
                            decision = Decision("if", branch, span, _references(expr), tuple(comparisons),
                                                _writes(other, target))
                            walk(child, (*decisions, decision))
                elif isinstance(stmt, slang.ExpressionStatement):
                    assignment = stmt.expr
                    if not isinstance(assignment, slang.AssignmentExpression) or _direct_value(assignment.left) != target:
                        return
                    span = self.span(assignment)
                    if (not assignment.isNonBlocking or assignment.timingControl is not None
                            or not isinstance(assignment.left, slang.NamedValueExpression) or not span):
                        uncertain_writer = True
                        return
                    refs = _references(assignment.right)
                    updates.append(Update(span, clock, edge, not refs, refs, decisions))
                elif _writes(stmt, target):
                    # A case, loop, unsupported timing control or partial assignment
                    # can change the hold/default behavior of these registers.
                    uncertain_writer = True

            walk(body)
            return slang.VisitAction.Skip

        instance.body.visit(procedure)
        if (uncertain_writer or writers != 1 or not updates or any(not u.clock for u in updates)
                or len({(u.clock, u.edge) for u in updates}) != 1):
            return None
        return Register(instance.hierarchicalPath, signal, _type(target), elaboration, tuple(updates),
                        any(not p.isLocalParam for p in instance.body.parameters))


class SemanticIndex:
    """Compile the supplied top once, with a parameter-free module fallback."""

    def __init__(self, source_index, top):
        self.top = top
        self.texts = source_index.texts
        self.modules = source_index.modules
        self._project = None
        self._tried_project = False
        self._standalone = {}
        self._registers = {}

    def _compile_project(self):
        if self.top and len(self.modules.get(self.top, ())) == 1:
            files = [n for n in self.texts if Path(n).suffix.lower() in {".v", ".sv"}]
            if len(files) <= 96 and sum(len(self.texts[n]) for n in files) <= _MAX_PROJECT_BYTES:
                texts = {n: self.texts[n].encode() for n in files}
                if sum(map(len, texts.values())) <= _MAX_PROJECT_BYTES:
                    return _Compilation(texts, self.top)
        return None

    def resolve(self, module, scope, signal):
        key = module.file, module.name, scope, signal
        if key not in self._registers:
            try:
                self._registers[key] = self._resolve(module, scope, signal)
            except (RuntimeError, ValueError, UnicodeError) as error:
                self._registers[key] = None, f"Slang could not resolve this register ({error})."
        return self._registers[key]

    def _resolve(self, module, scope, signal):
        if not self._tried_project:
            self._tried_project = True
            self._project = self._compile_project()
        world = self._project
        if world and world.complete:
            path = self.top + ("." + scope.replace("/", ".") if scope else "")
            instances = world.instances(path)
            elaboration = "Supplied project hierarchy"
        else:
            key = module.file, module.name
            if key not in self._standalone:
                data = self.texts[module.file].encode()
                self._standalone[key] = (_Compilation({module.file: data}, module.name)
                                         if len(data) <= _MAX_MODULE_BYTES else None)
            world = self._standalone[key]
            instances = world.instances(module.name) if world and world.complete else []
            if any(any(not p.isLocalParam for p in i.body.parameters) for i in instances):
                return None, "Project elaboration is unresolved and the module has overridable parameters."
            elaboration = "Isolated parameter-free module. Full project elaboration is unavailable."
        if (len(instances) != 1 or instances[0].definition.name != module.name
                or world.buffers.get(instances[0].definition.location.buffer, (None,))[0] != module.file):
            return None, "The captured register scope does not resolve to a unique elaborated source instance."
        register = world.register(instances[0], signal, elaboration)
        if not register:
            return None, "The register has unsupported update semantics or its driver could not be resolved."
        return register, None
