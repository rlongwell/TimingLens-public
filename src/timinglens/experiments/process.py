"""Cancellable process-group execution for local experiment tools on Linux."""
import codecs
import os
from pathlib import Path
from selectors import DefaultSelector, EVENT_READ
import signal
import subprocess
from time import monotonic

from ..vivado.runner import Cancelled


class ProcessFailure(RuntimeError):
    pass


def execute(command, cwd: Path, logfile: Path, cancel, timeout, log=lambda _:None):
    if cancel.is_set():raise Cancelled('Cancelled before launching a tool.')
    started=monotonic()
    process=subprocess.Popen([str(c) for c in command],cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                             start_new_session=True,stdin=subprocess.DEVNULL)
    def kill(sig):
        try:os.killpg(process.pid,sig)
        except ProcessLookupError:pass
    stop=None;expired=False;exited=None;pending='';decoder=codecs.getincrementaldecoder('utf-8')(errors='replace')
    try:
        with process.stdout as pipe, logfile.open('w',encoding='utf-8',buffering=1) as stream, DefaultSelector() as selector:
            os.set_blocking(pipe.fileno(),False);selector.register(pipe,EVENT_READ)
            while True:
                now=monotonic();expired=expired or now-started>=timeout
                if (expired or cancel.is_set()) and stop is None:stop=now;kill(signal.SIGTERM)
                if stop is not None and now-stop>=2:kill(signal.SIGKILL);break
                if process.poll() is not None and exited is None:exited=now
                if not selector.select(.1):
                    if exited is not None and now-exited>1:break
                    continue
                chunk=os.read(pipe.fileno(),65536)
                if not chunk:break
                text=decoder.decode(chunk);stream.write(text)
                lines=(pending+text).split('\n');pending=lines.pop()
                for line in lines:log(line.rstrip('\r'))
                if len(pending)>16384:log(pending[:16384]);pending=''
            tail=decoder.decode(b'',final=True);stream.write(tail)
            if pending or tail:log((pending+tail)[:16384])
        # A descendant may close stdout while its parent keeps running.
        while process.poll() is None:
            expired=expired or monotonic()-started>=timeout
            if cancel.is_set() or expired:kill(signal.SIGTERM);break
            try:process.wait(timeout=.1)
            except subprocess.TimeoutExpired:pass
        try:status=process.wait(timeout=2)
        except subprocess.TimeoutExpired:kill(signal.SIGKILL);status=process.wait(timeout=10)
    finally:
        # Only this tool's new process group; never an existing user's process.
        kill(signal.SIGKILL)
        if process.poll() is None:process.wait(timeout=10)
    if cancel.is_set():raise Cancelled(f'Cancelled; retained {logfile}')
    if expired:raise ProcessFailure(f'Tool timed out after {timeout:g}s; retained {logfile}')
    if status:raise ProcessFailure(f'Tool exited with status {status}; retained {logfile}')
    return {'command':[str(c) for c in command],'returncode':status,'seconds':round(monotonic()-started,3),'log':str(logfile.relative_to(cwd))}
