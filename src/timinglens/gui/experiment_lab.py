"""Offline experiment comparison workspace. All import/export work runs off the UI."""
from pathlib import Path
import json

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QFrame, QHBoxLayout,
    QLineEdit, QPushButton, QSplitter, QTableView, QTabWidget, QVBoxLayout, QWidget)

from ..experiments import compare, export_comparison, load_run
from ..experiments.compare import number
from ..experiments.recipes import RECIPES, variant_name
from ..experiments.sweep import POLICY, explain, export_sweep, load_sweep
from ..experiments.rtl_sweep import load_rtl_sweep,export_rtl_sweep,pair_paths
from ..timing.coverage import path_coverage
from .widgets import label, set_syntax, text_area
from ..syntax import file_syntax


def words(value): return value.replace('_',' ').capitalize()


class EvidenceTable(QAbstractTableModel):
    def __init__(self, headers, status_column=None):
        super().__init__();self.headers=headers;self.rows=[];self.status_column=status_column
        self.colors={'bad':'#ffaaa2','accent':'#8dd8bd','muted':'#b9b9b9'}

    def populate(self,rows):
        self.beginResetModel();self.rows=list(rows);self.endResetModel()

    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.rows)
    def columnCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.headers)
    def headerData(self,section,orientation,role):
        if role==Qt.ItemDataRole.DisplayRole and orientation==Qt.Orientation.Horizontal:return self.headers[section]
    def data(self,index,role):
        if not index.isValid():return None
        value=self.rows[index.row()][index.column()]
        if role in (Qt.ItemDataRole.DisplayRole,Qt.ItemDataRole.ToolTipRole):
            return number(value) if value is None or isinstance(value,(int,float)) else words(value) if index.column()==self.status_column else str(value)
        if role==Qt.ItemDataRole.ForegroundRole and index.column()==self.status_column:
            color='bad' if value in {'regressed','failed','mismatch','newly_failing'} else 'accent' if value in {'improved','passed','matched','now_passing'} else 'muted'
            return QColor(self.colors[color])


def table(headers, widths, status=None):
    view=QTableView();model=EvidenceTable(headers,status);view.setModel(model)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.setAlternatingRowColors(True);view.setWordWrap(False);view.verticalHeader().hide()
    view.verticalHeader().setDefaultSectionSize(34)
    for i,width in enumerate(widths):view.setColumnWidth(i,max(width,view.horizontalHeader().sectionSizeHint(i)))
    view.horizontalHeader().setStretchLastSection(True)
    return view,model


class LabWorker(QObject):
    finished=Signal(str,object);failed=Signal(str);done=Signal()
    def __init__(self,kind,payload):super().__init__();self.kind=kind;self.payload=payload
    @Slot()
    def run(self):
        try:
            if self.kind in {'import','pair'}:
                paths=self.payload
                if not 1<=len(paths)<=24:raise ValueError('Import between 1 and 24 run files at a time.')
                if sum(path.stat().st_size for path in paths)>256_000_000:
                    raise ValueError('Import at most 256 MB of evidence at a time.')
                loaded=[]
                for path in paths:
                    run=load_run(path);loaded.append((str(path.resolve()),run,run.fingerprint))
                result=(loaded,compare(loaded[0][1],loaded[1][1]) if self.kind=='pair' else None)
            elif self.kind=='compare':result=compare(*self.payload)
            elif self.kind=='sweep':result=load_sweep(*self.payload)
            elif self.kind=='rtl_sweep':result=load_rtl_sweep(*self.payload)
            elif self.kind=='rtl_pair':
                path,population,key=self.payload;review=load_rtl_sweep(path,population)
                paths=pair_paths(review,key);comparison=next(r.comparison for r in review.rows if r.variant==key)
                loaded=[(str(p.resolve()),run,run.fingerprint) for p,run in zip(paths,(comparison.before,comparison.after))]
                result=(loaded,comparison)
            elif self.kind=='export_rtl':result=export_rtl_sweep(*self.payload)
            elif self.kind=='sweep_pair':
                path,population,strategy,overall=self.payload;review=load_sweep(path,population)
                row=next(r for r in review.rows if r.strategy==strategy)
                comparison=row.overall_comparison if overall else row.strategy_comparison
                if comparison is None:raise ValueError('This recipe has no completed comparison evidence.')
                variants=('baseline' if overall else 'candidate',variant_name(strategy))
                loaded=[(str((path.parent/f'runs/{variant}.{population}.run.json').resolve()),run,run.fingerprint)
                        for variant,run in zip(variants,(comparison.before,comparison.after))]
                result=(loaded,comparison)
            elif self.kind=='export_sweep':result=export_sweep(*self.payload)
            else:result=export_comparison(*self.payload)
            self.finished.emit(self.kind,result)
        except Exception as error:self.failed.emit(str(error))
        finally:self.done.emit()


