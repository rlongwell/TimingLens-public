"""Counter experiment controls; tool work and cancellation stay outside the UI thread."""
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Event
from uuid import uuid4

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit,
    QProgressBar, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from ..experiments.counters import plan_counter, COUNTERS
from ..experiments.io import load_run
from ..experiments.runner import CounterRequest, CounterResult, JobFailure, run_counter, workspace_root
from ..experiments.recipes import RECIPES
from ..experiments.sweep import load_sweep, referenced_path
from .widgets import label, text_area


def read_completed_job(directory):
    directory=Path(directory)
    if (directory/'sweep.json').is_file():
        reviews=[load_sweep(directory/'sweep.json',p) for p in ('register_paths','design')]
        if reviews[0].manifest!=reviews[1].manifest:raise ValueError('Sweep changed while reading; reopen after the current build.')
        pairs=[]
        for review in reviews:
            manifest=review.manifest;default=manifest.strategies[0]
            pairs.append(tuple(referenced_path(review.path,ref,variant,review.population) for ref,variant in
                [(manifest.baseline[review.population],'baseline'),(default.records[review.population],'candidate')])
                if review.baseline and review.reference else ())
        return CounterResult(directory,*pairs,manifest.example,directory/'sweep.json',manifest.status)
    with (directory/'job.json').open('rb') as stream:raw=stream.read(1_000_001)
    if len(raw)>1_000_000:raise ValueError('Job manifest exceeds its size limit.')
    state=json.loads(raw)
    if state.get('timinglens_job')!=1 or state.get('status')!='completed':
        raise ValueError('This job is not completed: '+str(state.get('status','unknown'))+'. '+str(state.get('error','')))
    if state.get('example') not in COUNTERS:raise ValueError('Unknown counter example in completed job.')
    pairs={}
    for population in ('register_paths','design'):
        pair=[]
        for variant in ('baseline','candidate'):
            relative=f'runs/{variant}.{population}.run.json'
            if state.get('pairs',{}).get(population,{}).get(variant)!=relative:
                raise ValueError('Unexpected run path in counter manifest.')
            path=directory/relative
            if not path.resolve().is_relative_to(directory.resolve()):raise ValueError('Run record points outside the selected job.')
            if load_run(path).population!=population:raise ValueError('Run population disagrees with its job manifest.')
            pair.append(path)
        pairs[population]=tuple(pair)
    return CounterResult(directory,pairs['register_paths'],pairs['design'],state['example'])


class CounterWorker(QObject):
    log=Signal(str);phase=Signal(str);finished=Signal(object);failed=Signal(str,str);done=Signal()
    def __init__(self,request=None,directory=None):
        super().__init__();self.request=request;self.directory=directory;self.cancel=Event()
    @Slot()
    def run(self):
        try:
            result=(run_counter(self.request,self.log.emit,self.phase.emit,self.cancel) if self.request
                    else read_completed_job(self.directory))
            if not self.request:
                self.log.emit('Restored '+result.status+' job: '+str(result.directory))
                for relative in ('simulation/simulation.log','baseline/vivado.log','candidate/vivado.log'):
                    path=result.directory/relative
                    if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(result.directory.resolve()):
                        with path.open('rb') as stream:
                            stream.seek(max(0,path.stat().st_size-12000));tail=stream.read(12000).decode(errors='replace')
                        self.log.emit('\n'+relative+' (last 12 KB)\n'+tail)
            self.finished.emit(result)
        except JobFailure as error:
            self.failed.emit(str(error),error.status)
            if (error.directory/'sweep.json').is_file():
                try:self.finished.emit(read_completed_job(error.directory))
                except Exception as read_error:self.log.emit('Could not reopen sweep evidence: '+str(read_error))
        except Exception as error:self.failed.emit(str(error),'failed')
        finally:self.done.emit()


