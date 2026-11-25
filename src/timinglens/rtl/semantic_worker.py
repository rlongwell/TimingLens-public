"""Bounded slang worker. Input is JSON source data, never Python or Tcl code."""
import json
import resource
import sys
from dataclasses import asdict


def main():
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (4, 5))
    from .syntax import build_index
    from .semantics import SemanticIndex
    from ..timing.models import Source
    data = sys.stdin.buffer.read(5_000_001)
    if len(data) > 5_000_000:
        raise ValueError('Semantic request exceeds size budget')
    request = json.loads(data)
    index = build_index([Source(path=p, text=t) for p, t in request['texts'].items()])
    semantics = SemanticIndex(index, request['top'])
    responses = []
    for file, name, scope, signal in request['registers']:
        matches = [m for m in index.modules.get(name, ()) if m.file == file]
        reg, reason = semantics.resolve(matches[0], scope, signal) if len(matches) == 1 else (None, 'Source module is ambiguous.')
        responses.append({'register': asdict(reg) if reg else None, 'reason': reason})
    output = json.dumps(responses)
    if len(output.encode()) > 8_000_000:
        raise ValueError('Semantic response exceeds size budget')
    sys.stdout.write(output)


if __name__ == '__main__':
    main()
