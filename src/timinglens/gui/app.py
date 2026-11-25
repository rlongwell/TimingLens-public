"""TimingLens desktop shell and asynchronous analysis orchestration."""
from __future__ import annotations

import logging
import json
from pathlib import Path
from threading import Event

from PySide6.QtCore import QByteArray, QObject, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFileDialog, QHBoxLayout, QMainWindow, QMessageBox,
                               QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from ..service import collect, export_result, load, inspect_files
from ..analysis.engine import analyze
from ..experiments.auto_fix import AutoRequest, AutoResult, run_auto
from ..timing.models import Session
from ..vivado.decode import refresh_report_arcs
from ..vivado.runner import Cancelled
from .pages import Dashboard, Execution, Issues
from .paths import PathsPage
from .source import SourcePage
from .theme import apply_theme, load_settings, save_settings
from .widgets import label
from .project_files import ProjectFiles
from .experiment_lab import ExperimentLab
from .counter_runner import CounterRunner
from .recommendation_runner import RecommendationRunner
from .home import Home

LOG = logging.getLogger(__name__)


class Worker(QObject):
    log = Signal(str)
    finished = Signal(object, object)
    failed = Signal(str, bool)
    done = Signal()

    def __init__(self, request=None, session=None, inspection=None):
        super().__init__()
        self.request = request
        self.session = session
        self.inspection = inspection
        self.cancel = Event()

    @Slot()
    def run(self):
        try:
            if isinstance(self.request, AutoRequest):
                work = run_auto(self.request, self.log.emit, self.cancel)
                result = work.analysis
            elif self.request:
                result, work = collect(self.request, log=self.log.emit, cancel=self.cancel)
            elif self.inspection:
                result, work = inspect_files(**self.inspection), 'Offline project files'
            elif isinstance(self.session, Session):
                result, work = analyze(refresh_report_arcs(self.session)), 'Embedded Experiment Lab session'
            else:
                result, work = load(self.session), self.session
            # Slang elaboration and recommendation assembly belong in this
            # worker, never in the GUI's first-selection callback.
            _ = result.investigations, result.project_plans
            self.finished.emit(result, work)
        except Cancelled as error:
            self.failed.emit(str(error), True)
        except Exception as error:
            LOG.exception("Analysis failed")
            self.failed.emit(str(error), False)
        finally:
            self.done.emit()


