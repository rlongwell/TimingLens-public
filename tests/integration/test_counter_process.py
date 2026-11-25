import os
from pathlib import Path
import subprocess
import sys
from threading import Event, Thread
import time

import pytest

from timinglens.experiments.process import execute, ProcessFailure
from timinglens.vivado.runner import Cancelled


def test_process_cancellation_isolated_to_owned_group(tmp_path):
    cancel=Event();ready=Event();errors=[]
    unrelated=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],start_new_session=True)
    child=tmp_path/'child.pid'
    script="import subprocess,sys,time; from pathlib import Path; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); Path('child.pid').write_text(str(p.pid)); print('ready',flush=True); time.sleep(30)"
    def work():
        try:execute([sys.executable,'-c',script],tmp_path,tmp_path/'tool.log',cancel,20,lambda _:ready.set())
        except BaseException as error:errors.append(error)
    thread=Thread(target=work);thread.start()
    try:
        assert ready.wait(5);cancel.set();thread.join(6)
        assert not thread.is_alive() and isinstance(errors[0],Cancelled)
        assert unrelated.poll() is None
        pid=int(child.read_text());stat=Path(f'/proc/{pid}/stat')
        # A reparented zombie has exited; it is no longer a running descendant.
        assert not stat.exists() or stat.read_text().split()[2]=='Z'
    finally:
        cancel.set();thread.join(6);unrelated.terminate();unrelated.wait(timeout=5)


def test_process_timeout_still_works_after_stdout_is_closed(tmp_path):
    start=time.monotonic()
    with pytest.raises(ProcessFailure,match='timed out'):
        execute([sys.executable,'-c','import os,time; os.close(1); os.close(2); time.sleep(30)'],tmp_path,tmp_path/'quiet.log',Event(),.2)
    assert time.monotonic()-start<4


def test_process_failure_records_final_line_and_exit_status(tmp_path):
    with pytest.raises(ProcessFailure,match='status 7'):
        execute([sys.executable,'-c',"import sys; print('failure evidence',end=''); sys.exit(7)"],tmp_path,tmp_path/'failed.log',Event(),2)
    assert (tmp_path/'failed.log').read_text()=='failure evidence'
