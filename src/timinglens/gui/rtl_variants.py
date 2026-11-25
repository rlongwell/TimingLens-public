"""Measured priority-mux tradeoffs, with acceptance kept visible and independent."""
from PySide6.QtCore import Qt,Signal,QRectF,QPointF
from PySide6.QtGui import QColor,QPainter,QPen
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QComboBox,QPushButton,QSpinBox,QSplitter,QFileDialog
from pathlib import Path
from ..experiments.priority_variants import VARIANTS
from ..experiments.rtl_sweep import POLICY
from ..experiments.compare import number
from .widgets import label,text_area

def title(key):return VARIANTS[key].title if key in VARIANTS else 'Original'

class TradeoffPlot(QWidget):
    selected=Signal(int)
    def __init__(self):
        super().__init__();self.review=None;self.points=[];self.current=-1
        self.colors={'text':'#eeeeee','muted':'#b9b9b9','border':'#505050','accent':'#8dd8bd','bad':'#ffaaa2'}
        self.setMinimumSize(260,160);self.setToolTip('Higher setup WNS and fewer LUTs are better. Click a point to inspect its evidence. The frontier does not establish acceptance.')
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);c=self.colors
        p.setPen(QColor(c['text']));p.drawText(QRectF(0,0,self.width(),26),Qt.AlignmentFlag.AlignCenter,'Timing / area · upper left is better')
        box=QRectF(50,48,self.width()-105,self.height()-99);p.setPen(QPen(QColor(c['border']),1));p.drawRect(box)
        self.points=[]
        rows=[(i,r) for i,r in enumerate(self.review.rows) if r.frontier!='Not comparable'] if self.review else []
        if not rows:
            p.setPen(QColor(c['muted']));p.drawText(box,Qt.AlignmentFlag.AlignCenter,'No comparable measurements');return
        xs=[r.run.metrics['area.lut_cells'] for _,r in rows];ys=[r.run.timing['setup'].worst_slack_ns for _,r in rows]
        x0,x1=min(xs),max(xs);y0,y1=min(ys),max(ys);dx=max(1,x1-x0);dy=max(.1,y1-y0)
        x0-=dx*.12;x1+=dx*.12;y0-=dy*.17;y1+=dy*.17
        p.setPen(QColor(c['muted']));p.drawText(QRectF(0,box.top()-8,46,20),Qt.AlignmentFlag.AlignRight,number(y1))
        p.drawText(QRectF(0,box.bottom()-10,46,20),Qt.AlignmentFlag.AlignRight,number(y0))
        p.drawText(QRectF(box.left()-10,box.bottom()+5,60,20),Qt.AlignmentFlag.AlignLeft,f'{x0:.0f}')
        p.drawText(QRectF(box.right()-30,box.bottom()+5,60,20),Qt.AlignmentFlag.AlignRight,f'{x1:.0f}')
        p.drawText(QRectF(0,self.height()-23,self.width(),20),Qt.AlignmentFlag.AlignCenter,'Logical LUTs · setup WNS in ns')
        for i,row in rows:
            x=row.run.metrics['area.lut_cells'];y=row.run.timing['setup'].worst_slack_ns
            point=QPointF(box.left()+(x-x0)/(x1-x0)*box.width(),box.bottom()-(y-y0)/(y1-y0)*box.height());self.points.append((i,point))
        occupied=[]
        for (i,row),(_,point) in zip(rows,self.points):
            color=c['accent'] if row.frontier=='Frontier' else c['muted'];p.setPen(QPen(QColor(color),2));p.setBrush(QColor(color))
            p.drawEllipse(point,5,5)
            if i==self.current:p.setBrush(Qt.BrushStyle.NoBrush);p.drawEllipse(point,9,9)
            p.setPen(QColor(c['text']));short=['Original','Balanced','Grouped','Mask'][i]
            width=p.fontMetrics().horizontalAdvance(short)+8
            choices=[]
            for dx,dy in [(-width/2,-26),(-width/2,12),(-width/2,-44),(12,-9),(-width-12,-9)]:
                rect=QRectF(min(max(2,point.x()+dx),self.width()-width-2),max(28,min(point.y()+dy,self.height()-43)),width,18)
                choices.append(rect)
            rect=next((r for r in choices if not any(r.intersects(other) for other in occupied) and not any(r.intersects(QRectF(pt.x()-9,pt.y()-9,18,18)) for _,pt in self.points)),choices[0])
            occupied.append(rect);p.drawText(rect,Qt.AlignmentFlag.AlignCenter,short)
    def mousePressEvent(self,event):
        if not self.points:return
        i,point=min(self.points,key=lambda item:(event.position()-item[1]).manhattanLength())
        if (event.position()-point).manhattanLength()<28:self.selected.emit(i)

