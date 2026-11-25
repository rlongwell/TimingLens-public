"""A small, explicit starting point for the desktop workflow."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from .widgets import label


class Home(QWidget):
    design_requested = Signal()
    session_requested = Signal()
    example_requested = Signal()
    resume_requested = Signal()

    def __init__(self):
        super().__init__()
        body = QVBoxLayout(self)
        body.setContentsMargins(0, 16, 0, 0)
        body.setSpacing(20)
        title = label('Find the path. Understand the cause. Test the fix.', 'Title')
        title.setWordWrap(True); body.addWidget(title)
        intro = label('Start with your design evidence, or explore a complete counter experiment.', 'Muted')
        intro.setWordWrap(True)
        body.addWidget(intro)
        choices = QHBoxLayout()
        choices.setSpacing(16)
        self.design = self.card(choices, 'YOUR DESIGN', 'Analyze a design',
            'Choose a Vivado project or checkpoint, or add timing reports with RTL and constraints.',
            'Choose design files…', self.design_requested)
        self.example = self.card(choices, 'GUIDED EXAMPLE', 'Try a counter fix',
            'Review a small RTL change, validate its behavior, then build both versions at 250 MHz.',
            'Review counter experiment →', self.example_requested)
        body.addLayout(choices)
        workflow = QFrame()
        workflow.setObjectName('Card')
        steps = QHBoxLayout(workflow)
        steps.setContentsMargins(20, 20, 20, 20)
        for title, detail in (
            ('1  Add evidence', 'Reports + RTL + XDC\nor a Vivado design'),
            ('2  Understand the failure', 'Timing paths, source links\nand targeted recommendations'),
            ('3  Test and compare', 'Isolated candidates, validation\nand timing / area results')):
            column = QVBoxLayout()
            column.addWidget(label(title, 'Section'))
            note = label(detail, 'Muted'); note.setWordWrap(True)
            column.addWidget(note); steps.addLayout(column, 1)
        body.addWidget(workflow)
        self.resume = QPushButton('Return to current analysis →')
        self.resume.clicked.connect(self.resume_requested.emit)
        self.resume.hide(); body.addWidget(self.resume)
        row = QHBoxLayout()
        self.session = QPushButton('Open saved analysis…')
        self.session.clicked.connect(self.session_requested.emit)
        row.addWidget(self.session); row.addStretch()
        body.addLayout(row)
        body.addStretch()
        note = label('Report analysis runs locally. New routed experiments require Vivado and Verilator.\nExperiment results retain the source change, validation, logs and reports for review.', 'Muted')
        note.setWordWrap(True); body.addWidget(note)

    def card(self, row, eyebrow, title, description, action, signal):
        card = QFrame(); card.setObjectName('Card')
        layout = QVBoxLayout(card); layout.setContentsMargins(22, 22, 22, 22); layout.setSpacing(14)
        layout.addWidget(label(eyebrow, 'Muted'))
        layout.addWidget(label(title, 'Metric'))
        text = label(description); text.setWordWrap(True); layout.addWidget(text)
        layout.addStretch()
        button = QPushButton(action); button.setObjectName('Primary')
        button.clicked.connect(signal.emit); layout.addWidget(button)
        row.addWidget(card, 1)
        return button

    def busy(self, active):
        for button in (self.design, self.example, self.session):
            button.setEnabled(not active)
