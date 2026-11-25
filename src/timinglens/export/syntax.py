"""Offline HTML highlighting. Interpolate only trusted style names and escaped evidence."""
from html import escape
from ..syntax import highlight_line


STYLE = """
.t-keyword,.t-accent{color:#9cc5ff}.t-identifier{color:#b1dce0}.t-literal{color:#f5cb93}
.t-operator{color:#e0b3ef}.t-comment{color:#b7b7b7}.t-success{color:#b4d9a0}
.t-bad{color:#ffaaa2}.t-warning{color:#f0c477}.t-diff_add_bg{background:#2b3d2e}
.t-diff_remove_bg{background:#493133}pre.syntax{background:#24272b;color:#eee;padding:1em}
"""


def code_block(source, syntax):
    parts = []
    state = 0
    for line in source.splitlines(keepends=True):
        spans, bg, state = highlight_line(line.rstrip('\r\n'), syntax, state)
        if bg:
            parts.append(f'<span class="t-{bg}">')
        start = 0
        for span in spans:
            tag = 'strong' if span.bold else 'span'
            parts.extend((escape(line[start:span.start]), f'<{tag} class="t-{span.color}">',
                          escape(line[span.start:span.end]), f'</{tag}>'))
            start = span.end
        parts.append(escape(line[start:]))
        if bg:
            parts.append('</span>')
    return '<pre class="syntax">' + ''.join(parts) + '</pre>'
