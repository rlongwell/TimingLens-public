"""Apply syntax spans to Qt layouts without changing selectable evidence or rich-text links."""
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

from ..syntax import highlight_line


class EvidenceHighlighter(QSyntaxHighlighter):
    def __init__(self, document, syntax):
        super().__init__(document)
        self.syntax = syntax
        self.colors = None
        self.formats = {}

    def set_colors(self, colors):
        self.colors = colors
        self.formats.clear()
        self.rehighlight()

    def style(self, color, background, bold=False):
        key = color, background, bold
        if key not in self.formats:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(self.colors[color]))
            if background:
                fmt.setBackground(QColor(self.colors[background]))
            if bold:
                fmt.setFontWeight(QFont.Weight.DemiBold)
            self.formats[key] = fmt
        return self.formats[key]

    def highlightBlock(self, text):
        if not self.colors:
            return
        kind = self.syntax
        if kind.startswith('rich-'):
            if not self.currentBlock().blockFormat().nonBreakableLines():
                self.setCurrentBlockState(0)
                return
            kind = kind.removeprefix('rich-')
        spans, bg, state = highlight_line(text, kind, max(0, self.previousBlockState()))
        self.setCurrentBlockState(state)
        # Qt positions count UTF-16 code units. Astral characters occupy two.
        offsets = range(len(text) + 1)
        if not text.isascii():
            offsets = [0]
            for char in text:
                offsets.append(offsets[-1] + (2 if ord(char) > 0xffff else 1))
        if bg:
            self.setFormat(0, offsets[-1], self.style('text', bg))
        for span in spans:
            start = offsets[span.start]
            self.setFormat(start, offsets[span.end] - start, self.style(span.color, bg, span.bold))
