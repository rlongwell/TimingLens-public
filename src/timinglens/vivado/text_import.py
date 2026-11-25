"""Import textual Vivado paths as report-derived evidence, without a DCP.

Only explicitly printed resources and incremental delays become arcs. Hidden
names and omitted pin rows remain unavailable; this is not a native netlist.
"""
from __future__ import annotations

import re

from ..timing.models import Arc, Cell, Clock, Net, Pin, Session, TimingPath
from .reports import NUMBER, ROW, PIN_ROW, CLOCK_SUFFIX, timing_summary, timing_checks, clock_interactions, design_stage


def metadata(text):
    result = {}
    for key, pattern in {'vivado': r'Tool Version\s*:\s*Vivado\s+v?([0-9.]+)',
                         'part': r'\|\s*Device\s*:\s*(\S+)', 'top': r'\|\s*Design\s*:\s*(\S+)'}.items():
        if match := re.search(pattern, text):result[key] = match[1]
    stage = design_stage(text, text, 'none')
    if stage != 'unknown':result['stage'] = stage
    return result


def _field(block, name):
    match = re.search(r'^\s*' + re.escape(name) + r':\s*(.*?)\s*$', block, re.M)
    return match[1] if match else None


def _number(block, name):
    match = re.search(r'^\s*' + re.escape(name) + rf':\s*({NUMBER})ns', block, re.M)
    return float(match[1]) if match else None


def _events(block):
    partition = resource = None
    pending = ''
    for line in block.splitlines():
        if 'Incr(ns)' in line and 'Netlist Resource' in line:
            partition = line.find('Partition'); resource = line.find('Netlist Resource')
            continue
        if partition is not None and partition >= 0 and len(line) >= resource:
            line = line[:partition] + line[resource:]
        if re.search(r'\b(?:data )?arrival time\s*(?:[+-]?\d+\.\d+)?\s*$', line, re.I):
            break
        if 'Prop_' in line and not ROW.match(line):
            pending = line.strip()
        match = ROW.match(line)
        if match:
            label = match['label'].strip() or pending
            pending = ''
            kind = 'net' if re.search(r'\bnet\s*\(', label) else 'pin'
            name = CLOCK_SUFFIX.sub('', match['name'])
            primitive = re.search(r'\b([A-Z][A-Z0-9_]+)\s*\(Prop_', label)
            yield kind, name, float(match['inc']), primitive[1] if primitive else None, label
        elif match := PIN_ROW.match(line):
            yield 'pin', CLOCK_SUFFIX.sub('', match[1]), None, None, line.strip()


