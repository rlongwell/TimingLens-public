"""Timing table, filters, path detail, and schematic inspector."""
from collections import defaultdict
import json
from math import isfinite

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QGridLayout, QHBoxLayout, QLineEdit,
                               QPushButton, QSplitter, QTableView, QTabWidget, QVBoxLayout, QWidget)

from ..export.html import value
from ..rtl.correlate import UNKNOWN
from ..rules.library import RULES
from ..visualization.schematic import Schematic
from ..vivado.reports import detail_blocks
from ..timing.coverage import coverage_note
from .widgets import PathFilter, PathTable, label, text_area


class PathsPage(QWidget):
    source_requested = Signal(object)

    def __init__(self):
        super().__init__()
        self.result = None
        self.paths = {}
        self.selected = None
        self.rtl_selection = None
        self.by_path = defaultdict(list)
        self.model = PathTable()
        self.proxy = PathFilter()
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.sortByColumn(4, Qt.SortOrder.AscendingOrder)
        self.table.selectionModel().currentRowChanged.connect(self._selected)
        self.combo = {}
        filters = QGridLayout()
        options = ((1, "Check", "checks"), (8, "Clock pair", "clock pairs"),
                   (9, "RTL module", "modules"), (11, "Diagnostic", "rules"),
                   (10, "Correlation", "confidence levels"))
        for index, (column, title, plural) in enumerate(options):
            combo = QComboBox()
            combo.setMinimumContentsLength(9)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.addItem("All " + plural, None)
            combo.currentIndexChanged.connect(self._filter)
            self.combo[column] = combo
            filters.addWidget(label(title, "Muted"), 0, index)
            filters.addWidget(combo, 1, index)
        self.low = QLineEdit(placeholderText="Min slack (ns)")
        self.high = QLineEdit(placeholderText="Max slack (ns)")
        self.search = QLineEdit(placeholderText="Search paths")
        self.count = label("0 paths", "Muted")
        self.error = label("", "Muted")
        second = QHBoxLayout()
        for widget in (self.low, self.high, self.search):
            widget.textChanged.connect(self._filter)
            second.addWidget(widget)
        second.addWidget(self.count)
        self.details = text_area('report')
        self.raw_path = text_area('report')
        self.raw_paths = {}
        self.properties = text_area('json')
        self.properties.setMaximumHeight(130)
        self.graph = Schematic()
        self.graph.setMinimumHeight(175)
        self.graph.inspected.connect(self.inspect)
        self.open_rtl = QPushButton("Open correlated RTL")
        self.open_rtl.clicked.connect(self._open_rtl)
        self.open_rtl.setEnabled(False)
        self.tabs = QTabWidget()
        graph_panel = QWidget()
        graph_layout = QVBoxLayout(graph_panel)
        buttons = QHBoxLayout()
        for title, action in (("Zoom in", lambda: self.graph.zoom(1.2)),
                              ("Zoom out", lambda: self.graph.zoom(1 / 1.2)), ("Fit", self.graph.fit)):
            button = QPushButton(title)
            button.clicked.connect(action)
            buttons.addWidget(button)
        buttons.addStretch()
        buttons.addWidget(self.open_rtl)
        graph_layout.addLayout(buttons)
        graph_layout.addWidget(self.graph, 1)
        graph_layout.addWidget(self.properties)
        self.tabs.addTab(graph_panel, "Schematic")
        self.tabs.addTab(self.details, "Timing and diagnostics")
        self.tabs.addTab(self.raw_path, "Raw Vivado path")
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.table)
        split.addWidget(self.tabs)
        split.setSizes([310, 415])
        layout = QVBoxLayout(self)
        layout.addLayout(filters)
        layout.addLayout(second)
        layout.addWidget(self.error)
        self.error.hide()
        layout.addWidget(split, 1)

    def theme(self, colors):
        self.model.bad = colors["bad"]
        self.table.viewport().update()
        self.graph.theme(colors)

    def load(self, result):
        self.result = result
        self.paths = {p.id: p for p in result.session.paths}
        self.raw_paths = {}
        for kind in ("setup", "hold"):
            self.raw_paths.update(detail_blocks(result.session.reports.get(f"{kind}-paths.rpt", "")))
        self.by_path.clear()
        for finding in result.findings:
            self.by_path[finding.path_id].append(finding)
        self.model.populate(result)
        for column, combo in self.combo.items():
            title = combo.itemText(0)
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(title, None)
            items = ({rule for row in self.model.rows for rule in row[column].split(", ") if rule in RULES}
                     if column == 11 else {row[column] for row in self.model.rows if row[column] is not None})
            for item in sorted(items):
                combo.addItem(f"{item} · {RULES[item].title}" if column == 11 else item, item)
            combo.blockSignals(False)
        self._filter()
        widths = (62, 66, 162, 164, 96, 84, 84, 63, 108, 118, 106, 95)
        for column, width in enumerate(widths):
            self.table.setColumnWidth(column, max(width, self.table.horizontalHeader().sectionSizeHint(column)))
        if self.proxy.rowCount():
            self.table.selectRow(0)
        else:
            self._display(None)

    def _filter(self):
        limits = []
        try:
            for widget in (self.low, self.high):
                raw = widget.text().strip()
                value_ = float(raw) if raw else None
                if value_ is not None and not isfinite(value_):
                    raise ValueError
                limits.append(value_)
            if all(x is not None for x in limits) and limits[0] > limits[1]:
                raise ValueError
        except ValueError:
            self.error.setText("Enter finite slack bounds with minimum at or below maximum.")
            self.error.show()
            return
        self.error.hide()
        self.proxy.beginFilterChange()
        self.proxy.criteria = {key: combo.currentData() for key, combo in self.combo.items() if combo.currentData()}
        self.proxy.low, self.proxy.high = limits
        self.proxy.search = self.search.text().strip().casefold()
        self.proxy.endFilterChange(PathFilter.Direction.Rows)
        self.count.setText(f"{self.proxy.rowCount()} paths")
        if not self.proxy.rowCount():
            self._display(None)
        elif not self.table.currentIndex().isValid():
            self.table.selectRow(0)

    def goto(self, path_id):
        for combo in self.combo.values():
            combo.setCurrentIndex(0)
        for field in (self.low, self.high, self.search):
            field.clear()
        for row in range(self.proxy.rowCount()):
            if self.proxy.index(row, 0).data() == path_id:
                self.table.selectRow(row)
                self.table.scrollTo(self.proxy.index(row, 0))
                break

    def _selected(self, current, previous):
        if current.isValid():
            self._display(self.paths.get(self.proxy.index(current.row(), 0).data()))

    def _display(self, path):
        self.selected = path
        self.rtl_selection = None
        self.open_rtl.setText("Open correlated RTL")
        self.open_rtl.setEnabled(path is not None)
        self.graph.set_path(self.result.session if self.result else None, path)
        self.properties.setPlainText("Select a cell or net to inspect its measured properties." if path else "")
        self.raw_path.setPlainText(self.raw_paths.get(path.id, "Raw Vivado path unavailable.") if path else "")
        if not path:
            self.details.setPlainText("No collected path matches the current view.")
            return
        association = self.result.paths[path.id]
        lines = [
            f"{path.id} · {path.path_type or path.analysis.title()} · {value(path.corner)}",
            f"{value(path.startpoint)} → {value(path.endpoint)}",
            f"Slack {value(path.slack_ns, ' ns')}   ·   Requirement {value(path.requirement_ns, ' ns')}",
            f"Arrival {value(path.arrival_ns, ' ns')}   ·   Required {value(path.required_ns, ' ns')}",
            f"Logic {value(path.logic_ns, ' ns')}   ·   Route {value(path.routing_ns, ' ns')}   ·   {value(path.levels)} levels",
            f"Skew {value(path.skew_ns, ' ns')}   ·   Uncertainty {value(path.uncertainty_ns, ' ns')}",
            f"Clock pair {value(path.start_clock)} → {value(path.end_clock)}   ·   {self.result.graph.delay_class(path)}",
            coverage_note([self.result.coverage[path.id]]),
            "", f"Source correlation {association.confidence.label} · {value(association.module)}",
            association.reason,
        ]
        if association.file:
            lines.append(f"{association.file}" + (f":{association.first}" if association.first else ""))
        for finding in self.by_path[path.id]:
            lines.extend(("", f"{finding.rule} · {RULES[finding.rule].title}", *finding.evidence))
        self.details.setPlainText("\n".join(lines))

    def _open_rtl(self):
        if self.selected:
            self.source_requested.emit(self.rtl_selection or self.result.paths[self.selected.id])

    def inspect(self, kind, name):
        session = self.result.session
        pool = {"cell": session.cells, "net": session.nets, "pin": session.pins}
        obj = pool[kind][name]
        info = obj.model_dump(exclude_none=True, exclude_defaults=True)
        self.rtl_selection = None
        self.open_rtl.setText("Open correlated RTL")
        if kind == "cell":
            source = self.result.cells.get(name, UNKNOWN)
            self.rtl_selection = source
            self.open_rtl.setText("Open cell RTL")
            info["source_correlation"] = f"{source.confidence.label}: {source.reason}"
        if self.selected:
            info["path_arcs"] = [arc.model_dump(exclude_none=True) for arc in self.selected.arcs if arc.resource == name]
        self.properties.setPlainText(json.dumps(info, indent=2, ensure_ascii=False))
