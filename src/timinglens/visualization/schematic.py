"""Qt path schematic with a fixed left-to-right layout following captured arcs."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QBrush, QPainter, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsView

from ..export.html import value
from ..timing.models import Session, TimingPath


@dataclass
class Node:
    name: str
    cell: str | None
    pins: list[str]


def layout(session: Session, path: TimingPath) -> tuple[list[Node], list]:
    nodes: list[Node] = []
    for name in path.pins:
        pin = session.pins[name]
        if nodes and pin.cell and nodes[-1].cell == pin.cell:
            nodes[-1].pins.append(name)
        else:
            nodes.append(Node(pin.cell or name, pin.cell, [name]))
    if not nodes:
        nodes = [Node(name, name, []) for name in path.cells]
        return nodes, [None] * max(0, len(nodes) - 1)
    arc_by_pair = {(arc.source, arc.sink): arc for arc in path.arcs if arc.kind == "net"}
    edges = [arc_by_pair.get((left.pins[-1], right.pins[0])) for left, right in zip(nodes, nodes[1:])]
    return nodes, edges


class Schematic(QGraphicsView):
    inspected = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.scene().selectionChanged.connect(self._select)
        self.session = self.path = self.colors = None

    def set_path(self, session, path):
        self.session, self.path = session, path
        self.draw()
        self.fit()
        if self.path and self.transform().m11() < 1.0:
            self.resetTransform()
            self.scale(1.0, 1.0)
            self.horizontalScrollBar().setValue(0)

    def theme(self, colors):
        self.colors = colors
        grip = self.mapToScene(self.viewport().rect().center())
        self.draw()
        self.centerOn(grip)

    def fit(self):
        if self.scene().items():
            self.resetTransform()
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def zoom(self, factor):
        if self.transform().m11() * factor <= 4 and (factor > 1 or self.transform().m11() > .025):
            self.scale(factor, factor)

    def wheelEvent(self, event):
        if not event.angleDelta().y():
            return super().wheelEvent(event)
        self.zoom(1.15 if event.angleDelta().y() > 0 else 1 / 1.15)
        event.accept()

    def _select(self):
        items = self.scene().selectedItems()
        if items:
            self.inspected.emit(items[0].data(0), items[0].data(1))

    def draw(self):
        scene = self.scene()
        scene.clear()
        if not self.colors:
            return
        c = self.colors
        scene.setBackgroundBrush(QColor(c["panel"]))
        if not self.path or not (self.path.pins or self.path.cells):
            item = scene.addSimpleText("Ordered hardware is unavailable for this path.")
            item.setBrush(QColor(c["muted"]))
            scene.setSceneRect(scene.itemsBoundingRect().adjusted(-20, -20, 20, 20))
            return
        nodes, edges = layout(self.session, self.path)
        delays = [arc.delay_ns for arc in self.path.arcs if arc.delay_ns is not None]
        peak = max(delays, default=0)
        width, step, y, inner = 168, 300, 100, 50

        def text(content, x, ypos, role="text", size=10, parent=None):
            item = scene.addSimpleText(content, QFont("Inter", size))
            item.setBrush(QColor(c[role]))
            if parent:
                item.setParentItem(parent)
            item.setPos(x, ypos)
            return item

        for i, node in enumerate(nodes):
            x = 15 + i * step
            cell = self.session.cells.get(node.cell or "")
            internal = [a for a in self.path.arcs if a.kind == "cell" and a.resource == node.cell
                        and a.source in node.pins and a.sink in node.pins and a.delay_ns is not None]
            delay = sum(a.delay_ns for a in internal) if internal else None
            role = "Startpoint" if i == 0 else "Endpoint" if i == len(nodes) - 1 else f"Stage {i}"
            text(role, x, y - 27, "muted")
            rectangle = scene.addRect(x, y, width, 86, QPen(QColor(c["accent"] if delay and delay >= peak * .8 else c["border"])),
                                      QBrush(QColor(c["raised"])))
            kind = "cell" if cell else "pin"
            rectangle.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
            rectangle.setData(0, kind)
            rectangle.setData(1, node.name)
            rectangle.setToolTip(node.name)
            text(cell.primitive if cell else "Port / pin", x + 10, y + 7, "accent", 10, rectangle)
            name = node.name.rsplit("/", 1)[-1]
            if len(name) > 21:
                name = name[:19] + "…"
            text(name, x + 10, y + 29, "text", 10, rectangle)
            text(f"{value(delay, ' ns')} · cell arc" if delay is not None else
                 (cell.location if cell and cell.location else " "), x + 10, y + 53, "muted", 9, rectangle)
            if i == len(edges):
                continue
            arc = edges[i]
            left, right = x + width, x + step
            if arc:
                dominant = arc.delay_ns is not None and peak > 0 and arc.delay_ns >= peak * .8
                pen = QPen(QColor(c["accent"] if dominant else c["muted"]), 4 if dominant else 2)
                line = scene.addLine(left, y + inner, right, y + inner, pen)
                line.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
                line.setData(0, "net")
                line.setData(1, arc.resource)
                line.setToolTip(f"{arc.resource}\n{arc.source} → {arc.sink}\n{value(arc.delay_ns, ' ns')}")
                scene.addLine(right - 9, y + inner - 5, right, y + inner, pen)
                scene.addLine(right - 9, y + inner + 5, right, y + inner, pen)
                net_name = arc.resource.rsplit("/", 1)[-1]
                text(net_name[:15] + ("…" if len(net_name) > 15 else ""), left + 8, y + 19, "muted", 9)
                text(value(arc.delay_ns, " ns"), left + 12, y + 52, "accent" if dominant else "muted", 9)
            else:
                text("Arc unavailable", left + 9, y + 41, "muted", 9)
        scene.setSceneRect(scene.itemsBoundingRect().adjusted(-14, -22, 14, 22))
