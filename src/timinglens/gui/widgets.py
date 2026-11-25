"""Reusable Qt widgets and sortable timing path model."""
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QLabel, QPlainTextEdit, QTableWidget, QTableWidgetItem

from ..export.html import value


def label(text="", style="") -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    if style:
        widget.setObjectName(style)
    return widget


def text_area(syntax=None) -> QPlainTextEdit:
    widget = QPlainTextEdit()
    widget.setReadOnly(True)
    if syntax:
        widget.setObjectName('CodeEditor')
        widget.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        set_syntax(widget, syntax)
    return widget


def set_syntax(widget, syntax):
    from .highlighting import EvidenceHighlighter
    active = getattr(widget, 'syntax_highlighter', None)
    if active is not None:
        if active.syntax != syntax:
            active.syntax = syntax
            active.rehighlight()
        return
    active = EvidenceHighlighter(widget.document(), syntax)
    widget.syntax_highlighter = active
    colors = QApplication.instance().property('timinglens_colors')
    if colors:
        active.set_colors(colors)


def fill_table(widget: QTableWidget, headers: tuple[str, ...], rows) -> None:
    rows = list(rows)
    widget.setColumnCount(len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setRowCount(len(rows))
    for y, row in enumerate(rows):
        for x, cell in enumerate(row):
            item = QTableWidgetItem(str(cell))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            widget.setItem(y, x, item)
    widget.resizeColumnsToContents()


class PathTable(QAbstractTableModel):
    headers = ("Path", "Check", "Startpoint", "Endpoint", "Slack (ns)", "Logic (ns)",
               "Route (ns)", "Levels", "Clock pair", "RTL module", "Correlation", "Diagnosis")
    numeric = {4, 5, 6, 7}

    def __init__(self):
        super().__init__()
        self.rows = []
        self.bad = "#ffaaa2"

    def populate(self, result):
        self.beginResetModel()
        self.rows = []
        if result:
            by_path = {}
            for finding in result.findings:
                by_path.setdefault(finding.path_id, set()).add(finding.rule)
            for path in result.session.paths:
                association = result.paths[path.id]
                clock = f"{path.start_clock or '—'} → {path.end_clock or '—'}"
                self.rows.append((path.id, path.analysis.title(), path.startpoint, path.endpoint,
                                  path.slack_ns, path.logic_ns, path.routing_ns, path.levels, clock,
                                  association.module, association.confidence.label,
                                  ", ".join(sorted(by_path.get(path.id, set()))) or
                                  ("Pass" if path.slack_ns is not None and path.slack_ns >= 0 else "Unavailable")))
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.headers)

    def headerData(self, section, orientation, role):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.headers[section]
        return None

    def data(self, index, role):
        if not index.isValid():
            return None
        item = self.rows[index.row()][index.column()]
        if role in {Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole}:
            return value(item)
        if role == Qt.ItemDataRole.UserRole:
            return item
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 4 and item is not None and item < 0:
            return QColor(self.bad)
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() in self.numeric:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        return None


class PathFilter(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.criteria = {}
        self.low = None
        self.high = None
        self.search = ""

    def filterAcceptsRow(self, row, parent):
        data = self.sourceModel().rows[row]
        if any(data[column] != selected for column, selected in self.criteria.items() if column != 11):
            return False
        if 11 in self.criteria and self.criteria[11] not in data[11].split(", "):
            return False
        slack = data[4]
        if self.low is not None and (slack is None or slack < self.low):
            return False
        if self.high is not None and (slack is None or slack > self.high):
            return False
        return not self.search or any(self.search in str(item).casefold() for item in data if item is not None)

    def lessThan(self, left, right):
        a, b = left.data(Qt.ItemDataRole.UserRole), right.data(Qt.ItemDataRole.UserRole)
        if a is None or b is None:
            return a is not None
        return a < b