def from_reports(reports: dict[str, str], name='Imported project reports') -> Session:
    cells = {}; pins = {}; nets = {}; paths = []; clocks = {}; summaries = {}; warnings = []
    meta = {}; details = {'setup': [], 'hold': []}; seen_paths = set()
    for filename, text in reports.items():
        for key, value in metadata(text).items():
            if key in meta and meta[key] != value:raise ValueError('Reports describe different designs/devices/releases/stages; inspect one implementation at a time.')
            meta[key] = value
        for kind, total in timing_summary(text).items():
            if kind in summaries and summaries[kind] != total:raise ValueError('Conflicting design-wide timing summaries; use reports from one implementation.')
            summaries[kind] = total
        blocks = re.split(r'(?=^\s*Slack\s*\((?:MET|VIOLATED)\)\s*:)', text, flags=re.M)[1:]
        for block in blocks:
            slack = re.match(rf'\s*Slack\s*\((?:MET|VIOLATED)\)\s*:\s*({NUMBER})ns', block)
            source, endpoint = _field(block, 'Source'), _field(block, 'Destination')
            kind_text = _field(block, 'Path Type') or ''
            kind = 'hold' if kind_text.startswith(('Hold', 'Removal')) else 'setup'
            if not slack:continue
            pid = f'P{len(paths)+1:05d}'
            path_pins = []; path_cells = []; path_nets = []; arcs = []; last = None; pending_net = None; active = False
            # Pin direction follows the printed propagation sequence. Both sides
            # must be explicit before a cell or net arc can be assigned a delay.
            for event, resource, delay, primitive, label in _events(block):
                if resource == source:active = True
                if not active:continue
                if event == 'net':
                    pending_net = (resource, delay, re.search(r'fo=(\d+)', label))
                    continue
                if resource == '<hidden>' or '/' not in resource:
                    last = None; pending_net = None;continue
                cell_name, ref = resource.rsplit('/', 1)
                if primitive:
                    old = cells.get(cell_name)
                    cells[cell_name] = Cell(name=cell_name, primitive=primitive, sequential=primitive.startswith(('FD', 'LD')),
                                            parent=old.parent if old else None, properties={'EVIDENCE_ORIGIN': 'Vivado timing report'})
                elif cell_name not in cells:
                    # A sink-only FF/RAM may have its type on a pin row.
                    found = re.search(r'\b(FD\w+|LD\w+|RAM\w+)\b', label)
                    primitive = found[1] if found else 'Unknown'
                    cells[cell_name] = Cell(name=cell_name, primitive=primitive,
                                            sequential=primitive.startswith(('FD', 'LD')), properties={'EVIDENCE_ORIGIN': 'Vivado timing report'})
                pin = Pin(name=resource, cell=cell_name, ref_pin=ref, direction='IN')
                pins[resource] = pin
                if resource not in path_pins:path_pins.append(resource)
                if cell_name not in path_cells:path_cells.append(cell_name)
                if last and pending_net:
                    net_name, elapsed, fanout = pending_net
                    if net_name != '<hidden>':
                        old = nets.get(net_name)
                        drivers = sorted(set((old.drivers if old else []) + [last]))
                        sinks = sorted(set((old.sinks if old else []) + [resource]))
                        nets[net_name] = Net(name=net_name, drivers=drivers, sinks=sinks, fanout=int(fanout[1]) if fanout else None,
                                            properties={'EVIDENCE_ORIGIN': 'Vivado timing report'})
                        pins[last] = pins[last].model_copy(update={'direction': 'OUT'})
                        arcs.append(Arc(source=last, sink=resource, resource=net_name, kind='net', delay_ns=elapsed))
                        if net_name not in path_nets:path_nets.append(net_name)
                elif last and pins[last].cell == cell_name:
                    pins[resource] = pin.model_copy(update={'direction': 'OUT'})
                    arcs.append(Arc(source=last, sink=resource, resource=cell_name, kind='cell', delay_ns=delay))
                last = resource; pending_net = None
                if resource == endpoint:break
            for clock, period in re.findall(r'clocked by (\S+)\s+\{[^}]*period=([\d.]+)ns', block):
                clocks[clock] = Clock(name=clock, period_ns=float(period))
            clock_names = re.findall(r'clocked by (\S+)', block)
            data = re.search(rf'Data Path Delay:\s*({NUMBER})ns\s*\(logic\s+({NUMBER})ns.*?route\s+({NUMBER})ns', block)
            levels = re.search(r'Logic Levels:\s*(\d+)', block)
            key = (source, endpoint, kind_text, float(slack[1]), tuple((a.source,a.sink,a.kind,a.resource,a.delay_ns) for a in arcs))
            if key in seen_paths:continue
            seen_paths.add(key)
            paths.append(TimingPath(id=pid, analysis=kind, startpoint=source, endpoint=endpoint, path_type=kind_text,
                                    start_clock=clock_names[0] if clock_names else None, end_clock=clock_names[1] if len(clock_names)>1 else None,
                                    slack_ns=float(slack[1]), requirement_ns=_number(block, 'Requirement'),
                                    datapath_ns=float(data[1]) if data else None, logic_ns=float(data[2]) if data else None,
                                    routing_ns=float(data[3]) if data else None, levels=int(levels[1]) if levels else None,
                                    cells=path_cells, pins=path_pins, nets=path_nets, arcs=arcs,
                                    properties={'EVIDENCE_ORIGIN': 'Vivado timing report'}))
            details[kind].append(f'TIMINGLENS_PATH {pid}\n{block}')
    if not paths and not summaries:raise ValueError('No supported Vivado timing paths or design timing summary found.')
    warnings.append('Report-only import: connectivity follows explicitly printed timing rows; full native hierarchy, off-path fanout and source metadata are unavailable. Use a DCP/session for stronger evidence.')
    combined='\n'.join(reports.values())
    if not summaries:warnings.append('Design-wide setup/hold totals are unavailable; captured paths are not the complete failing-endpoint count.')
    stage = meta.pop('stage', 'unknown')
    return Session(name=name, **meta, paths=paths, cells=cells, pins=pins, nets=nets, clocks=list(clocks.values()), summary=summaries,
                   stage=stage, timing_checks=timing_checks(combined), clock_interactions=clock_interactions(combined),
                   reports={**reports, **{f'{kind}-paths.rpt':'\n'.join(blocks) for kind,blocks in details.items()}}, warnings=warnings)