class ExperimentLab(QWidget):
    preferences_changed=Signal(object)
    idle=Signal()
    inspect_requested=Signal(object,str)
    run_requested=Signal()

    def __init__(self,preferences=None):
        super().__init__()
        self.thread=self.worker=self.result=self.sweep_review=None;self.records={};self.order=[];self.paths={}
        self.automatic_pair = None
        self.showing_verified_closure = False
        self.showing_resource_result = False
        self.preferences=preferences if isinstance(preferences,dict) else {}
        self.colors={'bad':'#ffaaa2','accent':'#8dd8bd','muted':'#b9b9b9'}
        self.models=[];self.endpoint_rows=[];self.evidence_items=[]
        layout=QVBoxLayout(self);layout.setContentsMargins(0,8,0,0);layout.setSpacing(10)
        description=label('Compare completed runs. Follow timing changes through to endpoints, source snapshots and build evidence.','Muted')
        description.setWordWrap(True)
        intro=QHBoxLayout();intro.addWidget(description,1)
        run_button=QPushButton('Run counter…');run_button.clicked.connect(self.run_requested.emit);intro.addWidget(run_button)
        layout.addLayout(intro)
        toolbar=QHBoxLayout()
        self.import_button=QPushButton('Import runs…');self.import_button.clicked.connect(self.browse)
        self.recent=QPushButton('Restore history');self.recent.clicked.connect(self.restore_history)
        self.examples=QComboBox();self.examples.setMinimumWidth(180);self.examples.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        for title in ('32-bit counter / registers','64-bit counter / registers','DFX hash / routed','32-bit counter / global OOC','64-bit counter / global OOC'):self.examples.addItem(title)
        self.load_example=QPushButton('Load example');self.load_example.clicked.connect(self.open_example)
        self.export_button=QPushButton('Export comparison…');self.export_button.clicked.connect(self.export_dialog)
        for item in (self.import_button,self.recent,self.examples,self.load_example,self.export_button):toolbar.addWidget(item)
        layout.addLayout(toolbar)
        self.selectors=QWidget();selectors=QHBoxLayout(self.selectors);selectors.setContentsMargins(0,0,0,0)
        self.baseline=QComboBox();self.candidate=QComboBox()
        for title,box in [('BASELINE',self.baseline),('CANDIDATE',self.candidate)]:
            column=QVBoxLayout();column.addWidget(label(title,'Muted'));column.addWidget(box)
            box.setMinimumWidth(120);box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            box.currentIndexChanged.connect(self.selection_changed);selectors.addLayout(column,1)
        self.swap=QPushButton('⇄');self.swap.setToolTip('Swap baseline and candidate');self.swap.clicked.connect(self.swap_runs)
        self.compare_button=QPushButton('Compare');self.compare_button.setObjectName('Primary');self.compare_button.clicked.connect(self.compare_selected)
        selectors.addWidget(self.swap,0,Qt.AlignmentFlag.AlignBottom);selectors.addWidget(self.compare_button,0,Qt.AlignmentFlag.AlignBottom)
        layout.addWidget(self.selectors)
        card=QFrame();self.comparison_card=card;card.setObjectName('Card');hero=QVBoxLayout(card)
        top=QHBoxLayout();self.outcome=label('Build your evidence trail','Metric');self.acceptance=label('','Section')
        top.addWidget(self.outcome);top.addStretch();top.addWidget(self.acceptance);hero.addLayout(top)
        self.headline=label('Load a saved counter or DFX example, or import two TimingLens JSON sessions.')
        self.headline.setWordWrap(True);hero.addWidget(self.headline)
        self.scope=label('Every verdict separates measured changes from acceptance checks.','Muted');self.scope.setWordWrap(True);hero.addWidget(self.scope)
        self.quick_metrics=QWidget();quick=QHBoxLayout(self.quick_metrics);quick.setContentsMargins(0,10,0,4)
        self.metric_cards={}
        for key,title in (('setup.worst_slack_ns','Setup slack · ns'),('setup.failing_endpoints','Failing setup endpoints'),('area.lut_sites','Physical LUTs')):
            column=QVBoxLayout();column.addWidget(label(title,'Muted'))
            value=label('—','Metric');column.addWidget(value);quick.addLayout(column,1);self.metric_cards[key]=value
        hero.addWidget(self.quick_metrics);self.quick_metrics.hide()
        self.next_step=label('','Section');self.next_step.setWordWrap(True);hero.addWidget(self.next_step)
        layout.addWidget(card)
        self.tabs=QTabWidget();layout.addWidget(self.tabs,1)
        self.metrics,self.metric_model=table(('Metric','Baseline','Candidate','Δ','Result'),(260,110,110,95,130),4)
        self.models.append(self.metric_model)
        overview=QWidget();overview_layout=QVBoxLayout(overview);overview_layout.setContentsMargins(0,6,0,0)
        overview_layout.addWidget(self.metrics,1);self.metric_note=label('Select a metric to inspect its measurement source.','Muted');self.metric_note.setWordWrap(True);overview_layout.addWidget(self.metric_note)
        self.metrics.selectionModel().currentRowChanged.connect(self.metric_selected);self.tabs.addTab(overview,'Measurements')
        self.build_endpoints();self.build_acceptance();self.build_evidence()
        self.change=text_area('diff');self.change.setObjectName('CodeEditor');self.tabs.addTab(self.change,'Change preview')
        self.build_sweep()
        from .rtl_variants import RTLVariants
        self.rtl=RTLVariants(self);self.rtl_index=self.tabs.addTab(self.rtl,'RTL variants')
        self.status=label('Ready · completed local evidence only','Muted');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.tabs.currentChanged.connect(self.tab_changed)
        self.busy(False)

    def build_sweep(self):
        page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(0,6,0,0)
        actions=QHBoxLayout();self.open_sweep=QPushButton('Open sweep…');self.open_sweep.clicked.connect(self.browse_sweep)
        self.last_sweep=QPushButton('Open last sweep');self.last_sweep.clicked.connect(lambda:self.import_sweep(Path(self.preferences['last_sweep'])))
        self.population=QComboBox();self.population.addItem('Register paths','register_paths');self.population.addItem('Global OOC','design')
        self.population.currentIndexChanged.connect(self.population_changed)
        actions.addWidget(self.open_sweep);actions.addWidget(self.last_sweep);actions.addStretch();actions.addWidget(self.population);layout.addLayout(actions)
        self.sweep_title=label('Strategy sweeps','Metric');layout.addWidget(self.sweep_title)
        self.sweep_scope=label('Open a counter sweep to rank completed recipes and inspect measured regressions.','Muted');self.sweep_scope.setWordWrap(True);layout.addWidget(self.sweep_scope)
        policy=label('Review priority: no summary regressions or newly failing endpoints first, then hold/pulse/setup failures, TNS and WNS. Rank is not acceptance.','Muted')
        policy.setWordWrap(True);policy.setToolTip(POLICY);layout.addWidget(policy)
        self.sweep_table,self.sweep_model=table(('Rank','Recipe','Vs Default','Setup WNS ns','Setup TNS ns','Setup fails','Hold fails','Hold WNS ns','LUTs','Seconds','Overall acceptance','Build status'),(85,220,110,110,110,95,90,110,65,80,140,100),2)
        self.models.append(self.sweep_model)
        self.sweep_table.setMinimumHeight(160)
        split=QSplitter(Qt.Orientation.Vertical);split.addWidget(self.sweep_table)
        details=QWidget();detail=QVBoxLayout(details);detail.setContentsMargins(0,3,0,0)
        row=QHBoxLayout();self.sweep_strategy=QPushButton('Compare recipe to Default');self.sweep_overall=QPushButton('Compare to original RTL')
        self.sweep_strategy.clicked.connect(lambda:self.compare_sweep_row(False));self.sweep_overall.clicked.connect(lambda:self.compare_sweep_row(True))
        row.addWidget(self.sweep_strategy);row.addWidget(self.sweep_overall);row.addStretch()
        self.sweep_acceptance=label('Acceptance: not tested','Section');row.addWidget(self.sweep_acceptance);detail.addLayout(row)
        self.sweep_detail=text_area();detail.addWidget(self.sweep_detail,1);split.addWidget(details);split.setSizes([190,300]);layout.addWidget(split,1)
        self.sweep_table.selectionModel().currentRowChanged.connect(self.sweep_selected)
        self.sweep_index=self.tabs.addTab(page,'Strategy sweeps')

    def tab_changed(self):
        sweep=self.tabs.currentIndex() in {self.sweep_index,self.rtl_index}
        self.selectors.setVisible(not sweep);self.comparison_card.setVisible(not sweep)
        self.export_button.setText('Export sweep…' if sweep else 'Export comparison…');self.busy(self.thread is not None)

    def browse_sweep(self):
        name,_=QFileDialog.getOpenFileName(self,'Open counter strategy sweep',filter='Sweep manifest (sweep.json)')
        if name:self.import_sweep(Path(name))

    def import_sweep(self,path):self.start('sweep',(Path(path),self.population.currentData()))

    def population_changed(self):
        if self.sweep_review:self.import_sweep(self.sweep_review.path)

    def show_sweep(self,review):
        self.sweep_review=review
        self.population.blockSignals(True);self.population.setCurrentIndex(self.population.findData(review.population));self.population.blockSignals(False)
        self.sweep_title.setText(review.manifest.example.replace('counter','')+'-bit counter · '+words(review.manifest.status))
        self.sweep_scope.setText('Recipe effect: identical candidate RTL versus Default. Overall effect: candidate versus original RTL. One build per recipe.\n'+review.manifest.job_name)
        rows=[]
        for row in review.rows:
            setup=row.run.timing.get('setup') if row.run else None;hold=row.run.timing.get('hold') if row.run else None
            rows.append((row.rank if row.rank is not None else 'Unranked',RECIPES[row.strategy].name,
                row.strategy_comparison.outcome if row.strategy_comparison else 'not_tested',
                setup.worst_slack_ns if setup else None,setup.total_negative_slack_ns if setup else None,setup.failing_endpoints if setup else None,
                hold.failing_endpoints if hold else None,hold.worst_slack_ns if hold else None,row.run.metrics.get('area.lut_sites') if row.run else None,row.seconds,
                words(row.overall_comparison.acceptance) if row.overall_comparison else 'Not tested',row.status))
        self.sweep_model.populate(rows);self.tabs.setCurrentIndex(self.sweep_index)
        self.sweep_table.selectRow(0);self.sweep_selected(self.sweep_model.index(0,0),None)
        self.preferences['last_sweep']=str(review.path.resolve());self.preferences_changed.emit(dict(self.preferences))
        self.status.setText(f'{len(review.rows)} recipes · {sum(r.rank is not None for r in review.rows)} ranked · '+str(review.path))

    def sweep_selected(self,index,_):
        if not self.sweep_review or not index.isValid():return
        row=self.sweep_review.rows[index.row()]
        lines=[RECIPES[row.strategy].name+' · '+row.status,row.reason,'',
            'RECIPE EFFECT — candidate RTL versus Default',*row.explanations,'',
            'OVERALL EFFECT — candidate versus original RTL']
        if row.overall_comparison:lines += ['Acceptance: '+words(row.overall_comparison.acceptance),*explain(row.overall_comparison)]
        else:lines.append('Not tested; no completed original reference or candidate.')
        lines += ['',POLICY]
        self.sweep_detail.setPlainText('\n'.join(lines));self.sweep_buttons(self.thread is not None)
        self.color_sweep_acceptance()

    def color_sweep_acceptance(self):
        index=self.sweep_table.currentIndex()
        row=self.sweep_review.rows[index.row()] if self.sweep_review and index.isValid() else None
        verdict=row.overall_comparison.acceptance if row and row.overall_comparison else 'not_tested'
        self.sweep_acceptance.setText('Acceptance: '+words(verdict).lower())
        self.sweep_acceptance.setStyleSheet('color: '+self.colors['bad' if verdict=='blocked' else 'muted'])

    def sweep_buttons(self,busy):
        index=self.sweep_table.currentIndex();row=self.sweep_review.rows[index.row()] if self.sweep_review and index.isValid() else None
        self.sweep_strategy.setEnabled(not busy and row is not None and row.strategy_comparison is not None)
        self.sweep_overall.setEnabled(not busy and row is not None and row.overall_comparison is not None)

    def compare_sweep_row(self,overall):
        index=self.sweep_table.currentIndex()
        if not self.sweep_review or not index.isValid():return
        review=self.sweep_review;row=review.rows[index.row()];population=review.population
        self.start('sweep_pair',(review.path,population,row.strategy,overall))

    def build_endpoints(self):
        page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(0,6,0,0)
        filters=QHBoxLayout();self.search=QLineEdit(placeholderText='Find an endpoint or clock…');self.search.textChanged.connect(self.filter_endpoints)
        self.endpoint_filter=QComboBox();self.endpoint_filter.addItems(['All captured endpoints','Regressions','Newly failing','Unmatched / ambiguous'])
        self.endpoint_filter.currentIndexChanged.connect(self.filter_endpoints);self.endpoint_count=label('','Muted')
        filters.addWidget(self.search,1);filters.addWidget(self.endpoint_filter);filters.addWidget(self.endpoint_count);layout.addLayout(filters)
        actions=QHBoxLayout();actions.addStretch()
        self.open_before=QPushButton('Inspect baseline path');self.open_after=QPushButton('Inspect candidate path')
        self.open_before.clicked.connect(lambda:self.inspect_path(False));self.open_after.clicked.connect(lambda:self.inspect_path(True))
        actions.addWidget(self.open_before);actions.addWidget(self.open_after);layout.addLayout(actions)
        self.endpoint_table,self.endpoint_model=table(('Result','Check','Endpoint','Baseline ns','Candidate ns','Δ ns'),(125,65,320,100,100,90),0)
        self.models.append(self.endpoint_model)
        split=QSplitter(Qt.Orientation.Vertical);split.addWidget(self.endpoint_table)
        details=QWidget();detail_layout=QVBoxLayout(details);detail_layout.setContentsMargins(0,3,0,0)
        self.match_note=label('Select an endpoint to compare the captured paths.','Muted');self.match_note.setWordWrap(True);detail_layout.addWidget(self.match_note)
        panes=QSplitter(Qt.Orientation.Horizontal);self.before_path=text_area('report');self.after_path=text_area('report')
        for title,pane in [('Baseline path',self.before_path),('Candidate path',self.after_path)]:
            box=QWidget();column=QVBoxLayout(box);column.setContentsMargins(0,0,0,0);column.addWidget(label(title,'Section'));column.addWidget(pane);panes.addWidget(box)
        detail_layout.addWidget(panes);split.addWidget(details);split.setSizes([230,210]);layout.addWidget(split,1)
        self.endpoint_table.selectionModel().currentRowChanged.connect(self.endpoint_selected);self.tabs.addTab(page,'Endpoint changes')

    def build_acceptance(self):
        page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(0,6,0,0)
        self.check_tabs=QTabWidget()
        self.gates,self.gate_model=table(('Check','Status','Scope / evidence'),(235,115,500),1)
        self.context,self.context_model=table(('Build context','Status','Baseline','Candidate','Meaning'),(200,105,260,260,400),1)
        self.models += [self.gate_model,self.context_model]
        self.check_tabs.addTab(self.gates,'Acceptance checks');self.check_tabs.addTab(self.context,'Comparison context')
        layout.addWidget(self.check_tabs,1);self.check_detail=text_area();self.check_detail.setMaximumHeight(125);layout.addWidget(self.check_detail)
        self.gates.selectionModel().currentRowChanged.connect(lambda index,_:self.show_check(index,False))
        self.context.selectionModel().currentRowChanged.connect(lambda index,_:self.show_check(index,True))
        self.tabs.addTab(page,'Checks and context')

    def build_evidence(self):
        page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(0,6,0,0)
        row=QHBoxLayout();self.evidence_side=QComboBox();self.evidence_side.addItems(['Baseline evidence','Candidate evidence'])
        self.evidence_side.currentIndexChanged.connect(self.populate_evidence);self.evidence_file=QComboBox()
        self.evidence_file.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.evidence_file.currentIndexChanged.connect(self.show_evidence)
        row.addWidget(self.evidence_side);row.addWidget(self.evidence_file,1);layout.addLayout(row)
        self.evidence=text_area('json');self.evidence.setObjectName('CodeEditor');layout.addWidget(self.evidence,1);self.tabs.addTab(page,'Evidence and sources')

    def theme(self,colors):
        self.colors=colors
        self.rtl.theme(colors)
        for model in self.models:model.colors=colors;model.layoutChanged.emit()
        self.color_verdict()
        self.color_sweep_acceptance()

    def color_verdict(self):
        if not self.result:return
        self.outcome.setStyleSheet('color: '+self.colors['accent' if self.showing_verified_closure or self.result.outcome=='improved' else 'bad' if self.result.outcome=='regressed' else 'muted'])
        color = 'accent' if self.showing_resource_result else 'bad' if self.result.acceptance=='blocked' else 'muted'
        self.acceptance.setStyleSheet('color: '+self.colors[color])

    def busy(self,value):
        self.rtl.busy(value)
        for button in (self.import_button,self.recent,self.load_example,self.examples,self.baseline,self.candidate,self.swap,self.open_sweep,self.population):button.setEnabled(not value)
        self.recent.setEnabled(not value and bool(self.preferences.get('recent')))
        self.last_sweep.setEnabled(not value and bool(self.preferences.get('last_sweep')));self.sweep_buttons(value)
        valid=self.baseline.currentData() is not None and self.candidate.currentData() is not None
        self.compare_button.setEnabled(not value and valid)
        exportable=self.rtl.review is not None if self.tabs.currentIndex()==self.rtl_index else self.sweep_review is not None if self.tabs.currentIndex()==self.sweep_index else self.result is not None and self.selection_matches()
        self.export_button.setEnabled(not value and exportable)

    def selection_matches(self):
        return self.result is not None and self.records.get(self.baseline.currentData()) is self.result.before and self.records.get(self.candidate.currentData()) is self.result.after

    def selection_changed(self):
        if self.result and not self.selection_matches():self.status.setText('Selection changed · click Compare to refresh the displayed result.')
        self.busy(self.thread is not None)

    def swap_runs(self):
        a,b=self.baseline.currentIndex(),self.candidate.currentIndex()
        self.baseline.setCurrentIndex(b);self.candidate.setCurrentIndex(a)

    def browse(self):
        names,_=QFileDialog.getOpenFileNames(self,'Import run records or native timing sessions',filter='TimingLens evidence (*.json)')
        if names:self.import_paths([Path(n) for n in names])

    def import_paths(self,paths,pair=False):self.start('pair' if pair else 'import',paths)

    def restore_history(self):
        recent=self.preferences.get('recent',[])
        if isinstance(recent,list):self.import_paths([Path(p) for p in recent[-24:] if isinstance(p,str)])

    def open_example(self):
        root=Path(__file__).resolve().parents[3]/'work/experiment-lab/catalog'
        names=[('unsigned32_ge-internal-before','unsigned32_ge-internal-after'),('unsigned64_gt-internal-before','unsigned64_gt-internal-after'),
               ('dfx-failing','dfx-passing'),('unsigned32_ge-global-before','unsigned32_ge-global-after'),('unsigned64_gt-global-before','unsigned64_gt-global-after')]
        paths=[root/(name+'.run.json') for name in names[self.examples.currentIndex()]]
        if not all(p.is_file() for p in paths):
            self.status.setText('Saved examples are unavailable here. Import run files, or prepare the retained captures with scripts/prepare_experiment_lab.py.');return
        self.import_paths(paths,pair=True)

    def compare_selected(self):
        if self.baseline.currentData() in self.records and self.candidate.currentData() in self.records:
            self.start('compare',(self.records[self.baseline.currentData()],self.records[self.candidate.currentData()]))

    def export_dialog(self):
        kind='rtl-sweep' if self.tabs.currentIndex()==self.rtl_index else 'sweep' if self.tabs.currentIndex()==self.sweep_index else 'comparison'
        name=QFileDialog.getExistingDirectory(self,'Choose the parent folder for a new '+kind+' export')
        if name:
            parent=Path(name);index=1
            while (parent/f'timinglens-{kind}-{index:02}').exists():index+=1
            self.export_to(parent/f'timinglens-{kind}-{index:02}')

    def export_to(self,path):
        if self.tabs.currentIndex()==self.rtl_index and self.rtl.review:self.start('export_rtl',(self.rtl.review.path,Path(path),self.rtl.review.max_luts))
        elif self.tabs.currentIndex()==self.sweep_index and self.sweep_review:self.start('export_sweep',(self.sweep_review.path,Path(path)))
        elif self.result and self.selection_matches():self.start('export',(self.result,Path(path)))

    def start(self,kind,payload):
        if self.thread:return
        self.thread=QThread(self);self.worker=LabWorker(kind,payload);self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run);self.worker.finished.connect(self.finished)
        self.worker.failed.connect(self.failed_operation)
        self.worker.done.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.cleanup);self.thread.finished.connect(self.thread.deleteLater)
        self.busy(True);self.status.setText({'rtl_sweep':'Validating RTL proofs and tradeoffs…','rtl_pair':'Validating selected RTL comparison…','export_rtl':'Writing portable RTL sweep…','pair':'Loading and comparing saved evidence…','sweep_pair':'Validating recipe comparison…','import':'Importing evidence…','compare':'Comparing measured results…','export':'Writing portable comparison…','sweep':'Validating and ranking sweep evidence…','export_sweep':'Writing portable sweep…'}[kind]);self.thread.start()

    def failed_operation(self,error):
        self.rtl.restore_controls()
        if self.sweep_review:
            self.population.blockSignals(True);self.population.setCurrentIndex(self.population.findData(self.sweep_review.population));self.population.blockSignals(False)
        self.status.setText('Could not complete operation: '+error)

    @Slot(str,object)
    def finished(self,kind,value):
        if kind in {'import','pair','sweep_pair','rtl_pair'}:
            loaded,result=value
            # Keep a bounded in-memory history; selected imports are always retained.
            for path,run,key in loaded:
                if key in self.order:self.order.remove(key)
                self.order.append(key);self.records[key]=run;self.paths[key]=path
            while len(self.order)>24:
                old=self.order.pop(0);self.records.pop(old);self.paths.pop(old)
            for box in (self.baseline,self.candidate):
                box.blockSignals(True);box.clear()
                for key in self.order:box.addItem(self.records[key].label+' · '+key[:7],key)
                box.blockSignals(False)
            keys=[item[2] for item in loaded]
            baseline=keys[0] if len(keys)>1 else self.preferences.get('baseline',self.order[0])
            candidate=keys[-1]
            if kind=='import':
                baseline=self.preferences.get('baseline',baseline) if self.preferences.get('baseline') in self.order else baseline
                candidate=self.preferences.get('candidate',candidate) if self.preferences.get('candidate') in self.order else candidate
            self.baseline.setCurrentIndex(max(0,self.baseline.findData(baseline)));self.candidate.setCurrentIndex(max(0,self.candidate.findData(candidate)))
            self.preferences['recent']=[self.paths[key] for key in self.order];self.preferences_changed.emit(dict(self.preferences))
            self.status.setText(f'Imported {len(loaded)} runs · select a baseline and candidate, then Compare.')
            if result:self.show_result(result)
        elif kind=='compare':self.show_result(value)
        elif kind=='sweep':self.show_sweep(value)
        elif kind=='rtl_sweep':self.rtl.show_review(value)
        else:self.status.setText('Exported report and self-contained run evidence to '+str(value))

    def show_result(self,result):
        self.tabs.setCurrentIndex(0)
        self.result=result;self.outcome.setText(words(result.outcome));self.acceptance.setText('Acceptance: '+words(result.acceptance).lower())
        self.headline.setText(result.headline)
        self.scope.setText(result.before.label+' → '+result.after.label+'\n'+('Provisional · missing build context. ' if any(c.status=='unknown' for c in result.context) else '')+'Δ = candidate − baseline. Acceptance does not follow from WNS alone.')
        self.update_summary(result)
        self.showing_verified_closure = False
        self.showing_resource_result = False
        self.acceptance.setToolTip("")
        if self.automatic_pair:
            pair, message, verified, resource_summary = self.automatic_pair
            selected = tuple(str(self.paths.get(box.currentData())) for box in (self.baseline, self.candidate))
            if pair == selected:
                self.next_step.setText(message)
                self.showing_verified_closure = verified
                if verified and resource_summary:
                    self.showing_resource_result = True
                    self.outcome.setText("Resource budget met")
                    self.acceptance.setText("Verified · routed timing passed")
                    self.acceptance.setToolTip("The automatic resource policy permits reduced positive slack. "
                                               "Checks and context includes the general Lab regression guard.")
                    self.headline.setText(resource_summary)
                    if result.before.session.stage == "synthesized":
                        self.scope.setText("Synthesized baseline → routed candidate. Timing is available for the candidate only.")
                elif verified:
                    self.outcome.setText("Timing closed")
                    self.acceptance.setText("Lab acceptance: " + words(result.acceptance).lower())
                    count = result.before.timing["setup"].failing_endpoints
                    self.headline.setText(f"Failing setup endpoints fell from {count:,} to zero in the routed design."
                                          if count is not None else "The routed candidate meets setup, hold and pulse width.")
        self.metric_model.populate((m.label+' ('+m.unit+')',m.before,m.after,m.delta,m.status) for m in result.metrics)
        self.gate_model.populate((g.name,g.status,g.detail) for g in result.gates)
        self.context_model.populate((c.name,c.status,c.before,c.after,c.detail) for c in result.context)
        self.change.setPlainText(result.after.change_diff or 'No change preview was supplied in the candidate run.')
        self.check_detail.setPlainText('\n\n'.join(result.notes));self.filter_endpoints();self.populate_evidence();self.color_verdict()
        self.preferences.update(baseline=self.baseline.currentData(),candidate=self.candidate.currentData());self.preferences_changed.emit(dict(self.preferences))
        self.status.setText('Compared completed evidence · '+str(len(result.endpoints))+' captured endpoint groups · source files unchanged by comparison')
        budget = next((gate for gate in result.gates if gate.name == "Resource budget"), None)
        self.metric_note.setText(budget.detail if budget else "Select a metric to inspect its measurement source.")
        self.busy(self.thread is not None)

    def update_summary(self,result):
        metrics={metric.key:metric for metric in result.metrics}
        for key,widget in self.metric_cards.items():
            metric=metrics.get(key)
            def display(value):
                if value is None:return 'Not supplied'
                return f'{value:+.3f}' if key.endswith('worst_slack_ns') else number(value)
            widget.setText(display(metric.before)+' → '+display(metric.after) if metric else 'Not supplied')
        self.quick_metrics.show()
        failed=[gate.name for gate in result.gates if gate.status=='failed']
        pending=[gate.name for gate in result.gates if gate.status=='not_tested']
        if failed:
            message='Next: resolve '+', '.join(failed)+'.'
        elif result.acceptance=='blocked':
            message='Next: review the regressions in Measurements and Checks and context.'
        elif pending:
            message='Still to verify: '+', '.join(pending)+'.'
        else:
            message='All supplied acceptance checks passed. Export the evidence for review.'
        scope='Whole design' if result.after.population=='design' else 'Register paths only'
        if result.after.context.mode=='out_of_context':scope+=' · out of context'
        elif result.after.context.mode=='integrated':scope+=' · top-level build'
        else:scope+=' · '+words(result.after.context.mode)
        self.next_step.setText(scope+'\n'+message)

    def metric_selected(self,index,_):
        if self.result and index.isValid():self.metric_note.setText(self.result.metrics[index.row()].evidence)

    def show_check(self,index,context):
        if not self.result or not index.isValid():return
        row=(self.result.context if context else self.result.gates)[index.row()]
        self.check_detail.setPlainText(row.name+' · '+words(row.status)+'\n'+(f'Baseline: {row.before}\nCandidate: {row.after}\n' if context else '')+row.detail)

    def filter_endpoints(self):
        if not self.result:return
        groups={1:{'regressed','newly_failing'},2:{'newly_failing'},3:{'baseline_only','candidate_only','ambiguous'}}
        statuses=groups.get(self.endpoint_filter.currentIndex());needle=self.search.text().casefold()
        self.endpoint_rows=[r for r in self.result.endpoints if (statuses is None or r.status in statuses) and (not needle or needle in (r.endpoint+' '+r.clocks).casefold())]
        self.endpoint_model.populate((r.status,r.analysis,r.endpoint,r.before_slack,r.after_slack,r.delta) for r in self.endpoint_rows)
        self.endpoint_count.setText(f'{len(self.endpoint_rows)} / {len(self.result.endpoints)}')
        self.before_path.clear();self.after_path.clear();self.match_note.setText('Captured names and clock pairs establish correspondence, not netlist equivalence. Unmatched does not mean new or removed.')
        self.open_before.setEnabled(False);self.open_after.setEnabled(False)
        if self.endpoint_rows:self.endpoint_table.selectRow(0)
        else:
            self.match_note.setText('No captured rows match this filter. Summary totals cover a larger population than this capped path sample; an empty list does not clear a reported regression.')

    def endpoint_selected(self,index,_):
        if not index.isValid() or not self.result:return
        row=self.endpoint_rows[index.row()];self.match_note.setText(row.basis+' '+row.clocks)
        self.open_before.setEnabled(row.before_id is not None);self.open_after.setEnabled(row.after_id is not None)
        for pane,run,path_id in [(self.before_path,self.result.before,row.before_id),(self.after_path,self.result.after,row.after_id)]:
            path=next((p for p in run.session.paths if p.id==path_id),None)
            if path is None:pane.setPlainText('No corresponding path was captured.');continue
            coverage=path_coverage(path)
            text=[f'{path.id} · {path.analysis} · slack {number(path.slack_ns)} ns',f'{path.startpoint} → {path.endpoint}',
                  f'Logic {number(path.logic_ns)} ns / route {number(path.routing_ns)} ns / levels {number(path.levels)}',
                  f'Detail coverage: {coverage.measured_delays}/{coverage.captured_arcs} arc delays; {coverage.captured_links}/{coverage.expected_links} pin links.',
                  'See Evidence and sources for full captured reports and RTL.','',json.dumps(path.model_dump(mode='json'),indent=2)]
            pane.setPlainText('\n'.join(text))

    def inspect_path(self,candidate):
        index=self.endpoint_table.currentIndex()
        if not self.result or not index.isValid():return
        row=self.endpoint_rows[index.row()];path_id=row.after_id if candidate else row.before_id
        if path_id:self.inspect_requested.emit((self.result.after if candidate else self.result.before).session,path_id)

    def populate_evidence(self):
        if not self.result:return
        run=self.result.before if self.evidence_side.currentIndex()==0 else self.result.after
        provenance={'run_sha256':run.fingerprint,'checkpoint_sha256':run.context.checkpoint_sha256,'population':run.population,
                    'captured_at':run.session.timestamp,'device':run.session.part,'vivado':run.session.vivado,
                    'context':run.context.model_dump(mode='json'),'notes':[*self.result.notes,*run.notes],
                    'artifacts':[a.model_dump(mode='json') for a in run.artifacts]}
        self.evidence_items=[('Provenance & limitations',json.dumps(provenance,indent=2))]
        self.evidence_items += [('Attachment / '+name,text) for name,text in run.attachments.items()]
        self.evidence_items += [('Report / '+name,text) for name,text in sorted(run.session.reports.items())]
        self.evidence_items += [('Source / '+source.path,'Recorded SHA-256: '+str(source.sha256)+'\nCaptured snapshot; file paths are descriptive.\n\n'+(source.text if source.text is not None else 'Source text was not captured.')) for source in run.session.sources]
        self.evidence_file.blockSignals(True);self.evidence_file.clear()
        for name,_ in self.evidence_items:self.evidence_file.addItem(name)
        self.evidence_file.blockSignals(False);self.show_evidence()

    def show_evidence(self):
        index=self.evidence_file.currentIndex()
        if 0<=index<len(self.evidence_items):
            name,text=self.evidence_items[index];self.evidence_file.setToolTip(name)
            set_syntax(self.evidence, 'json' if index == 0 else file_syntax(name))
            self.evidence.setPlainText(text[:300000]+('\n\nPreview truncated at 300,000 characters. Full text remains in the exported run.' if len(text)>300000 else ''))

    @Slot()
    def cleanup(self):
        # finished() can reach the GUI before the worker thread finishes native teardown.
        self.thread.wait()
        self.worker=self.thread=None;self.busy(False);self.idle.emit()
