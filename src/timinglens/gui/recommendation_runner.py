"""Review and execute a frozen recommendation without blocking the desktop."""
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from uuid import uuid4

from PySide6.QtCore import QObject,QThread,Signal,Slot
from PySide6.QtWidgets import QComboBox,QFileDialog,QFormLayout,QHBoxLayout,QLineEdit,QProgressBar,QPushButton,QSpinBox,QTabWidget,QVBoxLayout,QWidget

from ..experiments.recommendation import EXAMPLES
from ..experiments.recommendation_runner import RecommendationRequest,read_recommendation_job,run_recommendation
from ..experiments.runner import JobFailure,workspace_root
from ..experiments.rtl_sweep_runner import RTLSweepResult
from ..experiments.priority_variants import VARIANTS,source_diff
from ..experiments.recommendation import bundled_inputs
from .widgets import label,text_area


class RecommendationWorker(QObject):
    log=Signal(str);phase=Signal(str);finished=Signal(object);failed=Signal(str,str);done=Signal()
    def __init__(self,request=None,directory=None):
        super().__init__();self.request=request;self.directory=directory;self.cancel=Event()
    @Slot()
    def run(self):
        try:
            result=run_recommendation(self.request,self.log.emit,self.phase.emit,self.cancel) if self.request else read_recommendation_job(self.directory)
            self.finished.emit(result)
        except JobFailure as error:self.failed.emit(str(error),error.status)
        except Exception as error:self.failed.emit(str(error),'failed')
        finally:self.done.emit()


