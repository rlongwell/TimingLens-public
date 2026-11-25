"""Line-oriented highlighting for the desktop and portable reports. Offsets index source characters."""
from dataclasses import dataclass
from pathlib import Path
import re


def file_syntax(name):
    suffix = Path(name).suffix.lower()
    return {
        '.sv': 'rtl', '.v': 'rtl', '.svh': 'rtl', '.vh': 'rtl', '.xdc': 'tcl', '.tcl': 'tcl',
        '.vhd': 'vhdl', '.vhdl': 'vhdl', '.bd': 'json', '.xci': 'json', '.patch': 'diff', '.diff': 'diff',
        '.log': 'log', '.jou': 'log', '.json': 'json',
    }.get(suffix, 'report')


@dataclass(frozen=True, slots=True)
class Span:
    start: int
    end: int
    color: str
    bold: bool = False


STRING = r'"(?:\\.|[^"\\])*"'
NUMBER = r'(?<!\w)[+−-]?\d+(?:\.\d+)?'
KEYWORDS = (
    r'module|endmodule|wire|logic|reg|bit|input|output|inout|parameter|localparam|always(?:_ff|_comb|_latch)?'
    r'|posedge|negedge|assign|if|else|for|genvar|begin|end|case[zx]?|endcase|generate|endgenerate|typedef'
    r'|function|endfunction|integer|int|return|signed|unsigned|automatic|initial|while|repeat'
)
RTL = re.compile(
    rf'(?P<comment>//.*)|(?P<opening>/\*)|(?P<literal>{STRING}|\b\d+\x27[sS]?[bBoOdDhH][\da-fA-F_xXzZ?]+'
    rf'|\x27[01xXzZ]|\b\d+(?:\.\d+)?)|(?P<keyword>\b(?:{KEYWORDS})\b)|(?P<identifier>[A-Za-z_$][\w$]*)'
    r'|(?P<operator>&&|\|\||===?|!==?|<=|>=|<<|>>|[&|^~!=<>+*/%:-])'
)
VHDL = re.compile(
    r"""(?P<comment>--.*)|(?P<literal>"(?:[^"]|"")*"|'[01UXZWLH-]'|\b\d+(?:\.\d+)?)"""
    r'|(?P<keyword>\b(?:library|use|entity|architecture|is|of|port|generic|in|out|inout|signal|'
    r'variable|constant|downto|to|range|process|begin|end|if|then|elsif|else|case|when|others|'
    r'component|map|generate|for|std_logic(?:_vector)?|signed|unsigned|rising_edge|falling_edge|'
    r'and|or|xor|not)\b)|(?P<identifier>[a-z][\w]*)|(?P<operator><=|=>|:=|/=|>=|[=<>&+*/-])', re.I)
JSON = re.compile(rf'(?P<keyword>{STRING}(?=\s*:))|(?P<literal>{STRING}|{NUMBER}(?:[Ee][+-]?\d+)?)'
                  r'|(?P<operator>\b(?:true|false|null)\b)')
TCL = re.compile(
    rf'(?P<comment>(?:^\s*|;\s*)\#.*)|(?P<literal>{STRING}|{NUMBER}\b)'
    r'|(?P<keyword>\b(?:set|unset|expr|if|else|foreach|proc|return|puts|source|incr|list|lindex|dict|'
    r'(?:get|set|create|report|read|write|synth|opt|place|phys_opt|route|open|link|current)_[a-z0-9_]+)\b)'
    r'|(?P<identifier>\$(?:\{[^}]+\}|[\w:]+)|(?<!\w)-[a-zA-Z][\w-]*)|(?P<operator>[\[\]{}])'
)
REPORT = re.compile(
    r'(?P<bad>\b(?:VIOLATED|FAILED|ERROR)\b)|(?P<success>\b(?:MET|PASSED)\b)'
    r'|(?P<keyword>\b(?:required time|arrival time|slack|source|destination|path type|path group|'
    r'data path delay|logic levels|clock uncertainty|WNS|TNS|WHS|THS)\b)'
    r'|(?P<identifier>\b(?:CARRY\d+|FD[A-Z]+|LUT\d|SLICE_X\d+Y\d+)\b)'
    rf'|(?P<literal>{NUMBER}(?:ns|ps|MHz|%)?)', re.I)
