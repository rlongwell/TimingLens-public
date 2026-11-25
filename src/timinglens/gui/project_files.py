"""Explicit offline project-file selection; no script execution or AI service."""
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QFileDialog, QHBoxLayout, QLineEdit, QListWidget, QPushButton, QVBoxLayout, QWidget

from .widgets import label


class FileList(QListWidget):
    files_dropped = Signal(object)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():event.acceptProposedAction()

    def dropEvent(self, event):
        self.files_dropped.emit([Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()])
        event.acceptProposedAction()


class ProjectFiles(QWidget):
    requested = Signal(object)

    def __init__(self):
        super().__init__()
        self.base = None
        self.files = FileList();self.files.files_dropped.connect(self.add_files)
        self.use_current = QCheckBox('Use the current timing session with these additional files')
        self.use_current.setEnabled(False)
        self.top = QLineEdit(placeholderText='Optional RTL top module (for report-only hierarchy matching)')
        self.add = QPushButton('Add files…');self.add.clicked.connect(self.browse)
        self.remove = QPushButton('Remove selected');self.remove.clicked.connect(self.remove_selected)
        self.start = QPushButton('Analyze selected files');self.start.clicked.connect(self.submit)
        self.start.setObjectName('Primary')
        self.status = label('', 'Muted');self.status.setWordWrap(True)
        description = label('Add or drop timing reports (or a TimingLens JSON session), RTL, block-design Tcl/BD files, XDC, and optional design-intent JSON. Analysis is local and deterministic. Tcl is never executed.', 'Muted')
        description.setWordWrap(True)
        layout = QVBoxLayout(self);layout.addWidget(description);layout.addWidget(self.files,1)
        buttons=QHBoxLayout();buttons.addWidget(self.add);buttons.addWidget(self.remove);buttons.addStretch()
        layout.addLayout(buttons);layout.addWidget(self.use_current);layout.addWidget(self.top);layout.addWidget(self.start);layout.addWidget(self.status)

    def browse(self):
        names,_=QFileDialog.getOpenFileNames(self,'Add project evidence',filter='Project files (*.rpt *.log *.json *.sv *.v *.svh *.vh *.vhd *.vhdl *.tcl *.xdc *.bd)')
        self.add_files([Path(n) for n in names])

    def add_files(self, paths):
        existing={self.files.item(i).text() for i in range(self.files.count())}
        for path in paths:
            name=str(path.resolve())
            if path.is_file() and name not in existing:self.files.addItem(name);existing.add(name)
        self.status.setText(f'{self.files.count()} files selected. Source revisions and report provenance are retained in the export.')

    def remove_selected(self):
        for item in self.files.selectedItems():self.files.takeItem(self.files.row(item))

    def set_base(self, session):
        self.base=session;self.use_current.setEnabled(True)

    def submit(self):
        paths=[Path(self.files.item(i).text()) for i in range(self.files.count())]
        if not paths:self.status.setText('Add timing evidence and project files first.');return
        self.requested.emit(dict(paths=paths,top=self.top.text().strip() or None,
                                 base=self.base if self.use_current.isChecked() else None))

    def busy(self, active):
        for widget in (self.add,self.remove,self.start,self.files,self.use_current,self.top):widget.setEnabled(not active)
        if not active:self.use_current.setEnabled(self.base is not None)