class RecommendationRunner(QWidget):
    preferences_changed=Signal(object);pair_requested=Signal(object);rtl_sweep_requested=Signal(object);back_requested=Signal();activity_changed=Signal(bool);idle=Signal()
    def __init__(self,preferences=None,vivado=''):
        super().__init__();self.preferences=preferences if isinstance(preferences,dict) else {}
        self.prepared=self.thread=self.worker=self.result=None;self.external_busy=False
        layout=QVBoxLayout(self);layout.setContentsMargins(0,8,0,0);layout.setSpacing(10)
        self.heading=label('Choose a recommendation to try','Metric');self.heading.setWordWrap(True);layout.addWidget(self.heading)
        intro=label('Review the frozen inputs and recipe, then build a fresh baseline and candidate. Results open in Experiment Lab.','Muted');intro.setWordWrap(True);layout.addWidget(intro)
        form=QFormLayout();self.vivado=QLineEdit(str(self.preferences.get('vivado',vivado)));self.vivado.setPlaceholderText('Auto-detect Vivado 2024.2')
        self.yosys=QLineEdit(str(self.preferences.get('yosys','')));self.yosys.setPlaceholderText('Auto-detect packaged Yosys 0.69')
        self.output=QLineEdit(str(self.preferences.get('output',workspace_root()/'results/recommendations')))
        destination=QHBoxLayout();destination.addWidget(self.output,1);self.browse=QPushButton('Choose folder…');destination.addWidget(self.browse);self.browse.clicked.connect(self.choose_folder)
        self.timeout=QSpinBox();self.timeout.setRange(30,7200);self.timeout.setSuffix(' s per tool')
        configured=self.preferences.get('timeout',900);self.timeout.setValue(configured if isinstance(configured,int) else 900)
        form.addRow('Vivado executable',self.vivado);form.addRow('Equivalence tool',self.yosys);self.form=form;form.setRowVisible(self.yosys,False)
        form.addRow('Results parent folder',destination);form.addRow('Timeout',self.timeout);layout.addLayout(form)
        actions=QHBoxLayout();self.back=QPushButton('Fix recommendations');self.back.clicked.connect(self.back_requested.emit)
        self.start_button=QPushButton('Run isolated experiment');self.start_button.setObjectName('Primary');self.start_button.clicked.connect(self.start_job)
        self.cancel_button=QPushButton('Cancel');self.cancel_button.clicked.connect(self.cancel_job)
        self.restore=QPushButton('Open last job');self.restore.clicked.connect(self.restore_job)
        for button in (self.back,self.start_button,self.cancel_button,self.restore):actions.addWidget(button)
        actions.addStretch();layout.addLayout(actions)
        self.status=label('Select “Try this experiment” in Fix recommendations.','Section');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.progress=QProgressBar();self.progress.setRange(0,7);self.progress.setValue(0);self.progress.setTextVisible(False);self.progress.setMaximumHeight(8);layout.addWidget(self.progress)
        self.tabs=QTabWidget();self.preview=text_area('tcl');self.preview.setObjectName('CodeEditor');self.log=text_area('log');self.log.document().setMaximumBlockCount(1800)
        self.tabs.addTab(self.preview,'Experiment preview');self.tabs.addTab(self.log,'Live log')
        diff_page=QWidget();diff_layout=QVBoxLayout(diff_page);diff_layout.setContentsMargins(0,4,0,0)
        self.variant=QComboBox()
        for key,v in VARIANTS.items():self.variant.addItem(v.title,key)
        self.variant.currentIndexChanged.connect(self.variant_changed);diff_layout.addWidget(self.variant)
        self.diff=text_area('diff');self.diff.setObjectName('CodeEditor');diff_layout.addWidget(self.diff,1)
        self.diff_index=self.tabs.addTab(diff_page,'Source diff');self.tabs.setTabVisible(self.diff_index,False)
        layout.addWidget(self.tabs,1)
        bottom=QHBoxLayout();self.location=label('Each job retains its trigger, input hashes, simulation, scripts, checkpoints and reports.','Muted');self.location.setWordWrap(True)
        self.registers=QPushButton('Compare registers');self.registers.clicked.connect(lambda:self.open_pair(False))
        self.global_timing=QPushButton('Compare design');self.global_timing.clicked.connect(lambda:self.open_pair(True))
        bottom.addWidget(self.location,1);bottom.addWidget(self.registers);bottom.addWidget(self.global_timing);layout.addLayout(bottom)
        self.busy(False)

    def configure(self,prepared):
        if self.thread:return
        self.prepared=prepared;self.result=None;self.heading.setText(EXAMPLES[prepared.example].title+' · '+('3 verified RTL variants · Default throughout' if prepared.rtl_sweep else 'Balanced RTL · Default in both builds' if prepared.rtl_rewrite else prepared.recipe.name))
        self.form.setRowVisible(self.yosys,prepared.rtl_rewrite)
        self.location.setText('A new job will retain the trigger, inputs, simulation, scripts, checkpoints and reports.');self.log.clear()
        preview=prepared.preview();parts=preview.split('\nSOURCE DIFF\n',1) if prepared.rtl_rewrite else [preview]
        self.preview.setPlainText(parts[0]);self.diff.setPlainText(parts[1] if len(parts)>1 else '')
        self.variant.setVisible(prepared.rtl_sweep)
        if prepared.rtl_sweep:self.variant_changed()
        self.tabs.setTabVisible(self.diff_index,prepared.rtl_rewrite);self.tabs.setCurrentIndex(0)
        self.status.setText('Ready · review the exact experiment below.');self.progress.setValue(0);self.busy(False)

    def variant_changed(self):
        if self.prepared and self.prepared.rtl_sweep:self.diff.setPlainText(source_diff(bundled_inputs('priority')[0],self.variant.currentData()))

    def busy(self,value):
        for widget in (self.vivado,self.yosys,self.output,self.timeout,self.browse):widget.setEnabled(not value)
        self.start_button.setEnabled(not value and not self.external_busy and self.prepared is not None)
        self.cancel_button.setEnabled(value and self.worker is not None and self.worker.request is not None)
        self.restore.setEnabled(not value and bool(self.preferences.get('last_job')))
        self.registers.setEnabled(not value and self.result is not None);self.global_timing.setEnabled(not value and self.result is not None)

    def set_external_busy(self,value):self.external_busy=value;self.busy(self.thread is not None)

    def choose_folder(self):
        name=QFileDialog.getExistingDirectory(self,'Choose parent for new recommendation jobs',self.output.text())
        if name:self.output.setText(name)

    def start_job(self):
        if self.thread or self.external_busy or self.prepared is None:return
        if not self.output.text().strip():self.status.setText('Choose a results parent folder.');return
        parent=Path(self.output.text()).expanduser();name=self.prepared.example+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8]
        request=RecommendationRequest(self.prepared,parent/name,self.vivado.text().strip() or None,timeout=float(self.timeout.value()),yosys=self.yosys.text().strip() or None)
        self.preferences.update(vivado=self.vivado.text(),yosys=self.yosys.text(),output=str(parent),timeout=self.timeout.value(),last_job=str(request.output.absolute()))
        self.preferences_changed.emit(dict(self.preferences));self.location.setText(str(request.output.absolute()));self.run_worker(RecommendationWorker(request=request))

    def restore_job(self):
        if self.thread or not self.preferences.get('last_job'):return
        self.prepared=None;self.heading.setText('Saved experiment');self.form.setRowVisible(self.yosys,False);self.tabs.setTabVisible(self.diff_index,False);self.diff.clear()
        self.preview.setPlainText('Opening saved evidence without running tools.\n\nThe Lab includes the recorded plan, trigger and recipe diff under Evidence and sources.\n\nChoose “Try this experiment” in Fix recommendations to prepare a new job.')
        self.run_worker(RecommendationWorker(directory=Path(self.preferences['last_job'])))

    def run_worker(self,worker):
        if self.thread:return
        self.result=None;self.worker=worker;self.thread=QThread(self);worker.moveToThread(self.thread)
        self.thread.started.connect(worker.run);worker.log.connect(self.log.appendPlainText);worker.phase.connect(self.on_phase)
        worker.finished.connect(self.completed);worker.failed.connect(self.failed);worker.done.connect(self.thread.quit);worker.done.connect(worker.deleteLater)
        self.thread.finished.connect(self.cleanup);self.thread.finished.connect(self.thread.deleteLater)
        self.progress.setValue(0);self.log.clear();self.tabs.setCurrentIndex(1);self.status.setText('Starting experiment…' if worker.request else 'Opening completed evidence…')
        self.busy(True);self.activity_changed.emit(True);self.thread.start()

    def on_phase(self,phase):
        if self.prepared and self.prepared.rtl_sweep:
            self.status.setText(phase);self.progress.setRange(0,0);return
        self.status.setText('Proving RTL equivalence…' if phase=='equivalence' else phase.capitalize())
        self.progress.setRange(0,0 if phase=='equivalence' else 7)
        stages={'prepare':0,'equivalence':0,'tool checks':0,'simulation build':1,'simulation':2,'baseline implementation':3,'baseline capture':4,'candidate implementation':5,'candidate capture':6,'compare':6,'completed':7}
        if phase in stages:self.progress.setValue(stages[phase])

    def cancel_job(self):
        if self.worker and self.worker.request:
            self.worker.cancel.set();self.cancel_button.setEnabled(False);self.status.setText('Cancelling the current tool; keeping completed evidence…')

    def completed(self,result):
        self.progress.setRange(0,7)
        if isinstance(result,RTLSweepResult):
            self.result=result;self.progress.setValue(7);self.heading.setText('Priority mux · RTL sweep '+result.status)
            self.location.setText(str(result.directory));self.status.setText(result.status.capitalize()+' · retained evidence opened in RTL variants')
            self.registers.setText('Review registers');self.global_timing.setText('Review design');self.rtl_sweep_requested.emit((result.sweep_path,'register_paths'));return
        self.result=result;self.progress.setValue(7);self.heading.setText(EXAMPLES[result.example].title+' · completed experiment')
        self.registers.setText('Compare registers');self.global_timing.setText('Compare design')
        self.location.setText(str(result.directory));self.status.setText('Completed · register comparison opened in Experiment Lab')
        self.pair_requested.emit(result.register_pair)

    def failed(self,message,status):
        self.progress.setRange(0,7)
        self.status.setText('Cancelled · evidence retained' if status=='cancelled' else 'Experiment failed · evidence retained when staging began')
        self.log.appendPlainText(message);self.location.setText(message)

    def open_pair(self,global_timing):
        if isinstance(self.result,RTLSweepResult):self.rtl_sweep_requested.emit((self.result.sweep_path,'design' if global_timing else 'register_paths'))
        elif self.result:self.pair_requested.emit(self.result.global_pair if global_timing else self.result.register_pair)

    @Slot()
    def cleanup(self):
        self.worker=self.thread=None;self.busy(False);self.activity_changed.emit(False);self.idle.emit()