class RTLVariants(QWidget):
    def __init__(self,lab):
        super().__init__();self.lab=lab;self.review=None
        from .experiment_lab import table
        layout=QVBoxLayout(self);layout.setContentsMargins(0,6,0,0)
        actions=QHBoxLayout();self.open=QPushButton('Open RTL sweep…');self.last=QPushButton('Open last');self.population=QComboBox()
        self.population.addItem('Register paths','register_paths');self.population.addItem('Full example','design')
        self.limit=QSpinBox();self.limit.setRange(0,1_000_000);self.limit.setSpecialValueText('No LUT limit');self.limit.setSuffix(' LUTs');self.limit.setToolTip('Optional review limit; zero leaves it unset. Does not change the measured frontier or acceptance.')
        saved=lab.preferences.get('rtl_max_luts',0);self.limit.setValue(saved if type(saved) is int else 0)
        for w in (self.open,self.last):actions.addWidget(w)
        actions.addStretch();actions.addWidget(self.limit);actions.addWidget(self.population);layout.addLayout(actions)
        self.heading=label('Priority mux · verified RTL variants','Metric');layout.addWidget(self.heading)
        self.scope=label('Compare three independently proved variants against one original build, using Default throughout.','Muted');self.scope.setWordWrap(True);layout.addWidget(self.scope)
        policy=label('Frontier = better setup WNS / fewer LUTs. Review limits and acceptance are separate. Single trial.','Muted');policy.setWordWrap(True);policy.setToolTip(POLICY);layout.addWidget(policy)
        self.table,self.model=table(('Variant','Setup WNS','LUTs','Tradeoff','Review limits','Acceptance','Hold WNS','FFs','Proof','Build'),(155,95,65,110,150,100,95,60,90,100),5)
        lab.models.append(self.model);self.table.verticalHeader().setDefaultSectionSize(30);self.table.setMinimumHeight(174)
        split=QSplitter(Qt.Orientation.Vertical);split.addWidget(self.table)
        bottom=QSplitter(Qt.Orientation.Horizontal);self.plot=TradeoffPlot();bottom.addWidget(self.plot)
        details=QWidget();column=QVBoxLayout(details);column.setContentsMargins(8,0,0,0)
        self.compare=QPushButton('Inspect selected comparison');self.compare.clicked.connect(self.compare_row);column.addWidget(self.compare)
        self.detail=text_area();column.addWidget(self.detail,1);bottom.addWidget(details);bottom.setSizes([350,480])
        split.addWidget(bottom);split.setSizes([180,280]);layout.addWidget(split,1)
        self.open.clicked.connect(self.browse);self.last.clicked.connect(lambda:self.load(Path(lab.preferences['last_rtl_sweep'])))
        self.population.currentIndexChanged.connect(self.reload);self.limit.editingFinished.connect(self.reload)
        self.table.selectionModel().currentRowChanged.connect(self.selected);self.plot.selected.connect(self.table.selectRow)
    def load(self,path,population=None):
        self.lab.start('rtl_sweep',(Path(path),population or self.population.currentData(),self.limit.value() or None))
    def reload(self):
        if self.review and (self.population.currentData()!=self.review.population or (self.limit.value() or None)!=self.review.max_luts):self.load(self.review.path)
    def browse(self):
        name,_=QFileDialog.getOpenFileName(self,'Open verified priority RTL sweep',filter='RTL sweep (rtl-sweep.json)')
        if name:self.load(Path(name))
    def restore_controls(self):
        if not self.review:return
        self.population.blockSignals(True);self.population.setCurrentIndex(self.population.findData(self.review.population));self.population.blockSignals(False)
        self.limit.setValue(self.review.max_luts or 0)
    def show_review(self,review):
        selected=self.table.currentIndex().row();self.review=review;self.restore_controls()
        self.heading.setText('Priority mux · '+review.manifest.status.capitalize())
        self.scope.setText(('One shared original' if review.baseline else 'No completed original')+' · Default throughout · '+('register paths' if review.population=='register_paths' else 'full standalone example')+'\n'+review.manifest.job_name)
        rows=[]
        for row in review.rows:
            run=row.run
            rows.append((title(row.variant),getattr(run.timing.get('setup'),'worst_slack_ns',None) if run else None,run.metrics.get('area.lut_cells') if run else None,
                         row.frontier,row.review_limits,row.comparison.acceptance if row.comparison else 'not tested',
                         getattr(run.timing.get('hold'),'worst_slack_ns',None) if run else None,run.metrics.get('area.ff') if run else None,row.proof,row.status))
        self.model.populate(rows);self.plot.review=review;self.table.selectRow(max(0,selected));self.plot.update()
        self.lab.preferences.update(last_rtl_sweep=str(review.path.resolve()),rtl_max_luts=review.max_luts or 0)
        self.lab.preferences_changed.emit(dict(self.lab.preferences));self.lab.tabs.setCurrentIndex(self.lab.rtl_index)
        self.lab.status.setText(f'{sum(r.status=="completed" for r in review.rows[1:])} / 3 variants completed · Select a row to inspect its evidence.')
        self.lab.status.setToolTip(str(review.path))
    def selected(self,index,_):
        if self.review and index.isValid():
            row=self.review.rows[index.row()];self.plot.current=index.row();self.plot.update()
            self.detail.setPlainText('\n'.join([title(row.variant)+' · '+row.status+' · proof: '+row.proof,row.frontier+' · '+row.review_limits,
                'Acceptance: '+(row.comparison.acceptance if row.comparison else 'not tested'),row.reason,'',*row.explanations,'',POLICY]))
        self.busy(self.lab.thread is not None)
    def compare_row(self):
        i=self.table.currentIndex().row()
        if self.review and i>0 and self.review.rows[i].comparison:self.lab.start('rtl_pair',(self.review.path,self.review.population,self.review.rows[i].variant))
    def busy(self,value):
        for w in (self.open,self.population,self.limit):w.setEnabled(not value)
        self.last.setEnabled(not value and bool(self.lab.preferences.get('last_rtl_sweep')))
        i=self.table.currentIndex().row();self.compare.setEnabled(not value and self.review is not None and i>0 and self.review.rows[i].comparison is not None)
    def theme(self,colors):self.plot.colors=colors;self.plot.update()
