"""Offline project context. Tcl/XDC are parsed as text and never executed."""
from __future__ import annotations

from dataclasses import dataclass
import json
import re


@dataclass(frozen=True)
class Fact:
    kind: str
    file: str
    line: int
    subject: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class ProjectContext:
    facts: tuple[Fact, ...]
    warnings: tuple[str, ...]


def commands(text):
    """Split literal Tcl commands without evaluating substitutions or bodies."""
    start = 1
    line = 1
    braces = brackets = 0
    quote = escape = comment = False
    current = []
    for char in text:
        if comment:
            if char == '\n':
                comment = False; current = []; start = line + 1
        elif char == '#' and not ''.join(current).strip() and not braces and not brackets and not quote:
            comment = True
        elif escape:
            current.append(' ' if char == '\n' else '\\' + char)
            escape = False
        elif char == '\\':
            escape = True
        elif char == '"' and not braces:
            quote = not quote; current.append(char)
        elif char == '{' and not quote:
            braces += 1; current.append(char)
        elif char == '}' and not quote:
            braces = max(0, braces - 1); current.append(char)
        elif char == '[' and not braces and not quote:
            brackets += 1; current.append(char)
        elif char == ']' and not braces and not quote:
            brackets = max(0, brackets - 1); current.append(char)
        elif char in '\n;' and not braces and not brackets and not quote:
            command = ''.join(current).strip()
            if command and not command.startswith('#'):
                yield start, command
            current = []; start = line + (char == '\n')
        else:
            current.append(char)
        if char == '\n':
            line += 1
    command = ''.join(current).strip()
    if command and not command.startswith('#'):
        yield start, command


def _literal(value):
    value = value.strip().strip('{}"')
    return value if value and not re.search(r'[\s$\[\];\\]', value) else None