class CounterRunner(QWidget):
    preferences_changed=Signal(object)
    pair_requested=Signal(object)
    sweep_requested=Signal(object)
    idle=Signal()
    activity_changed=Signal(bool)

    def __init__(self,preferences=None,vivado=''):
        super().__init__();self.preferences=preferences if isinstance(preferences,dict) else {}
        self.thread=self.worker=self.result=None;self.external_busy=False
        body=QVBoxLayout(self);body.setContentsMargins(0,8,0,0);body.setSpacing(10)
        intro=label('Run a counter fix in fresh baseline and candidate copies. Validate behavior, route both variants, then compare the evidence in Experiment Lab.','Muted')
        intro.setWordWrap(True);body.addWidget(intro)
        form=QFormLayout();self.example=QComboBox();self.example.addItem('32-bit unsigned counter · ≥','counter32');self.example.addItem('64-bit unsigned counter · >','counter64')
        self.example.addItem('32-bit counter · 250 MHz core','counter32_250')
        self.example.setCurrentIndex(max(0,self.example.findData(self.preferences.get('example','counter32'))))
        self.mode=QComboBox();self.mode.addItem('Single recipe · Default',False);self.mode.addItem('Strategy sweep · 3 recipes',True)
        self.mode.setCurrentIndex(1 if self.preferences.get('sweep') is True else 0)
        self.vivado=QLineEdit(str(self.preferences.get('vivado',vivado)));self.vivado.setPlaceholderText('Auto-detect Vivado 2024.2')
        self.output=QLineEdit(str(self.preferences.get('output',workspace_root()/'results/experiments')))
        destination=QHBoxLayout();destination.addWidget(self.output,1);self.browse=QPushButton('Choose folder…');destination.addWidget(self.browse);self.browse.clicked.connect(self.choose_folder)
        self.timeout=QSpinBox();self.timeout.setRange(30,7200);self.timeout.setSuffix(' s per tool')
        configured=self.preferences.get('timeout',900);self.timeout.setValue(configured if isinstance(configured,int) else 900)
        form.addRow('Counter example',self.example);form.addRow('Implementation',self.mode)
        body.addLayout(form)
        self.advanced_toggle=QPushButton('Advanced settings ▸');self.advanced_toggle.setCheckable(True)
        body.addWidget(self.advanced_toggle)
        self.advanced=QWidget();advanced=QFormLayout(self.advanced);advanced.setContentsMargins(0,0,0,0)
        advanced.addRow('Vivado executable',self.vivado);advanced.addRow('Results parent folder',destination);advanced.addRow('Timeout',self.timeout)
        body.addWidget(self.advanced);self.advanced.hide()
        self.advanced_toggle.toggled.connect(self.advanced.setVisible)
        self.advanced_toggle.toggled.connect(lambda value:self.advanced_toggle.setText('Advanced settings ▾' if value else 'Advanced settings ▸'))
        self.budget=label('','Muted')
        self.budget.setWordWrap(True);body.addWidget(self.budget)
        actions=QHBoxLayout();self.start_button=QPushButton('Validate and run experiment');self.start_button.setObjectName('Primary');self.start_button.clicked.connect(self.start_job)
        self.cancel_button=QPushButton('Cancel');self.cancel_button.clicked.connect(self.cancel_job)
        self.restore=QPushButton('Open last job');self.restore.clicked.connect(self.restore_job)
        self.registers=QPushButton('Compare registers');self.registers.clicked.connect(lambda:self.open_pair(False))
        self.global_timing=QPushButton('Compare whole core');self.global_timing.clicked.connect(lambda:self.open_pair(True))
        for widget in (self.start_button,self.cancel_button,self.restore,self.registers,self.global_timing):actions.addWidget(widget)
        actions.addStretch();body.addLayout(actions)
        self.status=label('Ready · choose an example and review the change below.','Section');self.status.setWordWrap(True);body.addWidget(self.status)
        self.progress=QProgressBar();self.progress.setRange(0,7);self.progress.setValue(0);self.progress.setTextVisible(False);self.progress.setMaximumHeight(8);body.addWidget(self.progress)
        self.tabs=QTabWidget();self.preview=text_area('diff');self.preview.setObjectName('CodeEditor');self.log=text_area('log');self.log.document().setMaximumBlockCount(1500)
        self.tabs.addTab(self.preview,'RTL change');self.tabs.addTab(self.log,'Live log')
        self.plan_details=text_area('tcl');self.tabs.addTab(self.plan_details,'Validation and recipe');body.addWidget(self.tabs,1)
        self.location=label('Every job keeps its inputs, patch, simulation, build logs and completed captures.','Muted');self.location.setWordWrap(True);body.addWidget(self.location)
        self.example.currentIndexChanged.connect(self.update_preview);self.mode.currentIndexChanged.connect(self.update_preview);self.update_preview();self.busy(False)

    def update_preview(self):
        try:
            plan=plan_counter(self.example.currentData())
            self.budget.setText(f'xc7z020clg400-1 · {COUNTERS[plan.name].period_ns:g} ns clock · OOC · Vivado 2024.2 · 2 threads · sequential builds')
            strategies=tuple(RECIPES) if self.mode.currentData() else ('default',)
            recipes='\n'.join(RECIPES[s].name+':\n  '+'\n  '.join(RECIPES[s].commands()) for s in strategies)
            self.preview.setPlainText(plan.diff)
            self.plan_details.setPlainText(plan.document()['scope']+f'\n\nValidation: 10,289 finite baseline/candidate/oracle cycles, then {1+len(strategies)} routed builds.\nOriginal RTL uses Default. Each candidate recipe uses identical RTL and constraints.\n\n'+recipes+'\n\nStrategy reference: candidate RTL with Default. Overall reference: original RTL with Default.\nRank is review priority, never acceptance. Single trial per recipe; failed or cancelled jobs keep their evidence.')
            self.plan_ok=True
        except Exception as error:self.preview.setPlainText(str(error));self.plan_ok=False
        self.start_button.setEnabled(self.plan_ok and not self.thread and not self.external_busy)

    def busy(self,value):
        for widget in (self.example,self.mode,self.vivado,self.output,self.browse,self.timeout):widget.setEnabled(not value)
        self.start_button.setEnabled(not value and self.plan_ok and not self.external_busy)
        self.cancel_button.setEnabled(value and self.worker is not None and self.worker.request is not None)
        self.restore.setEnabled(not value and bool(self.preferences.get('last_job')))
        self.registers.setEnabled(not value and self.result is not None)
        self.registers.setText('View sweep' if self.result and self.result.sweep else 'Compare registers')
        self.global_timing.setEnabled(not value and self.result is not None and bool(self.result.global_pair))

    def set_external_busy(self,value):self.external_busy=value;self.busy(self.thread is not None)

    def choose_folder(self):
        name=QFileDialog.getExistingDirectory(self,'Choose parent for new experiment jobs',self.output.text())
        if name:self.output.setText(name)

    def start_job(self):
        if self.thread or self.external_busy or not self.plan_ok:return
        parent=Path(self.output.text()).expanduser()
        if not self.output.text().strip():self.status.setText('Choose a results parent folder.');return
        directory=parent/(self.example.currentData()+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8])
        request=CounterRequest(self.example.currentData(),directory,self.vivado.text().strip() or None,timeout=float(self.timeout.value()),strategies=tuple(RECIPES) if self.mode.currentData() else ('default',))
        self.preferences.update(example=request.example,vivado=self.vivado.text(),output=str(parent),timeout=self.timeout.value(),sweep=bool(self.mode.currentData()),last_job=str(directory.absolute()))
        self.preferences_changed.emit(dict(self.preferences));self.location.setText(str(directory.absolute()))
        self.run_worker(CounterWorker(request=request))

    def restore_job(self):
        if self.preferences.get('last_job'):self.run_worker(CounterWorker(directory=Path(self.preferences['last_job'])))

    def run_worker(self,worker):
        if self.thread:return
        self.result=None;self.progress.setRange(0,11 if worker.request and len(worker.request.strategies)>1 else 7);self.progress.setValue(0)
        self.worker=worker;self.thread=QThread(self);worker.moveToThread(self.thread)
        self.thread.started.connect(worker.run);worker.log.connect(self.log.appendPlainText);worker.phase.connect(self.on_phase)
        worker.finished.connect(self.completed);worker.failed.connect(self.failed);worker.done.connect(self.thread.quit);worker.done.connect(worker.deleteLater)
        self.thread.finished.connect(self.cleanup);self.thread.finished.connect(self.thread.deleteLater)
        self.log.clear();self.status.setText('Starting isolated experiment…' if worker.request else 'Opening completed evidence…')
        self.tabs.setCurrentIndex(1);self.busy(True);self.activity_changed.emit(True);self.thread.start()

    def on_phase(self,phase):
        descriptions={'prepare':'1 / 4 · Preparing isolated source copies',
            'tool checks':'1 / 4 · Checking Vivado and Verilator',
            'simulation build':'1 / 4 · Building the behavior check',
            'simulation':'1 / 4 · Checking baseline and candidate against an independent oracle',
            'baseline implementation':'2 / 4 · Building and routing the baseline',
            'baseline capture':'2 / 4 · Collecting baseline timing and area',
            'candidate implementation':'3 / 4 · Building and routing the candidate',
            'candidate capture':'3 / 4 · Collecting candidate timing and area',
            'compare':'4 / 4 · Comparing timing, area and validation',
            'publish':'4 / 4 · Saving evidence for Experiment Lab'}
        self.status.setText(descriptions.get(phase,phase.replace('_',' ').capitalize()))
        phases={'prepare':0,'tool checks':0,'simulation build':1,'simulation':2,'baseline implementation':3,'baseline capture':4,
                'candidate implementation':5,'candidate capture':6,'candidate_explore implementation':7,'candidate_explore capture':8,
                'candidate_extra_timing implementation':9,'candidate_extra_timing capture':10,
                'compare':self.progress.maximum()-1,'publish':self.progress.maximum(),'completed':self.progress.maximum(),'partial':self.progress.maximum()}
        if phase in phases:self.progress.setValue(phases[phase])

    def cancel_job(self):
        if self.worker and self.worker.request:
            self.worker.cancel.set();self.cancel_button.setEnabled(False);self.status.setText('Cancelling the current tool; preserving job evidence…')

    def completed(self,result):
        self.result=result
        if result.status in {'completed','partial'}:self.progress.setValue(self.progress.maximum())
        if result.example in COUNTERS:self.example.setCurrentIndex(self.example.findData(result.example))
        self.mode.setCurrentIndex(1 if result.sweep else 0)
        self.status.setText(result.status.capitalize()+': '+(result.example or result.directory.name)+' · evidence opened in Experiment Lab')
        self.location.setText(str(result.directory))
        if result.sweep:self.sweep_requested.emit(result.sweep)
        elif result.example=='counter32_250' and result.global_pair:self.pair_requested.emit(result.global_pair)
        elif result.register_pair:self.pair_requested.emit(result.register_pair)

    def failed(self,message,status):
        self.status.setText('Cancelled · evidence retained' if status=='cancelled' else 'Experiment failed · evidence retained when staging began')
        self.log.appendPlainText(message);self.location.setText(message)

    def open_pair(self,global_timing):
        if not self.result:return
        if self.result.sweep and not global_timing:self.sweep_requested.emit(self.result.sweep)
        else:self.pair_requested.emit(self.result.global_pair if global_timing else self.result.register_pair)

    @Slot()
    def cleanup(self):
        self.worker=self.thread=None;self.busy(False);self.activity_changed.emit(False);self.idle.emit()
