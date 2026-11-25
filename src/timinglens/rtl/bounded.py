"""One isolated semantic compilation per analysis, with bounded resources."""
import json
from pathlib import Path
import re
import subprocess
import sys
from dataclasses import replace

from .semantics import Comparison, Decision, Register, Span, Update, ValueType


def _register(data):
    if data is None:
        return None
    updates = []
    for u in data['updates']:
        decisions = []
        for d in u['decisions']:
            comparisons = tuple(Comparison(**{**c, 'span': Span(**c['span']),
                                              'operand_type': ValueType(**c['operand_type']),
                                              'dependencies': tuple(c['dependencies'])}) for c in d['comparisons'])
            decisions.append(Decision(**{**d, 'span': Span(**d['span']), 'comparisons': comparisons,
                                          'dependencies': tuple(d['dependencies'])}))
        updates.append(Update(**{**u, 'span': Span(**u['span']), 'decisions': tuple(decisions),
                                 'dependencies': tuple(u['dependencies'])}))
    return Register(**{**data, 'type': ValueType(**data['type']), 'updates': tuple(updates)})


class BoundedSemanticIndex:
    def __init__(self, result):
        self.result = result
        self.resolved = None
        self.reason = 'The register was not in the bounded semantic request.'

    def resolve(self, module, scope, signal):
        if self.resolved is None:
            self._run()
        return self.resolved.get((module.file, module.name, scope, signal), (None, self.reason))

    def _run(self):
        self.resolved = {}
        result = self.result
        texts = {p: t for p, t in result.source_index.texts.items() if Path(p).suffix.lower() in {'.sv', '.v'}}
        limited = len(texts) > 96 or sum(len(t.encode()) for t in texts.values()) > 2_000_000
        requests = set()
        for path in result.session.paths:
            pin = result.session.pins.get(path.endpoint or '')
            cell = result.session.cells.get(pin.cell or '') if pin and pin.ref_pin == 'CE' else None
            if not cell or path.analysis != 'setup' or path.slack_ns is None or path.slack_ns >= 0:
                continue
            link = result.cells[cell.name]
            match = re.fullmatch(r'([A-Za-z_][A-Za-z0-9_$]*)_reg(?:\[\d+\])*', (cell.original_name or cell.name).rsplit('/', 1)[-1])
            if match and link.file and link.module:
                requests.add((link.file, link.module, link.instance, match[1]))
        if len(requests) > 256:
            self.reason = 'Semantic register budget exceeded (256 targets); narrow the captured path selection.'
            return
        requests = sorted(requests, key=lambda r: tuple(x or '' for x in r))
        if limited:
            # Large vendor libraries need not prevent a small, explicitly
            # isolated module review. Never call this project elaboration.
            selected = {r[0] for r in requests}
            texts = {p: t for p, t in texts.items() if p in selected}
            if len(texts) > 96 or sum(len(t.encode()) for t in texts.values()) > 2_000_000:
                self.reason = 'Semantic input budget exceeded (96 files / 2 MB); supply a smaller complete compile unit.'
                return
        try:
            child = subprocess.run([sys.executable, '-m', 'timinglens.rtl.semantic_worker'],
                                   input=json.dumps({'texts': texts, 'top': None if limited else result.session.top, 'registers': requests}),
                                   capture_output=True, text=True, timeout=6)
            if child.returncode:
                self.reason = 'Semantic worker failed or reached its CPU/memory limit; no source rewrite is emitted.'
                return
            responses = json.loads(child.stdout)
            if len(responses) != len(requests):
                raise ValueError('Incomplete semantic response')
            self.resolved = {key: (_register(value['register']), value['reason']) for key, value in zip(requests, responses)}
            if limited:
                self.resolved = {key: (replace(reg, elaboration=reg.elaboration + ' Project input budget exceeded; only target files were compiled.') if reg else None, reason)
                                 for key, (reg, reason) in self.resolved.items()}
        except subprocess.TimeoutExpired:
            self.reason = 'Semantic elaboration exceeded the 6-second time budget; no source rewrite is emitted.'
        except (OSError, ValueError, KeyError, TypeError):
            self.reason = 'Semantic worker response unavailable; no source rewrite is emitted.'
