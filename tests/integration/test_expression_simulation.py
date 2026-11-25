"""Execute generated HDL against SystemVerilog's own comparison semantics."""
from pathlib import Path
import shutil
import subprocess

import pytest

from timinglens.analysis.rtl_fixes import factored
from timinglens.rtl.semantics import SemanticIndex
from timinglens.rtl.syntax import build_index
from timinglens.timing.models import Source


def test_exhaustive_binary_comparison_expressions(tmp_path):
    if not shutil.which('verilator'):
        pytest.skip('Verilator unavailable')
    assertions=[]
    for op in ('>','>=','<','<=','==','!='):
        text=f'''module m(input bit clk, input bit [3:0] amount);
bit [15:0] remaining;
always_ff @(posedge clk) if(remaining {op} amount) remaining <= remaining - 1;
endmodule
'''
        index=build_index([Source(path='m.sv',text=text)])
        reg,reason=SemanticIndex(index,'m').resolve(index.modules['m'][0],None,'remaining')
        assert reg and not reason
        proposal=factored(reg.enable_decisions[0].comparisons[0])
        assertions.append(f'if ((remaining {op} amount) !== {proposal}) $fatal(1,"comparison {op} failed");')
    tb='''module tb;
bit [15:0] remaining;
bit [3:0] amount;
initial begin
  for(int w=0; w<65536; w++) begin
    for(int n=0; n<16; n++) begin
      remaining=16'(w); amount=4'(n);
'''+ '\n'.join(assertions)+'''
    end
  end
  $display("PASS: 6291456 exhaustive binary expression comparisons");
  $finish;
end
endmodule
'''
    (tmp_path/'tb.sv').write_text(tb)
    # Implicit unsigned extension is exactly the behavior under test.
    build=subprocess.run(['verilator','--binary','--timing','-Wno-WIDTHEXPAND','-j','2','--top-module','tb','--Mdir','obj','tb.sv'],
                         cwd=tmp_path,capture_output=True,text=True,timeout=120)
    assert build.returncode==0,build.stdout+build.stderr
    run=subprocess.run([str(tmp_path/'obj/Vtb')],cwd=tmp_path,capture_output=True,text=True,timeout=30)
    assert run.returncode==0 and '6291456' in run.stdout,run.stdout+run.stderr
