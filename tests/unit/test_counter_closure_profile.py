from hashlib import sha256
import shutil

import pytest

from timinglens.experiments import counters
from timinglens.experiments.counters import plan_counter


def test_closure_profile_keeps_the_original_rtl_fix_and_its_own_frozen_constraints(tmp_path,monkeypatch):
    stress=plan_counter('counter32');closure=plan_counter('counter32_250')
    assert closure.baseline==stress.baseline and closure.candidate==stress.candidate
    assert closure.testbench==stress.testbench
    assert closure.document()['clock_period_ns']==4.
    assert b'-period 4.000' in closure.constraints
    assert b'-period 2.000' in stress.constraints
    assert closure.document()['constraints_sha256']==sha256(closure.constraints).hexdigest()
    # Swapping a valid but different bundled XDC must still fail closed.
    shutil.copytree(counters.example_path()/'counter32_250',tmp_path/'counter32_250')
    (tmp_path/'counter32_250/timing.xdc').write_bytes(stress.constraints)
    monkeypatch.setattr(counters,'example_path',lambda:tmp_path)
    with pytest.raises(ValueError,match='constraints changed'):
        plan_counter('counter32_250')


def test_closure_profile_cli_preview_is_read_only(capsys):
    from timinglens.cli import main
    assert main(['experiment','--example','counter32_250','--preview'])==0
    output=capsys.readouterr().out
    assert 'counter32_250' in output and 'remaining[31:4]' in output