def context(sources) -> ProjectContext:
    facts = []; warnings = []
    for source in sources:
        if source.text is None:
            continue
        suffix = source.path.rsplit('.', 1)[-1].lower()
        if suffix in {'tcl', 'xdc'}:
            handles = {}
            for line, command in commands(source.text):
                # Literal create commands can be direct or assigned to a Tcl
                # handle. Dynamic Tcl control flow is deliberately not evaluated.
                create = re.fullmatch(r'(?:set\s+(\w+)\s+\[)?(create_bd_cell|create_bd_intf_port)\s+(.*?)\]?', command, re.S)
                if create:
                    args = create[3].strip().removesuffix(']').split()
                    name = _literal(args[-1]) if args else None
                    vlnv = next((_literal(args[i+1]) for i, a in enumerate(args[:-1]) if a == '-vlnv'), None)
                    if name and vlnv:
                        facts.append(Fact('bd_ip' if create[2] == 'create_bd_cell' else 'bd_port', source.path, line, name, (vlnv,)))
                        if create[1]:handles[create[1]] = name
                if command.startswith('connect_bd_intf_net '):
                    reference = r'\[get_bd_intf_(?:pins|ports)\s+([^\]]+)\]|\$(\w+)'
                    refs = re.findall(reference, command)
                    residue = re.sub(reference, '', command).strip()
                    endpoints = []
                    for literal, variable in refs:
                        endpoint = _literal(literal) if literal else handles.get(variable)
                        if endpoint:endpoints.append(endpoint)
                    if len(endpoints) == len(refs) == 2 and re.fullmatch(r'connect_bd_intf_net(?:\s+-intf_net\s+[A-Za-z0-9_/.-]+)?', residue):
                        facts.append(Fact('bd_link', source.path, line, endpoints[0], (endpoints[1],)))
                    else:
                        warnings.append(f'{source.path}:{line}: interface connection contains unresolved Tcl; no connection was inferred.')
                if command.startswith('connect_bd_net '):
                    reference = r'\[get_bd_(?:pins|ports)\s+([^\]]+)\]'
                    refs = re.findall(reference, command)
                    endpoints = [_literal(r) for r in refs]
                    residue = re.sub(reference, '', command).strip()
                    if len(endpoints) >= 2 and all(endpoints) and re.fullmatch(r'connect_bd_net(?:\s+-net\s+[A-Za-z0-9_/.-]+)?', residue):
                        facts.append(Fact('bd_pin_net', source.path, line, endpoints[0], tuple(endpoints[1:])))
                    else:
                        warnings.append(f'{source.path}:{line}: scalar BD net contains unresolved Tcl; clock/reset connectivity is unknown.')
                if command.startswith('set_property '):
                    target = re.search(r'\[get_bd_cells\s+([^\]]+)\]\s*$|\$(\w+)\s*$', command)
                    name = (_literal(target[1]) if target[1] else handles.get(target[2])) if target else None
                    if name:
                        for key, value in re.findall(r'CONFIG\.([A-Za-z0-9_]+)\s+(\{[^{}]*\}|"[^"]*"|[^\s\]]+)', command):
                            if literal := _literal(value):facts.append(Fact('bd_parameter', source.path, line, name, (key, literal)))
                if re.match(r'(?:opt_design|place_design|phys_opt_design|route_design)\b', command):
                    match = re.search(r'-directive\s+(\w+)', command)
                    facts.append(Fact('build_directive', source.path, line, command.split()[0], (match[1] if match else 'Default',)))
                if re.match(r'(?:create_clock|create_generated_clock|set_false_path|set_multicycle_path|set_clock_groups|set_case_analysis|set_max_delay|set_min_delay|set_disable_timing)\b', command):
                    facts.append(Fact('constraint', source.path, line, command.split()[0], (command,)))
                if command.startswith(('source ', 'if ', 'foreach ', 'for ', 'proc ')):
                    warnings.append(f'{source.path}:{line}: Tcl control flow/includes were not executed; declarations in supplied files are context, not proof of the implemented design.')
        elif suffix == 'bd':
            pending_facts = []
            try:
                doc = json.loads(source.text)
                design = doc.get('design', {})
                for name, component in design.get('components', {}).items():
                    if vlnv := component.get('vlnv'):
                        if not isinstance(vlnv,str): raise ValueError('Invalid VLNV')
                        pending_facts.append(Fact('bd_ip', source.path, 1, name, (vlnv,)))
                    for key, value in component.get('parameters', {}).items():
                        value = value.get('value') if isinstance(value, dict) else value
                        if isinstance(value, (str, int, float)):
                            pending_facts.append(Fact('bd_parameter', source.path, 1, name, (key, str(value))))
                for name, net in design.get('interface_nets', {}).items():
                    endpoints = net.get('interface_ports', [])
                    if len(endpoints) == 2 and all(isinstance(v, str) for v in endpoints):
                        pending_facts.append(Fact('bd_link', source.path, 1, endpoints[0], (endpoints[1],)))
                for net in design.get('nets', {}).values():
                    endpoints = net.get('ports', [])
                    if len(endpoints) >= 2 and all(isinstance(v, str) for v in endpoints):
                        pending_facts.append(Fact('bd_pin_net', source.path, 1, endpoints[0], tuple(endpoints[1:])))
                facts.extend(pending_facts)
            except (ValueError, TypeError, AttributeError):
                warnings.append(f'{source.path}: unsupported block-design JSON structure; no hardware facts inferred.')
        elif suffix == 'json':
            pending_facts = []
            try:
                doc = json.loads(source.text)
                if isinstance(doc, dict) and doc.get('timinglens_intent') == 1:
                    for item in doc.get('stream_links', []):
                        required = ('source', 'sink', 'max_burst_beats', 'buffer_capacity_beats', 'reason')
                        if not all(k in item for k in required):raise ValueError('Incomplete stream intent')
                        burst, capacity = item['max_burst_beats'], item['buffer_capacity_beats']
                        if type(burst) is not int or type(capacity) is not int or min(burst, capacity) < 0:raise ValueError('Invalid buffer bounds')
                        if not all(isinstance(item[k], str) and item[k] for k in ('source', 'sink', 'reason')):raise ValueError('Invalid stream intent')
                        pending_facts.append(Fact('buffer_intent', source.path, 1, str(item['source']),
                                          (str(item['sink']), str(burst), str(capacity), str(item['reason']))))
                    for item in doc.get('asynchronous_clocks', []):
                        if not all(isinstance(item.get(k), str) and item[k] for k in ('source', 'destination', 'reason')):raise ValueError('Incomplete clock intent')
                        pending_facts.append(Fact('async_intent', source.path, 1, item['source'], (item['destination'], item['reason'])))
                    for item in doc.get('multicycle_paths', []):
                        if not all(isinstance(item.get(k), str) and item[k] for k in ('source', 'destination', 'reason')):raise ValueError('Incomplete multicycle intent')
                        if type(item.get('cycles')) is not int or not 2 <= item['cycles'] <= 1000000:raise ValueError('Invalid multicycle count')
                        pending_facts.append(Fact('multicycle_intent', source.path, 1, item['source'], (item['destination'], str(item['cycles']), item['reason'])))
                    facts.extend(pending_facts)
            except (ValueError, TypeError, AttributeError):
                warnings.append(f'{source.path}: invalid design-intent data; no unsupported assertion will be used.')
    return ProjectContext(tuple(facts), tuple(dict.fromkeys(warnings)))
