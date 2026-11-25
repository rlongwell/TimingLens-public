"""Read-only source editor with line numbers and explicit correlation evidence."""
from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFontDatabase, QPainter, QTextCursor, QTextFormat
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QPlainTextEdit, QPushButton, QTextEdit, QVBoxLayout, QWidget

from .widgets import label, set_syntax
from ..syntax import file_syntax


class LineNumbers(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.number_width(), 0)

    def paintEvent(self, event):
        editor = self.editor
        painter = QPainter(self)
        painter.fillRect(event.rect(), editor.palette().alternateBase())
        painter.setPen(editor.palette().text().color())
        block = editor.firstVisibleBlock()
        while block.isValid():
            geometry = editor.blockBoundingGeometry(block).translated(editor.contentOffset())
            top = int(geometry.top())
            if top > event.rect().bottom():
                break
            if block.isVisible() and geometry.bottom() >= event.rect().top():
                painter.drawText(0, top, self.width() - 7, editor.fontMetrics().height(),
                                 Qt.AlignmentFlag.AlignRight, str(block.blockNumber() + 1))
            block = block.next()


class CodeEditor(QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self.setObjectName("CodeEditor")
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.numbers = LineNumbers(self)
        self.blockCountChanged.connect(lambda _: self.update_numbers())
        self.updateRequest.connect(self.scroll_numbers)
        self.update_numbers()

    def number_width(self):
        return 16 + self.fontMetrics().horizontalAdvance("9") * max(2, len(str(self.blockCount())))

    def update_numbers(self):
        self.setViewportMargins(self.number_width(), 0, 0, 0)
        rect = self.contentsRect()
        self.numbers.setGeometry(QRect(rect.left(), rect.top(), self.number_width(), rect.height()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_numbers()

    def scroll_numbers(self, rect, dy):
        if dy:
            self.numbers.scroll(0, dy)
        else:
            self.numbers.update(0, rect.y(), self.number_width(), rect.height())

    def jump(self, line, last, colors):
        if line:
            block = self.document().findBlockByNumber(line - 1)
            if block.isValid():
                self.setTextCursor(QTextCursor(block))
                self.centerCursor()
        highlights = []
        if line and last:
            for number in range(line, last + 1):
                block = self.document().findBlockByNumber(number - 1)
                if block.isValid():
                    selection = QTextEdit.ExtraSelection()
                    selection.cursor = QTextCursor(block)
                    selection.format.setBackground(QColor(colors["accent_bg"]))
                    selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
                    highlights.append(selection)
        self.setExtraSelections(highlights)


class SourcePage(QWidget):
    def __init__(self):
        super().__init__()
        self.texts = {}
        self.colors = None
        self.active_range = None
        self.files = QComboBox()
        self.files.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.files.setMinimumContentsLength(26)
        self.search = QLineEdit(placeholderText="Find in source")
        button = QPushButton("Find next")
        button.clicked.connect(self.find)
        self.search.returnPressed.connect(self.find)
        controls = QHBoxLayout()
        controls.addWidget(self.files, 2)
        controls.addWidget(self.search, 1)
        controls.addWidget(button)
        self.evidence = label("Open a session to browse available RTL.", "Muted")
        self.evidence.setWordWrap(True)
        self.editor = CodeEditor()
        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self.evidence)
        layout.addWidget(self.editor)
        self.files.currentIndexChanged.connect(self._show_file)

    def load(self, index):
        self.texts = index.texts
        self.files.blockSignals(True)
        self.files.clear()
        for path in sorted(self.texts):
            self.files.addItem(f"{Path(path).parent.name}/{Path(path).name}", path)
            self.files.setItemData(self.files.count() - 1, path, Qt.ItemDataRole.ToolTipRole)
        self.files.blockSignals(False)
        self._show_file()

    def _show_file(self):
        path = self.files.currentData()
        set_syntax(self.editor, file_syntax(path) if path else 'rtl')
        self.editor.setPlainText(self.texts.get(path, ""))
        self.active_range = None
        self.editor.setExtraSelections([])
        self.evidence.setText(path or "Source snapshots are unavailable for this session.")

    def show_source(self, association):
        if association.file in self.texts:
            position = self.files.findData(association.file)
            self.files.setCurrentIndex(position)
            line = association.first or association.module_line
            self.active_range = (line, association.last if association.first else None)
            self.editor.jump(*self.active_range, self.colors)
        else:
            self.editor.setExtraSelections([])
            self.active_range = None
        structure = ""
        if association.constructs:
            structure = "  ·  " + ", ".join(sorted({item.kind for item in association.constructs}))
        symbols = sorted({symbol for item in association.constructs for symbol in item.signals})
        names = "  ·  Parsed identifiers: " + ", ".join(symbols) if symbols else ""
        self.evidence.setText(f"{association.confidence.label}  ·  {association.reason}{structure}{names}")

    def find(self):
        if not self.search.text():
            return
        if not self.editor.find(self.search.text()):
            self.editor.moveCursor(QTextCursor.MoveOperation.Start)
            self.editor.find(self.search.text())

    def theme(self, colors):
        self.colors = colors
        if self.active_range:
            cursor = self.editor.textCursor()
            position = self.editor.verticalScrollBar().value()
            self.editor.jump(*self.active_range, self.colors)
            self.editor.setTextCursor(cursor)
            self.editor.verticalScrollBar().setValue(position)
