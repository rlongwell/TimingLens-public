"""Opt-in real tool validation: OOC counter builds only, no hardware connection."""
from hashlib import sha256
import json
import shutil

import pytest

from timinglens.experiments import load_run
from timinglens.experiments.counters import plan_counter
from timinglens.experiments.runner import CounterRequest, run_counter
from timinglens.vivado.runner import discover, VivadoError


@pytest.mark.vivado
@pytest.mark.parametrize('example',['counter32','counter64'])
def test_isolated_counter_build_and_lab_records(tmp_path,monkeypatch,example):
    if not shutil.which('verilator'):pytest.skip('Verilator unavailable')
    try:discover()
    except VivadoError:pytest.skip('Vivado unavailable')
    monkeypatch.setenv('TIMINGLENS_REPO_ROOT',str(tmp_path))
    before=plan_counter(example)
    result=run_counter(CounterRequest(example,tmp_path/'experiment'))
    assert plan_counter(example)==before
    job=json.loads((result.directory/'job.json').read_text());assert job['status']=='completed'
    for path in (*result.register_pair,*result.global_pair):
        run=load_run(path)
        assert run.session.stage=='routed' and run.session.part=='xc7z020clg400-1'
        assert run.metrics['route.errors']==0 and run.metrics['route.unrouted']==0
        assert all(check.status=='passed' for check in run.checks)
    a,b=[load_run(path) for path in result.register_pair]
    assert a.context.constraints==b.context.constraints
    assert a.context.sources!=b.context.sources
    assert a.context.sources['design.sv']==sha256(before.baseline).hexdigest()
    assert b.context.sources['design.sv']==sha256(before.candidate).hexdigest()
