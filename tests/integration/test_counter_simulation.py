"""The finite counter oracle must catch a shared bug in both compared variants."""
import shutil
from threading import Event

import pytest

from timinglens.experiments.counters import plan_counter
from timinglens.experiments.process import execute, ProcessFailure


def test_independent_oracle_rejects_identically_broken_variants(tmp_path):
    verilator=shutil.which('verilator')
    if not verilator:pytest.skip('Verilator unavailable')
    plan=plan_counter('counter32')
    broken=plan.baseline.replace(b'remaining >= amount',b'remaining > amount')
    for filename,module in [('before.sv',b'counter_before'),('after.sv',b'counter_after')]:
        (tmp_path/filename).write_bytes(broken.replace(b'module counter(',b'module '+module+b'(',1))
    (tmp_path/'tb.sv').write_bytes(plan.testbench)
    execute([verilator,'--binary','--timing','-Wno-WIDTHEXPAND','-j','2','--top-module','tb','--Mdir','obj',
             'before.sv','after.sv','tb.sv'],tmp_path,tmp_path/'build.log',Event(),120)
    with pytest.raises(ProcessFailure,match='status'):
        execute([tmp_path/'obj/Vtb'],tmp_path,tmp_path/'simulation.log',Event(),10)
    output=(tmp_path/'simulation.log').read_text()
    assert 'sequential mismatch' in output and 'PASS: 10289' not in output
