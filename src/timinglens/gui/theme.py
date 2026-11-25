"""Application colors and local desktop preferences."""
import json
import os
from pathlib import Path

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QTableView

from ..timing.io import atomic_text

DARK = dict(bg="#252525", sidebar="#202020", panel="#303030", raised="#393939", border="#505050",
            text="#eeeeee", muted="#b9b9b9", accent="#8bb8ff", accent_bg="#303b4d",
            bad="#ffaaa2", keyword="#a6c8ff", literal="#f5cb93", comment="#acacac", operator="#e0b3ef", identifier="#b1dce0",
            warning="#f0c477", success="#b4d9a0", diff_add_bg="#2b3d2e", diff_remove_bg="#493133")
LIGHT = dict(bg="#f3f3f2", sidebar="#e7e7e5", panel="#ffffff", raised="#f0f0ee", border="#bcbcb9",
             text="#202020", muted="#545454", accent="#285b9b", accent_bg="#dce8f8",
             bad="#9f2d24", keyword="#284f99", literal="#805416", comment="#5f645f", operator="#763a83", identifier="#205d62",
             warning="#815000", success="#28602b", diff_add_bg="#e2efdf", diff_remove_bg="#f9e3e2")


def settings_path() -> Path:
    root = os.environ.get("TIMINGLENS_REPO_ROOT")
    if root:
        return Path(root) / ".settings" / "gui.json"
    candidate = Path(__file__).resolve().parents[3]
    if (candidate / "pyproject.toml").is_file():
        return candidate / ".settings" / "gui.json"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "timinglens" / ".settings" / "gui.json"


def load_settings() -> dict:
    try:
        value = json.loads(settings_path().read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(settings: dict) -> None:
    atomic_text(settings_path(), json.dumps(settings, indent=2) + "\n")


def apply_theme(app: QApplication, dark: bool) -> dict:
    c = DARK if dark else LIGHT
    palette = QPalette()
    for role, name in {
        "Window": "bg", "WindowText": "text", "Base": "panel", "AlternateBase": "raised",
        "Text": "text", "Button": "raised", "ButtonText": "text", "Highlight": "accent_bg",
        "HighlightedText": "text", "ToolTipBase": "panel", "ToolTipText": "text", "Link": "accent",
        "PlaceholderText": "muted",
    }.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(c[name]))
    app.setPalette(palette)
    app.setProperty('timinglens_colors', c)
    app.setStyleSheet(f"""
        QWidget {{ font-family: "Inter", "Noto Sans", sans-serif; font-size: 16px; }}
        QWidget#Sidebar {{ background: {c['sidebar']}; border-right: 1px solid {c['border']}; }}
        QLabel#Title {{ font-size: 26px; font-weight: 650; }}
        QLabel#Brand {{ font-size: 21px; font-weight: 700; color: {c['accent']}; }}
        QLabel#Muted {{ color: {c['muted']}; }}
        QLabel#Section {{ font-size: 16px; font-weight: 600; }}
        QLabel#Metric {{ font-size: 23px; font-weight: 600; }}
        QFrame#Card {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 8px; }}
        QPushButton {{ background: {c['raised']}; border: 1px solid {c['border']}; border-radius: 5px;
                       padding: 7px 12px; }}
        QPushButton:hover, QPushButton:checked {{ background: {c['accent_bg']}; border-color: {c['accent']}; }}
        QPushButton#Nav {{ text-align: left; border-color: transparent; background: transparent; }}
        QPushButton#Nav:checked {{ color: {c['accent']}; background: {c['accent_bg']}; }}
        QPushButton#Primary {{ background: {c['accent_bg']}; border-color: {c['accent']}; }}
        QPushButton:disabled {{ color: {c['muted']}; }}
        QLineEdit, QComboBox, QSpinBox {{ background: {c['panel']}; border: 1px solid {c['border']};
                        padding: 6px; border-radius: 4px; min-height: 16px; }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {c['accent']}; }}
        QPlainTextEdit, QTextBrowser, QTreeWidget, QTableView, QGraphicsView {{
            background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 5px; }}
        QPlainTextEdit#CodeEditor {{ font-family: "IBM Plex Mono", "DejaVu Sans Mono", monospace; font-size: 16px; }}
        QHeaderView::section {{ background: {c['raised']}; padding: 7px; border: 0;
                                border-bottom: 1px solid {c['border']}; text-align: left; }}
        QTreeWidget#IssueList::item {{ padding-top: 6px; padding-bottom: 6px; }}
        QTabBar::tab {{ padding: 7px 14px; }}
        QTabBar::tab:selected {{ color: {c['accent']}; border-bottom: 2px solid {c['accent']}; }}
        QSplitter::handle {{ background: {c['bg']}; }}
        QToolTip {{ border: 1px solid {c['border']}; }}
    """)
    for widget in app.allWidgets():
        if isinstance(widget, QTableView):
            header = widget.horizontalHeader()
            for column in range(header.count()):
                header.resizeSection(column, max(header.sectionSize(column), header.sectionSizeHint(column)))
        highlighter = getattr(widget, 'syntax_highlighter', None)
        if highlighter is not None:
            highlighter.set_colors(c)
    return c