SLACK = re.compile(r'^\s*slack(?:\s*\([^)]*\))?\s*:?\s*([+−-]?\d+(?:\.\d+)?)(?:ns)?\b', re.I)
LOG = re.compile(r'(?P<keyword>\b(?:INFO|NOTE|DEBUG)(?=:))|(?P<accent>\[[A-Za-z][A-Za-z0-9_ ]*\s+\d+-\d+\])'
                 rf'|(?P<literal>{NUMBER}(?:ns|ms|MB|GB|s)?\b)')
LOG_LINES = [
    (re.compile(r'\b(?:ERROR|FATAL)(?:\s*[:\[]|\b error)|^%Error|\b(?:FAILED|FAILURE)\b|\bCRITICAL WARNING\s*:', re.I), 'bad', True),
    (re.compile(r'\bWARNING\s*:', re.I), 'warning', True),
    (re.compile(r'\b(?:PASS(?:ED)?|SUCCESS(?:FUL)?|COMPLETED)\b', re.I), 'success', False),
    (re.compile(r'^\s*(?:==|\[TimingLens\]|Starting\b|Running\b|Phase\b|Step\b|Command\s*:|#\s*\w+)', re.I), 'accent', True)
]


def rtl_line(text, comment, start=0):
    spans = []
    pos = start
    while pos < len(text):
        if comment:
            end = text.find('*/', pos)
            stop = len(text) if end < 0 else end + 2
            spans.append(Span(pos, stop, 'comment'))
            comment = end < 0
            pos = stop
            continue
        match = RTL.search(text, pos)
        if not match:
            break
        if match.lastgroup == 'opening':
            pos = match.start()
            comment = True
        else:
            spans.append(Span(match.start(), match.end(), match.lastgroup))
            pos = match.end()
    return spans, int(comment)


def matched(pattern, text, start=0):
    return [Span(m.start() + start, m.end() + start, m.lastgroup) for m in pattern.finditer(text)]


def diff_line(text, state):
    # Bits 0 and 1 keep independent multiline comment states for the two files.
    # Higher bits select the source language across hunk boundaries.
    modes = ('rtl', 'tcl', 'vhdl', 'json', 'log', 'report')
    language = state >> 2
    if text.startswith(('--- ', '+++ ')):
        filename = text[4:].split('\t', 1)[0]
        if filename != '/dev/null':
            kind = file_syntax(filename)
            # Bare labels such as "before" and "after" occur in generated RTL patches.
            if not Path(filename).suffix:
                kind = 'rtl'
            language = modes.index(kind) if kind in modes else 0
    if text.startswith(('--- ', '+++ ', '@@', 'diff ', 'index ')):
        return [Span(0, len(text), 'accent', True)], None, language << 2
    marker = text[:1]
    old, new = bool(state & 1), bool(state & 2)
    has_prefix = marker in ('+', '-', ' ')
    offset = int(has_prefix)
    if language:
        tokens, _, _ = highlight_line(text[offset:], modes[language])
        spans = [Span(s.start + offset, s.end + offset, s.color, s.bold) for s in tokens]
    else:
        spans, comment = rtl_line(text, old if marker == '-' else new, offset)
        if marker == '-':
            old = comment
        elif marker == '+':
            new = comment
        else:
            old = comment if old == new else rtl_line(text, old, offset)[1]
            new = comment
    background = None
    if marker in ('+', '-'):
        added = marker == '+'
        background = 'diff_add_bg' if added else 'diff_remove_bg'
        spans.insert(0, Span(0, 1, 'success' if added else 'bad', True))
    return spans, background, int(old) | (int(new) << 1) | (language << 2)


def highlight_line(text, syntax, state=0):
    """Return ordered nonoverlapping spans, optional row background and next line state."""
    if syntax == 'diff':
        return diff_line(text, state)
    if syntax == 'rtl':
        spans, state = rtl_line(text, bool(state))
        return spans, None, state
    if syntax == 'log':
        for pattern, color, bold in LOG_LINES:
            if pattern.search(text):
                return [Span(0, len(text), color, bold)], None, 0
    pattern = {'report': REPORT, 'log': LOG, 'tcl': TCL, 'json': JSON, 'vhdl': VHDL}[syntax]
    spans = matched(pattern, text)
    if syntax == 'report' and (slack := SLACK.match(text)):
        color = 'bad' if float(slack[1].replace('−', '-')) < 0 else 'success'
        spans = [Span(s.start, s.end, color, True) if s.start == slack.start(1) else s for s in spans]
    return spans, None, 0
