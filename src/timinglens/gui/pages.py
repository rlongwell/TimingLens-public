"""Dashboard, ranked issues, and Vivado execution views."""
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, Signal, Slot
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
                               QLineEdit, QProgressBar, QPushButton, QSpinBox, QSplitter, QTableWidget, QTabWidget,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QTextBrowser, QApplication, QScrollArea)

from ..analysis.engine import recommendation
from ..export.html import value
from ..rules.library import RULES
from ..syntax import file_syntax
from ..vivado.runner import Request
from .widgets import fill_table, label, set_syntax, text_area
from .fix_view import pages as fix_pages


class Dashboard(QWidget):
    review_requested = Signal()

    def __init__(self):
        super().__init__()
        self.project = label("No timing session open", "Section")
        self.project.setWordWrap(True)
        self.metadata = label("Open a Vivado project, checkpoint, or TimingLens JSON session.", "Muted")
        self.metadata.setWordWrap(True)
        self.next_action = label('Open timing evidence to select an investigation.', 'Section')
        self.next_action.setWordWrap(True)
        self.review = QPushButton('Review first issue')
        self.review.setEnabled(False)
        self.review.clicked.connect(self.review_requested)
        self.metrics = {}
        cards = QGridLayout()
        titles = ("Worst setup slack", "Setup TNS", "Setup failing endpoints", "Collected failing paths",
                  "Worst hold slack", "Hold TNS", "Hold failing endpoints", "Diagnostic findings", "Bottleneck groups")
        for i, title in enumerate(titles):
            frame = QFrame()
            frame.setObjectName("Card")
            frame.setMinimumHeight(82)
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(14, 11, 14, 11)
            layout.addWidget(label(title, "Muted"))
            field = label("Unavailable", "Metric")
            layout.addWidget(field)
            self.metrics[title] = field
            cards.addWidget(frame, i // 3, i % 3)
        self.clocks, self.clock_pairs = QTableWidget(), QTableWidget()
        for table in (self.clocks, self.clock_pairs):
            table.verticalHeader().hide()
            table.horizontalHeader().setStretchLastSection(True)
            table.setAlternatingRowColors(True)
        clock_tabs = QTabWidget()
        clock_tabs.setMinimumHeight(150)
        clock_tabs.addTab(self.clocks, "Definitions")
        clock_tabs.addTab(self.clock_pairs, "Interactions")
        self.note = label("", "Muted")
        self.note.setWordWrap(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(body)
        outer = QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); outer.addWidget(scroll)
        layout.addWidget(self.project)
        layout.addWidget(self.metadata)
        layout.addWidget(self.next_action)
        layout.addWidget(self.review, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addSpacing(5)
        layout.addLayout(cards)
        layout.addSpacing(5)
        layout.addWidget(label("Clock domains", "Section"))
        layout.addWidget(clock_tabs, 1)
        self.summary_report = QComboBox()
        self.summary_report.addItem("Available Vivado reports")
        self.summary_report.activated.connect(self._show_report)
        self.report = text_area('report')
        self.report.setMaximumHeight(180)
        self.report.hide()
        layout.addWidget(self.summary_report)
        layout.addWidget(self.report)
        layout.addWidget(self.note)
        self.reports = {}

    def load(self, result):
        session = result.session
        setup, hold = (session.summary.get(kind) for kind in ("setup", "hold"))
        self.project.setText(session.top or session.name)
        self.project.setToolTip(session.name)
        first = result.investigations[0] if result.investigations else None
        self.review.setEnabled(bool(first or result.project_plans))
        if first:
            self.next_action.setText(f'Investigate first: {first.title}\nMeasured: {value(first.worst_slack_ns)} ns worst slack · '
                                     f'{first.complete_paths}/{len(first.path_ids)} paths with complete detail. '
                                     'Source causality and timing benefit require validation.')
        elif result.project_plans:
            self.next_action.setText('Review first: '+result.project_plans[0].title)
        else:
            self.next_action.setText('No supported investigation in the captured evidence. Check coverage and design-wide status below.')
        if any((summary.failing_endpoints or 0) > 0 for summary in session.summary.values()) or result.failing_paths:
            status = "Timing violations found"
        elif setup and hold and setup.failing_endpoints == hold.failing_endpoints == 0:
            status = "No failing setup or hold endpoints"
        else:
            status = "Design-wide timing status unavailable"
        self.metadata.setText(
            f"{value(session.part)}  ·  Vivado {value(session.vivado)}  ·  {session.stage.replace('_',' ').title()}"
            f"  ·  {status}" + (f"  ·  {session.run}" if session.run else ""))
        incomplete = sum(not c.complete for c in result.coverage.values())
        if incomplete:
            self.metadata.setText(self.metadata.text() + f'\nDetailed path evidence is incomplete on {incomplete}/{len(session.paths)} captured paths; inspect coverage notes below.')
        for kind, summary, first, total, last in (
            ("setup", setup, "Worst setup slack", "Setup TNS", "Setup failing endpoints"),
            ("hold", hold, "Worst hold slack", "Hold TNS", "Hold failing endpoints"),
        ):
            self.metrics[first].setText(value(summary.worst_slack_ns if summary else None, " ns"))
            self.metrics[total].setText(value(summary.total_negative_slack_ns if summary else None, " ns"))
            self.metrics[last].setText(value(summary.failing_endpoints if summary else None))
        self.metrics["Collected failing paths"].setText(str(result.failing_paths))
        self.metrics["Diagnostic findings"].setText(str(len(result.findings)))
        self.metrics["Bottleneck groups"].setText(str(len(result.groups)))
        fill_table(self.clocks, ("Clock", "Period", "Waveform (ns)", "Generated", "Source"),
                   ((clock.name, value(clock.period_ns, " ns"), ", ".join(map(str, clock.waveform_ns)) or "Unavailable",
                     value(clock.generated), ", ".join(clock.sources) or "Unavailable") for clock in session.clocks))
        keys = ("source", "destination", "worst_slack_ns", "total_negative_slack_ns",
                "failing_endpoints", "classification", "constraints")
        fill_table(self.clock_pairs, ("Launch", "Capture", "Worst (ns)", "TNS (ns)", "Failing endpoints",
                                      "Classification", "Constraints"),
                   (tuple(pair.get(key) or "Unavailable" for key in keys) for pair in session.clock_interactions))
        note = (f"{len(session.paths)} paths collected. Design-wide setup and hold totals come from Vivado."
                if session.summary else f"{len(session.paths)} paths collected. Design-wide totals are unavailable.")
        if session.stage == "synthesized":
            note += " Routing delays are synthesis estimates."
        note += "\n" + result.coverage_note
        if result.warnings:
            note += "\n" + "\n".join(result.warnings[:5])
        self.note.setText(note)
        self.reports = session.reports
        self.summary_report.clear()
        self.summary_report.addItem("Available Vivado reports")
        self.summary_report.addItems(sorted(self.reports))
        self.report.hide()

    def _show_report(self, index):
        key = self.summary_report.itemText(index)
        set_syntax(self.report, file_syntax(key))
        self.report.setPlainText(self.reports.get(key, ""))
        self.report.setVisible(key in self.reports)


class Issues(QWidget):
    path_requested = Signal(str)
    source_requested = Signal(object)
    experiment_requested = Signal(object)
    auto_project_requested = Signal()
    example_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.analysis=None;self.external_busy=False
        self.proof_worker = None
        self.proof_messages = {}
        self.groups = {}
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(("Issue", "Slack (ns)", "Paths"))
        self.tree.setObjectName('IssueList')
        self.tree.setMinimumWidth(260)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.currentItemChanged.connect(self._show)
        self.tree.itemActivated.connect(self._open)
        self.description = QTextBrowser()
        self.evidence = QTextBrowser()
        self.validation = QTextBrowser()
        self.preview = QTextBrowser()
        self.details = QTabWidget()
        for title, widget in (('Suggested change',self.description),('Evidence',self.evidence),('Tcl & validation',self.validation),('Change preview',self.preview)):
            set_syntax(widget, 'rich-tcl' if widget is self.validation else 'rich-diff')
            widget.document().setDocumentMargin(14)
            widget.setOpenExternalLinks(False)
            widget.setOpenLinks(False)
            widget.anchorClicked.connect(self._source_link)
            self.details.addTab(widget,title)
        self.description.setPlainText("Select a bottleneck to inspect measured evidence and recommendations.")
        self.candidates = QComboBox()
        self.candidates.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.candidates.setMinimumContentsLength(24)
        self.candidates.currentIndexChanged.connect(self._candidate)
        self.candidate_texts = []
        self.candidate_plans = []
        self.current_plan = None
        self.summary = label('', 'Section')
        self.context = label('', 'Muted');self.context.setWordWrap(True)
        self.open = QPushButton("Open timing path")
        self.open.clicked.connect(lambda: self._open(self.tree.currentItem()))
        self.open.setEnabled(False)
        self.copy_tcl = QPushButton('Copy Tcl')
        self.copy_tcl.setEnabled(False)
        self.copy_tcl.setToolTip('Copy the reviewable commands; nothing is executed.')
        self.copy_tcl.clicked.connect(self._copy_tcl)
        self.copy_diff = QPushButton('Copy diff')
        self.copy_diff.setEnabled(False)
        self.copy_diff.setToolTip('Copies the selected expression alternative; no source file is changed.')
        self.copy_diff.clicked.connect(self._copy_diff)
        self.alternative = QComboBox()
        self.alternative.setToolTip('Choose one independent expression diff to copy.')
        self.alternative.setVisible(False)
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.addWidget(label("2. Review a candidate", "Section"))
        panel_layout.addWidget(self.context)
        panel_layout.addWidget(self.candidates)
        trial=QHBoxLayout();self.try_experiment=QPushButton('Try this experiment');self.try_experiment.setObjectName('Primary')
        self.try_experiment.clicked.connect(self._try_experiment);trial.addWidget(self.try_experiment)
        self.experiment_note=label('Select a supported example recommendation.','Muted');self.experiment_note.setWordWrap(True);trial.addWidget(self.experiment_note,1)
        panel_layout.addLayout(trial)
        panel_layout.addWidget(self.details,1)
        actions = QHBoxLayout();actions.addWidget(self.alternative);actions.addStretch();actions.addWidget(self.copy_diff);actions.addWidget(self.copy_tcl);actions.addWidget(self.open)
        panel_layout.addLayout(actions)
        left = QWidget();left_layout = QVBoxLayout(left);left_layout.setContentsMargins(0,0,0,0)
        left_layout.addWidget(label('1. Choose an issue', 'Section'))
        self.filter = QLineEdit(placeholderText='Filter issue, path, signal or rule')
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._filter)
        left_layout.addWidget(self.filter)
        left_layout.addWidget(self.tree,1)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(panel)
        splitter.setStretchFactor(0,0);splitter.setStretchFactor(1,1)
        splitter.setSizes([270, 870])
        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        guidance = label('Start with the suggested change. Use Evidence and Tcl & validation to check it before editing.', 'Muted')
        guidance.setWordWrap(True)
        layout.addWidget(guidance)
        examples=QHBoxLayout();self.example=QComboBox()
        for title,name in [('Deep logic','deep'),('Priority mux','priority'),('High fanout','fanout')]:self.example.addItem(title,name)
        self.open_example=QPushButton('Open example evidence');self.open_example.clicked.connect(lambda:self.example_requested.emit(self.example.currentData()))
        examples.addWidget(self.example);examples.addWidget(self.open_example);examples.addStretch();layout.addLayout(examples)
        layout.addSpacing(8)
        layout.addWidget(splitter,1)
        self._update_experiment()

    def load(self, result):
        self.analysis=result
        self.groups = {group.id: group for group in result.investigations}
        self.raw_groups = {group.id: group for group in result.groups}
        self.source_texts = result.source_index.texts
        self.fix_plans = result.fix_plans
        self.project_plans = {f'project-{i}':p for i,p in enumerate(result.project_plans)}
        path_label = 'path' if result.failing_paths == 1 else 'paths'
        noun = 'investigation' if len(result.investigations) == 1 else 'investigations'
        self.summary.setText(f'{len(result.investigations)} {noun}  ·  {result.failing_paths} captured failing {path_label}  ·  {len(result.project_plans)} project reviews')
        by_id = {path.id: path for path in result.session.paths}
        self.tree.clear()
        for group in result.investigations:
            short_titles = {'TL-A':'Deep logic chain', 'TL-B':'Priority / mux chain', 'TL-C':'Slow high-fanout net',
                            'TL-D':'Long routing delay', 'TL-E':'Cascaded arithmetic', 'TL-F':'RAM interface',
                            'TL-G':'Clock / constraint review', 'TL-H':'Timing failure to inspect'}
            issue = " + ".join(short_titles.get(rule, RULES[rule].title) for rule in group.rules)
            if group.plans and any(e.id == "pipeline:shared-source" for e in group.plans[0].evidence_links):
                issue = "DSP pipeline"
            item = QTreeWidgetItem((issue, value(group.worst_slack_ns), str(len(group.path_ids))))
            item.setToolTip(0,', '.join(group.rules)+'\n'+group.title)
            item.setData(0, Qt.ItemDataRole.UserRole, group.id)
            self.tree.addTopLevelItem(item)
            for path_id in group.path_ids:
                path = by_id[path_id]
                child = QTreeWidgetItem((f"{path_id} · {path.analysis.title()}", value(path.slack_ns), ''))
                child.setToolTip(0,f'{path.startpoint} → {path.endpoint}')
                child.setData(0, Qt.ItemDataRole.UserRole, path_id)
                item.addChild(child)
        for key, plan in self.project_plans.items():
            item = QTreeWidgetItem((plan.title, 'Review', ''))
            item.setToolTip(0,plan.title+'\n'+plan.scope)
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            self.tree.addTopLevelItem(item)
        for index, width in enumerate((150, 75, 45)):
            self.tree.setColumnWidth(index, width)
        if result.groups or self.project_plans:
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        else:
            self.description.setPlainText("No supported diagnostic findings in the supplied evidence. Missing timing reports or paths do not establish a clean design.")
        self._filter(self.filter.text())

    def _show(self, item, previous):
        if item is None:
            self.open.setEnabled(False)
            self.candidate_plans = [];self.candidate_texts = []
            self.candidates.clear();self._candidate(-1)
            self.context.clear()
            return
        group_item = item.parent() or item
        group = self.groups.get(group_item.data(0, Qt.ItemDataRole.UserRole))
        if group:
            noun = 'path' if len(group.path_ids)==1 else 'paths'
            self.context.setText(f'MEASURED · {len(group.path_ids)} {noun} · Worst slack {value(group.worst_slack_ns)} ns\n'
                                 + ', '.join(group.rules) + ' are symptoms of this same captured path set.')
            plans = group.plans
            if plans:
                shared = next((e for e in plans[0].evidence_links if e.id == "pipeline:shared-source"), None)
                if shared:
                    self.context.setText(f"{shared.statement} Worst slack {value(group.worst_slack_ns)} ns.")
            titles = [p.title for p in plans] + ['Measured group evidence and general guidance']
            texts = [fix_pages(p) for p in plans] + ['\n\n'.join(recommendation(self.raw_groups[i]) for i in group.group_ids)]
            self.candidate_plans = [*plans,None]
        elif plan := self.project_plans.get(group_item.data(0, Qt.ItemDataRole.UserRole)):
            self.context.setText('Project review  ·  '+plan.scope)
            titles, texts = [plan.title], [fix_pages(plan)]
            self.candidate_plans = [plan]
        else:
            titles, texts = [], []
            self.candidate_plans = []
        self.candidates.blockSignals(True)
        self.candidates.clear(); self.candidates.addItems(titles)
        self.candidate_texts = texts
        self.candidates.blockSignals(False)
        self._candidate(0)
        self.open.setEnabled(bool(group and group.path_ids))

    def _candidate(self, index):
        self.current_plan = self.candidate_plans[index] if 0 <= index < len(self.candidate_plans) else None
        self.candidates.setToolTip(self.current_plan.title if self.current_plan else '')
        self.copy_tcl.setEnabled(bool(self.current_plan and self.current_plan.commands))
        self.copy_tcl.setText('Copy Tcl')
        diffs = [c for c in self.current_plan.changes if c.unified_diff] if self.current_plan else []
        self.copy_diff.setEnabled(bool(diffs));self.copy_diff.setText('Copy diff')
        self.alternative.clear()
        for i, change in enumerate(diffs, 1):
            self.alternative.addItem(f'Expression {i}', change.unified_diff)
        self.alternative.setVisible(len(diffs) > 1)
        text = self.candidate_texts[index] if 0 <= index < len(self.candidate_texts) else ''
        if isinstance(text,tuple):
            for widget, html in zip((self.description,self.evidence,self.validation,self.preview),text):widget.setHtml(html)
        else:
            self.description.setPlainText(text);self.evidence.clear();self.validation.clear();self.preview.clear()
        self.details.setTabEnabled(1,isinstance(text,tuple))
        self.details.setTabEnabled(2,isinstance(text,tuple))
        self.details.setTabEnabled(3,bool(self.current_plan and self.current_plan.changes))
        self.details.setCurrentIndex(0)
        self._update_experiment()

    def set_external_busy(self,value):
        self.external_busy=value;self.open_example.setEnabled(not value);self._update_experiment()

    def _update_experiment(self):
        from ..experiments.recommendation import eligibility
        if self.current_plan and self.current_plan.id == "rtl.redistribute_arithmetic":
            key = self.current_plan.changes[0].source_sha256
            self.try_experiment.setText("Verify RTL fix…")
            self.try_experiment.setEnabled(not self.external_busy and self.proof_worker is None)
            self.experiment_note.setText(self.proof_messages.get(key, "Save the generated RTL and prove its cycle latency in an isolated copy."))
            return
        if self.current_plan and self.current_plan.id == "bd.multiplier_dsp":
            self.try_experiment.setText("Run from project…")
            self.try_experiment.setEnabled(not self.external_busy)
            self.experiment_note.setText("Select the matching Vivado project to test the IP change and compare both routes.")
            return
        self.try_experiment.setText("Try this experiment")
        name,reason=eligibility(self.analysis,self.current_plan) if self.analysis else (None,'Open example evidence to select a recommendation.')
        self.try_experiment.setEnabled(name is not None and not self.external_busy)
        ready='Preview the RTL diff, equivalence gate and same-recipe builds.' if self.current_plan and self.current_plan.kind=='rtl_experiment' else 'Preview a fresh baseline and this recipe in isolated copies.'
        self.experiment_note.setText('Wait for the current analysis or experiment.' if self.external_busy else reason or ready)

    def _try_experiment(self):
        if self.current_plan and self.current_plan.id == "bd.multiplier_dsp" and not self.external_busy:
            self.auto_project_requested.emit()
            return
        if self.external_busy or not self.analysis:return
        if self.current_plan and self.current_plan.id == "rtl.redistribute_arithmetic":
            self._verify_pipeline()
            return
        from ..experiments.recommendation import prepare_experiment
        try:self.experiment_requested.emit(prepare_experiment(self.analysis,self.current_plan))
        except (OSError,ValueError) as error:self.experiment_note.setText(str(error))

    def _verify_pipeline(self):
        from uuid import uuid4
        from ..experiments.pipeline_proof import prepare
        from .pipeline_proof import ProofWorker
        if self.proof_worker:
            return
        folder = QFileDialog.getExistingDirectory(self, "Choose where to save the candidate and proof")
        if not folder:
            return
        try:
            candidate = prepare(self.analysis, self.current_plan)
        except ValueError as error:
            self.experiment_note.setText(str(error))
            return
        output = Path(folder) / f"timinglens-proof-{uuid4().hex[:12]}"
        key = self.current_plan.changes[0].source_sha256
        self.proof_worker = ProofWorker(candidate, output, key)
        self.proof_worker.signals.finished.connect(self._proof_finished)
        self.proof_messages[key] = "Proving all output bits for arbitrary input sequences…"
        self._update_experiment()
        QThreadPool.globalInstance().start(self.proof_worker)

    @Slot(str, str)
    def _proof_finished(self, key, message):
        self.proof_worker = None
        self.proof_messages[key] = message
        self._update_experiment()

    def select_experiment(self,plan_id):
        for i in range(self.tree.topLevelItemCount()):
            item=self.tree.topLevelItem(i);group=self.groups.get(item.data(0,Qt.ItemDataRole.UserRole))
            if group and any(p.id==plan_id for p in group.plans):
                self.tree.setCurrentItem(item)
                for j,plan in enumerate(self.candidate_plans):
                    if plan and plan.id==plan_id:self.candidates.setCurrentIndex(j);return

    def _copy_tcl(self):
        if self.current_plan and self.current_plan.commands:
            QApplication.clipboard().setText('\n'.join(self.current_plan.commands))
            self.copy_tcl.setText('Copied')

    def _copy_diff(self):
        if diff := self.alternative.currentData():
            QApplication.clipboard().setText(diff)
            self.copy_diff.setText('Copied')

    def _source_link(self, url):
        from ..rtl.correlate import Association, Confidence
        text = url.toString()
        if not self.current_plan or not text.startswith('tl-source:'):
            return
        try:
            index = int(text.removeprefix('tl-source:'))
            if not 0 <= index < len(self.current_plan.source_candidates):
                return
            location = self.current_plan.source_candidates[index]
        except ValueError:
            return
        if location.file in self.source_texts:
            self.source_requested.emit(Association(Confidence.PARTIAL,
                'Exact source location for review; this is not proof of physical causality.',
                file=location.file, first=location.first, last=location.last))

    def _filter(self, text):
        query = text.casefold()
        visible = []
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            content = item.text(0)+' '+item.toolTip(0)
            content += ' '.join(item.child(j).text(0)+' '+item.child(j).toolTip(0) for j in range(item.childCount()))
            item.setHidden(query not in content.casefold())
            if not item.isHidden():visible.append(item)
        selected = self.tree.currentItem()
        if selected and (selected.parent() or selected).isHidden():
            self.tree.setCurrentItem(visible[0] if visible else None)
        elif selected is None and visible:
            self.tree.setCurrentItem(visible[0])

    def _open(self, item, column=0):
        if item and item.parent():
            self.path_requested.emit(item.data(0, Qt.ItemDataRole.UserRole))
        elif item and (group := self.groups.get(item.data(0, Qt.ItemDataRole.UserRole))) and group.path_ids:
            self.path_requested.emit(group.path_ids[0])


class Execution(QWidget):
    requested = Signal(object)
    cancelled = Signal()
    executable_changed = Signal(str)
    auto_mode_changed = Signal(str)
    resource_preferences_changed = Signal()

    def __init__(self):
        super().__init__()
        self.input = QLineEdit(placeholderText="Project (.xpr) or design checkpoint (.dcp)")
        self.output = QLineEdit(placeholderText="Output directory")
        self.executable = QLineEdit(placeholderText="Automatic discovery")
        self.run_name = QLineEdit(placeholderText="Use the current completed run")
        self.build = QComboBox()
        for title, key in (("Inspect existing design", "none"), ("Synthesize an isolated project copy", "synth"),
                           ("Route an isolated project copy", "route")):
            self.build.addItem(title, key)
        self.auto_mode = QComboBox()
        self.auto_mode.addItem("Analysis only", "off")
        self.auto_mode.addItem("Apply verified fixes in a project copy", "copy")
        self.auto_mode.addItem("Update the selected project after verification", "source")
        self.auto_mode.setToolTip("Route a baseline and candidate with the same Default recipe. Check RTL equivalence or Xilinx IP behavior before publishing a change.")
        self.balance_resources = QCheckBox("Rebalance overused resources")
        self.resource_limit = QSpinBox()
        self.resource_limit.setRange(1, 100)
        self.resource_limit.setValue(85)
        self.resource_limit.setSuffix("%")
        self.resource_limit.setAccessibleName("Maximum resource utilization")
        self.resource_limit.setEnabled(False)
        self.balance_resources.toggled.connect(self.resource_limit.setEnabled)
        self.balance_resources.toggled.connect(lambda _: self.resource_preferences_changed.emit())
        self.resource_limit.valueChanged.connect(lambda _: self.resource_preferences_changed.emit())
        self.limit = QSpinBox()
        self.limit.setRange(1, 10000)
        self.limit.setValue(100)
        self.per_endpoint = QSpinBox()
        self.per_endpoint.setRange(1, 100)
        self.per_endpoint.setValue(3)
        self.embed = QCheckBox("Include RTL snapshots in the JSON session")
        self.embed.setChecked(True)
        self.extra = []
        self.sources = QPushButton("Select RTL, Tcl, XDC or BD context")
        self.sources.clicked.connect(self._sources)
        self.start = QPushButton("Run analysis")
        self.start.setObjectName("Primary")
        self.start.clicked.connect(self._request)
        self.cancel = QPushButton("Cancel")
        self.cancel.setEnabled(False)
        self.cancel.clicked.connect(self.cancelled.emit)
        self.status = label("Ready", "Section")
        self.activity = QProgressBar()
        self.activity.setRange(0, 0)
        self.activity.setTextVisible(False)
        self.activity.setFixedHeight(5)
        self.activity.hide()
        self.detail = label("", "Muted")
        self.detail.setWordWrap(True)
        self.log = text_area('log')
        self.log.document().setMaximumBlockCount(5000)
        self.executable.editingFinished.connect(lambda: self.executable_changed.emit(self.executable.text().strip()))
        form = QFormLayout()
        form.addRow("Design", self._browse_line(self.input, "design"))
        form.addRow("Output", self._browse_line(self.output, "directory"))
        form.addRow("Vivado executable", self._browse_line(self.executable, "executable"))
        form.addRow("Run", self.run_name)
        form.addRow("Build", self.build)
        form.addRow("Automatic fixes", self.auto_mode)
        self.resource_row = QWidget()
        controls = QHBoxLayout(self.resource_row)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.addWidget(self.balance_resources)
        controls.addWidget(label("Utilization limit", "Muted"))
        controls.addWidget(self.resource_limit)
        controls.addStretch()
        self.resource_row.setToolTip("Checks LUT, memory-capable LUT, block RAM and DSP budgets even when timing passes.")
        form.addRow("Resource budget", self.resource_row)
        self.auto_note = label("", "Muted")
        self.auto_note.setWordWrap(True)
        form.addRow("", self.auto_note)
        self.form = form
        budget = QWidget()
        budgets = QHBoxLayout(budget)
        budgets.setContentsMargins(0, 0, 0, 0)
        budgets.addWidget(self.limit)
        self.endpoint_label = label("Paths per endpoint", "Muted")
        budgets.addWidget(self.endpoint_label)
        budgets.addWidget(self.per_endpoint)
        budgets.addStretch()
        form.addRow("Paths per analysis", budget)
        form.addRow("Source files", self.sources)
        form.addRow("", self.embed)
        actions = QHBoxLayout()
        actions.addWidget(self.start)
        actions.addWidget(self.cancel)
        actions.addStretch()
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(actions)
        layout.addWidget(self.status)
        layout.addWidget(self.activity)
        layout.addWidget(self.detail)
        layout.addWidget(self.log, 1)
        self.input.textChanged.connect(self._update_kind)
        self.auto_mode.currentIndexChanged.connect(self._auto_changed)
        self._update_kind()

    def _auto_changed(self):
        self.auto_mode_changed.emit(self.auto_mode.currentData())
        self._update_kind()

    def _browse_line(self, edit, kind):
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit, 1)
        button = QPushButton("Browse…")
        button.clicked.connect(lambda: self._browse(edit, kind))
        row.addWidget(button)
        return widget

    def _browse(self, edit, kind):
        if kind == "directory":
            name = QFileDialog.getExistingDirectory(self, "Choose output directory")
        else:
            ext = "Vivado design (*.xpr *.dcp)" if kind == "design" else "All files (*)"
            name, _ = QFileDialog.getOpenFileName(self, "Choose " + kind, filter=ext)
        if name:
            edit.setText(name)
            if edit is self.executable:
                self.executable_changed.emit(name)

    def _sources(self):
        names, _ = QFileDialog.getOpenFileNames(self, "Select project source and context files",
                                                filter="Project sources (*.sv *.v *.svh *.vh *.vhd *.vhdl *.tcl *.xdc *.bd *.json)")
        if names:
            self.extra = [Path(name) for name in names]
            self.sources.setText(f"{len(names)} additional project files")

    def _update_kind(self):
        checkpoint = Path(self.input.text()).suffix.lower() == ".dcp"
        self.auto_mode.setEnabled(not checkpoint)
        automatic = not checkpoint and self.auto_mode.currentData() != "off"
        self.build.setEnabled(not checkpoint and not automatic)
        self.run_name.setEnabled(not checkpoint and not automatic)
        self.embed.setEnabled(not automatic)
        self.sources.setEnabled(not automatic)
        self.per_endpoint.setEnabled(not automatic)
        self.limit.setMaximum(1000 if automatic else 10000)
        for widget in (self.build, self.run_name, self.embed, self.sources):
            self.form.setRowVisible(widget, not automatic)
        self.form.setRowVisible(self.auto_note, automatic)
        self.form.setRowVisible(self.resource_row, automatic)
        self.endpoint_label.setVisible(not automatic)
        self.per_endpoint.setVisible(not automatic)
        publish = self.auto_mode.currentData() == "source"
        self.auto_note.setText("Vivado routes both builds with the same Default placement and routing recipe. " +
            ("After a verified timing pass, TimingLens backs up and updates the selected project." if publish
             else "The verified RTL or block-design edit is saved in a new project copy."))
        self.output.setPlaceholderText("Defaults to timinglens-runs beside the project" if automatic else "Output directory")
        self.start.setText("Run and apply verified fixes" if automatic else "Run analysis")
        if checkpoint:
            self.build.setCurrentIndex(0)
            self.run_name.clear()

    def _request(self):
        inp, out = self.input.text().strip(), self.output.text().strip()
        automatic = Path(inp).suffix.lower() == ".xpr" and self.auto_mode.currentData() != "off"
        if automatic and not out:
            out = str(Path(inp).absolute().parent / "timinglens-runs")
        if not inp or not out:
            self.detail.setText("Choose a design file and an output directory.")
            return
        kind = "checkpoint" if Path(inp).suffix.lower() == ".dcp" else "project"
        if kind == "project" and self.auto_mode.currentData() != "off":
            from uuid import uuid4
            from ..experiments.auto_fix import AutoRequest
            job = Path(out) / ("auto-fix-" + uuid4().hex[:12])
            self.requested.emit(AutoRequest(Path(inp), job, self.executable.text().strip() or None,
                                            self.auto_mode.currentData() == "source", self.limit.value(),
                                            self.resource_limit.value() if self.balance_resources.isChecked() else None))
            return
        self.requested.emit(Request(kind, Path(inp), Path(out), self.executable.text().strip() or None,
                                    self.run_name.text().strip(), self.build.currentData(),
                                    max_paths=self.limit.value(), paths_per_endpoint=self.per_endpoint.value(),
                                    sources=self.extra, embed_sources=self.embed.isChecked()))

    def busy(self, value):
        self.start.setEnabled(not value)
        self.cancel.setEnabled(value)
        self.activity.setVisible(value)

    def append_log(self, line):
        self.log.appendPlainText(line)
        if line.startswith("TimingLens:"):
            self.detail.setText(line.removeprefix("TimingLens: "))
