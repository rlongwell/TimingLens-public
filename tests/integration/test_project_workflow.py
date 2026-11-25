from pathlib import Path
import json
import os
import subprocess
import sys
import time

from timinglens import read_session

FIXTURE=Path(__file__).parents[1]/'fixtures/zybo_dfx_path.json'


def test_cli_report_and_project_files(tmp_path):
    s=read_session(FIXTURE)
    report=tmp_path/'timing.rpt';report.write_text(s.reports['setup-paths.rpt'])
    xdc=tmp_path/'timing.xdc';xdc.write_text('set_false_path -to [get_cells *debug*]\n')
    out=tmp_path/'out'
    process=subprocess.run([sys.executable,'-m','timinglens','inspect','--files',str(report),str(xdc),'--output',str(out)],capture_output=True,text=True,timeout=20)
    assert process.returncode==0,process.stderr
    data=json.loads((out/'diagnostics.json').read_text())
    assert data['detail_coverage']['P00001']['complete']
    assert data['project_plans'][0]['id']=='constraints.audit'
    assert 'Audit the supplied timing exceptions' in process.stdout
    assert 'No supported project-specific' not in (out/'report.html').read_text()


def test_gui_add_files_analyze_and_show_project_plan(tmp_path,monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    monkeypatch.setenv('TIMINGLENS_REPO_ROOT',str(tmp_path))
    from PySide6.QtWidgets import QApplication
    from timinglens.gui.app import MainWindow
    app=QApplication.instance() or QApplication([]);app.setStyle('Fusion')
    xdc=tmp_path/'clocking.xdc';xdc.write_text('set_false_path -to [get_cells *debug*]\n')
    window=MainWindow(app);window.show()
    try:
        window.navigate(5)
        window.project_files.add_files([FIXTURE,xdc,FIXTURE])
        assert window.project_files.files.count()==2
        window.project_files.start.click()
        deadline=time.monotonic()+10
        while window.thread and time.monotonic()<deadline:
            app.processEvents();time.sleep(.005)
        assert window.result and len(window.result.project_plans)==1
        window.navigate(2)
        last=window.issues.tree.topLevelItem(window.issues.tree.topLevelItemCount()-1)
        window.issues.tree.setCurrentItem(last)
        assert 'Match each exception' in window.issues.description.toPlainText()
        assert 'exceptions coverage/ignored' in window.issues.validation.toPlainText()
        assert 'set_false_path' in window.issues.evidence.toPlainText()
        window.issues.details.setCurrentIndex(2)
        window.issues.copy_tcl.click()
        assert 'report_exceptions -coverage' in app.clipboard().text()
        assert not app.clipboard().text().startswith('set_false_path')
        assert not window.issues.open.isEnabled()
        window.navigate(5)
        window.project_files.top.setText('unsaved_top')
        window.toggle_theme()
        assert window.project_files.top.text()=='unsaved_top'
        assert window.project_files.files.count()==2
    finally:
        window.close();app.processEvents()