class MainWindow(QMainWindow):
    titles = ("Overview", "Timing paths", "Fix recommendations", "Project source", "Analyze a Vivado design", "Project files", "Experiment Lab", "Counter experiment", "Suggested experiment", "Start here")

    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.settings = load_settings()
        self.result = self.worker = self.thread = None
        self.pending_close = False
        self.setWindowTitle("TimingLens")
        self.resize(1350, 880)
        if isinstance(geometry := self.settings.get("geometry"), str):
            self.restoreGeometry(QByteArray.fromHex(geometry.encode("ascii", errors="ignore")))
        self.setMinimumSize(980, 690)

        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root)
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(232)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(13, 20, 13, 15)
        side.setSpacing(7)
        side.addWidget(label("TimingLens", "Brand"))
        side.addSpacing(19)
        self.navigation = QButtonGroup(self)
        for index in (9, 0, 2, 6):
            button = QPushButton(self.titles[index])
            button.setObjectName("Nav")
            button.setCheckable(True)
            self.navigation.addButton(button, index)
            side.addWidget(button)
        side.addSpacing(12)
        self.details_toggle = QPushButton('Show tools and details ▸')
        self.details_toggle.setCheckable(True)
        side.addWidget(self.details_toggle)
        self.details_navigation = QWidget()
        details = QVBoxLayout(self.details_navigation)
        details.setContentsMargins(0, 0, 0, 0)
        for index in (1, 3, 5, 4, 7, 8):
            button = QPushButton({4: 'Vivado analysis'}.get(index, self.titles[index]))
            button.setObjectName('Nav'); button.setCheckable(True)
            self.navigation.addButton(button, index); details.addWidget(button)
        self.details_navigation.hide()
        self.details_toggle.toggled.connect(self.details_navigation.setVisible)
        self.details_toggle.toggled.connect(lambda expanded: self.details_toggle.setText('Hide tools and details ▾' if expanded else 'Show tools and details ▸'))
        side.addWidget(self.details_navigation)
        side.addStretch()
        self.switch = QPushButton()
        self.switch.clicked.connect(self.toggle_theme)
        side.addWidget(self.switch)
        root_layout.addWidget(sidebar)

        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(16, 13, 16, 12)
        header = QHBoxLayout()
        self.title = label("", "Title")
        header.addWidget(self.title)
        header.addStretch()
        self.open = QPushButton("Open session…")
        self.open.clicked.connect(self.open_session)
        self.export = QPushButton("Export…")
        self.export.setEnabled(False)
        self.export.clicked.connect(self.export_session)
        live = QPushButton("Add design…")
        live.setObjectName("Primary")
        live.clicked.connect(self.choose_design)
        self.add_design = live
        for button in (self.open, self.export, live):
            header.addWidget(button)
        body.addLayout(header)

        self.stack = QStackedWidget()
        self.dashboard, self.paths, self.issues, self.source, self.execution = (
            Dashboard(), PathsPage(), Issues(), SourcePage(), Execution())
        for page in (self.dashboard, self.paths, self.issues, self.source, self.execution):
            self.stack.addWidget(page)
        self.project_files = ProjectFiles()
        self.stack.addWidget(self.project_files)
        self.project_files.requested.connect(lambda inspection: self.start_work(inspection=inspection))
        self.lab = ExperimentLab(self.settings.get('experiment_lab'))
        self.stack.addWidget(self.lab)
        self.lab.preferences_changed.connect(self.save_lab)
        self.lab.idle.connect(self.lab_idle)
        self.lab.inspect_requested.connect(self.inspect_lab_path)
        self.lab_path = None
        self.pending_pair = None
        self.pending_sweep = None
        self.pending_rtl = None
        self.counter_runner = CounterRunner(self.settings.get('counter_runner'), self.settings.get('vivado',''))
        self.stack.addWidget(self.counter_runner)
        self.counter_runner.preferences_changed.connect(self.save_runner)
        self.counter_runner.pair_requested.connect(self.import_counter_pair)
        self.counter_runner.sweep_requested.connect(self.import_counter_sweep)
        self.counter_runner.idle.connect(self.lab_idle)
        self.lab.run_requested.connect(lambda:self.navigate(7))
        self.recommendation_runner=RecommendationRunner(self.settings.get('recommendation_runner'),self.settings.get('vivado',''))
        self.stack.addWidget(self.recommendation_runner)
        self.recommendation_runner.preferences_changed.connect(self.save_recommendation_runner)
        self.recommendation_runner.pair_requested.connect(self.import_counter_pair)
        self.recommendation_runner.rtl_sweep_requested.connect(self.import_rtl_sweep)
        self.recommendation_runner.back_requested.connect(lambda:self.navigate(2))
        self.recommendation_runner.idle.connect(self.lab_idle)
        self.recommendation_runner.activity_changed.connect(self.tool_activity)
        self.counter_runner.activity_changed.connect(self.tool_activity)
        self.issues.experiment_requested.connect(self.prepare_recommendation)
        self.issues.auto_project_requested.connect(self.choose_automatic_project)
        self.issues.example_requested.connect(self.open_example_evidence)
        self.example_plan=None
        self.home = Home()
        self.stack.addWidget(self.home)
        self.home.design_requested.connect(self.choose_design)
        self.home.session_requested.connect(self.open_session)
        self.home.example_requested.connect(self.prepare_counter_example)
        self.home.resume_requested.connect(lambda: self.navigate(0))
        body.addWidget(self.stack, 1)
        self.footer = label("Local analysis · ready", "Muted")
        body.addWidget(self.footer)
        root_layout.addWidget(content, 1)
        self.navigation.idClicked.connect(self.navigate)
        self.paths.source_requested.connect(self.show_source)
        self.issues.path_requested.connect(self.show_path)
        self.issues.source_requested.connect(self.show_source)
        self.dashboard.review_requested.connect(lambda: self.navigate(2))
        self.execution.requested.connect(lambda request: self.start_work(request=request))
        self.execution.cancelled.connect(self.cancel_work)
        self.execution.executable.setText(self.settings.get("vivado", "") if isinstance(self.settings.get("vivado"), str) else "")
        self.execution.executable_changed.connect(self.save_vivado)
        mode = self.execution.auto_mode.findData(self.settings.get("auto_fix_mode", "off"))
        self.execution.auto_mode.setCurrentIndex(max(0, mode))
        self.execution.auto_mode_changed.connect(self.save_auto_mode)
        limit = self.settings.get("resource_limit", 85)
        self.execution.resource_limit.setValue(limit if type(limit) is int and 1 <= limit <= 100 else 85)
        self.execution.balance_resources.setChecked(self.settings.get("balance_resources") is True)
        self.execution.resource_preferences_changed.connect(self.save_resource_preferences)
        self.set_theme(self.settings.get("theme") != "light")
        self.navigate(9)

    def navigate(self, index):
        if index in (1, 3, 4, 5, 7, 8):
            self.details_toggle.setChecked(True)
        self.stack.setCurrentIndex(index)
        self.navigation.button(index).setChecked(True)
        self.title.setText(self.titles[index])

    def choose_design(self):
        if self.thread or self.counter_runner.thread or self.recommendation_runner.thread:
            return
        names, _ = QFileDialog.getOpenFileNames(self, 'Choose design evidence', filter=
            'Design evidence (*.xpr *.dcp *.rpt *.log *.json *.sv *.v *.svh *.vh *.vhd *.vhdl *.tcl *.xdc *.bd)')
        self.route_design_files([Path(name) for name in names])

    def route_design_files(self, paths):
        """Stage inputs for review; selecting a file never launches a tool."""
        if not paths or self.thread or self.counter_runner.thread or self.recommendation_runner.thread:
            return
        designs = [path for path in paths if path.suffix.lower() in {'.xpr', '.dcp'}]
        if len(designs) > 1:
            self.footer.setText('Choose one Vivado project or checkpoint at a time. Add RTL and constraints alongside it.')
            return
        if designs:
            self.execution.input.setText(str(designs[0]))
            self.execution.extra = [path for path in paths if path not in designs]
            self.execution.sources.setText(f'{len(self.execution.extra)} additional project files' if self.execution.extra else 'Select RTL, Tcl, XDC or BD context')
            self.navigate(4)
        else:
            self.project_files.add_files(paths)
            self.navigate(5)

    def prepare_counter_example(self):
        if self.thread or self.counter_runner.thread or self.recommendation_runner.thread:
            return
        self.counter_runner.example.setCurrentIndex(self.counter_runner.example.findData('counter32_250'))
        self.counter_runner.mode.setCurrentIndex(0)
        self.counter_runner.tabs.setCurrentIndex(0)
        self.navigate(7)

    def set_theme(self, dark):
        self.dark = dark
        colors = apply_theme(self.app, dark)
        self.switch.setText("Light theme" if dark else "Dark theme")
        self.paths.theme(colors)
        self.source.theme(colors)
        self.lab.theme(colors)

    def toggle_theme(self):
        self.set_theme(not self.dark)
        self.settings["theme"] = "dark" if self.dark else "light"
        self.persist()

    def save_resource_preferences(self):
        self.settings["balance_resources"] = self.execution.balance_resources.isChecked()
        self.settings["resource_limit"] = self.execution.resource_limit.value()
        self.persist()

    def save_auto_mode(self, mode):
        self.settings["auto_fix_mode"] = mode
        self.persist()

    def save_vivado(self, path):
        self.settings["vivado"] = path
        self.persist()

    def save_lab(self, preferences):
        self.settings['experiment_lab'] = preferences
        self.persist()

    def save_runner(self, preferences):
        self.settings['counter_runner'] = preferences
        self.persist()

    def save_recommendation_runner(self,preferences):
        self.settings['recommendation_runner']=preferences;self.persist()

    def choose_automatic_project(self):
        if self.thread or self.counter_runner.thread or self.recommendation_runner.thread:
            return
        name, _ = QFileDialog.getOpenFileName(self, "Choose the matching Vivado project", filter="Vivado project (*.xpr)")
        if name:
            self.route_design_files([Path(name)])
            if self.execution.auto_mode.currentData() == "off":
                self.execution.auto_mode.setCurrentIndex(self.execution.auto_mode.findData("copy"))

    def prepare_recommendation(self,prepared):
        if self.thread or self.counter_runner.thread or self.recommendation_runner.thread:return
        self.recommendation_runner.configure(prepared);self.navigate(8)

    def open_example_evidence(self,name):
        from ..experiments.recommendation import EXAMPLES
        if name not in EXAMPLES:return
        path=Path(__file__).resolve().parents[3]/'results/verified'/name/'analysis.json'
        if not path.is_file():
            self.footer.setText('Example evidence is unavailable. Run timinglens demo --run-vivado --design '+name+' --output results/verified/'+name+', then open its analysis.json.');return
        if self.thread or self.counter_runner.thread or self.recommendation_runner.thread:return
        self.example_plan='vivado.fanout' if name=='fanout' else 'rtl.priority_sweep' if name=='priority' else 'vivado.remap'
        self.start_work(session=path)

    def tool_activity(self,*_):
        active=bool(self.thread or self.counter_runner.thread or self.recommendation_runner.thread)
        self.home.busy(active)
        self.add_design.setEnabled(not active)
        self.counter_runner.set_external_busy(bool(self.thread or self.recommendation_runner.thread))
        self.recommendation_runner.set_external_busy(bool(self.thread or self.counter_runner.thread))
        self.issues.set_external_busy(active)

    def import_counter_pair(self, paths):
        self.pending_rtl = None
        self.pending_pair = list(paths)
        self.pending_sweep = None
        self.lab_idle()

    def import_counter_sweep(self, path):
        self.pending_rtl = None
        self.pending_sweep = path
        self.pending_pair = None
        self.lab_idle()

    def import_rtl_sweep(self, payload):
        self.pending_rtl=payload;self.pending_pair=self.pending_sweep=None;self.lab_idle()

    def lab_idle(self):
        if self.pending_close and not self.thread and not self.counter_runner.thread and not self.recommendation_runner.thread and not self.lab.thread:
            QTimer.singleShot(0, self.close)
        elif not self.pending_close and self.pending_rtl and not self.lab.thread:
            payload,self.pending_rtl=self.pending_rtl,None
            self.lab.rtl.load(*payload);self.navigate(6)
        elif not self.pending_close and self.pending_sweep and not self.lab.thread:
            path, self.pending_sweep = self.pending_sweep, None
            self.lab.import_sweep(path)
            self.navigate(6)
        elif not self.pending_close and self.pending_pair and not self.lab.thread:
            paths, self.pending_pair = self.pending_pair, None
            self.lab.import_paths(paths,pair=True)
            self.navigate(6)

    def inspect_lab_path(self, session, path_id):
        if self.thread or self.counter_runner.thread or self.recommendation_runner.thread:
            self.footer.setText('Wait for the current analysis before opening another path.')
            return
        self.lab_path = path_id
        self.start_work(session=session)

    def persist(self):
        self.settings["geometry"] = bytes(self.saveGeometry().toHex()).decode("ascii")
        try:
            save_settings(self.settings)
        except OSError as error:
            self.footer.setText(f"Could not save preferences: {error}")

    def show_source(self, association):
        self.navigate(3)
        self.source.show_source(association)

    def show_path(self, path_id):
        self.navigate(1)
        self.paths.goto(path_id)

    def open_session(self):
        name, _ = QFileDialog.getOpenFileName(self, "Open TimingLens session", filter="TimingLens session (*.json)")
        if name:
            self.start_work(session=Path(name))

    def export_session(self):
        name = QFileDialog.getExistingDirectory(self, "Choose an export directory")
        if name:
            try:
                export_result(self.result, Path(name))
                self.footer.setText(f"Exported to {name}")
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Export failed", str(error))

    def start_work(self, request=None, session=None, inspection=None):
        if self.thread or self.counter_runner.thread or self.recommendation_runner.thread:
            self.footer.setText('Wait for the current analysis or experiment to finish.')
            return
        self.counter_runner.set_external_busy(True)
        self.recommendation_runner.set_external_busy(True);self.issues.set_external_busy(True)
        self.open.setEnabled(False)
        self.home.busy(True)
        self.add_design.setEnabled(False)
        self.execution.busy(True)
        self.project_files.busy(True)
        self.execution.cancel.setEnabled(request is not None)
        self.execution.log.clear()
        self.execution.status.setText("Running Vivado" if request else "Analyzing project files" if inspection else "Opening session")
        self.footer.setText("Vivado is running…" if request else "Analyzing project evidence…")
        self.worker = Worker(request, session, inspection)
        self.thread = QThread(self)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.log.connect(self.execution.append_log)
        self.worker.finished.connect(self.finished)
        self.worker.failed.connect(self.failed)
        self.worker.done.connect(self.thread.quit)
        self.worker.done.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.cleanup)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def cancel_work(self):
        if self.worker:
            self.worker.cancel.set()
            self.execution.cancel.setEnabled(False)
            self.execution.status.setText("Cancelling…")

    @Slot(object, object)
    def finished(self, result, work):
        self.set_result(result)
        if isinstance(work, AutoResult):
            self.execution.status.setText("Verified fix applied" if work.status == "applied" else work.status.replace("_", " ").capitalize())
            self.execution.detail.setText(work.message)
            self.footer.setText(f"Automatic fixes · {work.status.replace('_', ' ')} · {work.directory.name}")
            self.footer.setToolTip(work.message)
            state = json.loads((work.directory / "decision.json").read_text())
            if "comparison" in state:
                pair = work.directory / state["comparison"]
                files = (pair / "baseline.run.json", pair / "candidate.run.json")
                attempt = next((a for a in reversed(state["attempts"]) if a.get("comparison") == state["comparison"]),
                               state["attempts"][-1])
                if work.status == "review":
                    decision = attempt.get("reason", work.message)
                else:
                    decision = ("Verified copy available" if work.status == "verified_copy" else
                                "Selected project updated" if state["apply_to_source"] else "Verified project copy saved")
                    decision += " · Setup, hold and pulse width passed."
                    if warnings := attempt.get("dsp_pipelining_warnings"):
                        decision += " DSP pipelining advisories: " + ", ".join(f"{rule} ({n})" for rule,n in warnings.items()) + "."
                    if margins := attempt.get("margin_reductions"):
                        for key, (a,b) in margins.items():
                            decision += f" {key.split('.')[0].title()} margin {a:+.3f} → {b:+.3f} ns."
                resource_summary = ""
                if move := attempt.get("resource_move"):
                    from ..experiments.resource_balance import LABELS
                    budget = state["resource_budget"]
                    old, new = budget["before"], attempt["resources_after"]
                    resource_summary = " · ".join(f"{LABELS[k]} {old[k]['used']:,g} → {new[k]['used']:,g} of {new[k]['available']:,g}"
                                                   for k in (move["from"], move["to"]))
                    resource_summary += f" · {budget['limit_percent']}% limit"
                    if budget["baseline_stage"] == "synthesized":
                        resource_summary += " · Baseline exceeded device capacity before placement"
                self.lab.automatic_pair = (tuple(map(str, files)), decision, work.status in {"applied", "verified_copy"}, resource_summary)
                self.import_counter_pair(files)
            else:
                self.navigate(2)
            return
        if self.example_plan:
            self.issues.select_experiment(self.example_plan);self.example_plan=None;self.navigate(2)
        if self.lab_path:
            self.show_path(self.lab_path)
            self.lab_path = None
        self.execution.status.setText("Completed")
        self.execution.detail.setText(str(work))

    def set_result(self, result):
        self.result = result
        self.home.resume.show()
        self.dashboard.load(result)
        self.paths.load(result)
        self.issues.load(result)
        self.source.load(result.source_index)
        self.project_files.set_base(result.session)
        self.export.setEnabled(True)
        self.footer.setText(f"{result.session.top or result.session.name[:70]} · {result.failing_paths} failing paths · {len(result.investigations)} investigations")
        self.footer.setToolTip(result.session.name)
        self.navigate(0)

    @Slot(str, bool)
    def failed(self, message, cancelled):
        self.example_plan=None
        self.lab_path = None
        self.execution.status.setText("Cancelled" if cancelled else "Analysis failed")
        self.execution.detail.setText(message)
        self.footer.setText(message)
        if not cancelled:
            self.navigate(5 if self.worker and self.worker.inspection else 4)

    @Slot()
    def cleanup(self):
        self.thread = self.worker = None
        self.counter_runner.set_external_busy(False)
        self.tool_activity()
        self.open.setEnabled(True)
        self.execution.busy(False)
        self.project_files.busy(False)
        if self.pending_close:
            QTimer.singleShot(0, self.close)

    def closeEvent(self, event):
        if self.thread or self.lab.thread or self.counter_runner.thread or self.recommendation_runner.thread:
            self.pending_close = True
            self.cancel_work()
            self.counter_runner.cancel_job()
            self.recommendation_runner.cancel_job()
            event.ignore()
            return
        self.persist()
        super().closeEvent(event)


def launch(session: Path | None = None) -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("TimingLens")
    app.setStyle("Fusion")
    window = MainWindow(app)
    window.show()
    if session:
        QTimer.singleShot(0, lambda: window.start_work(session=session))
    return app.exec()
