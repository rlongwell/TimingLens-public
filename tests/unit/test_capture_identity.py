"""Object properties must not replace the design identity in a capture."""
from timinglens.vivado.decode import decode
from timinglens.timing.io import read_session
import pytest


def test_cell_property_name_does_not_overwrite_session_name(tmp_path):
    rows=[('META','actual_design','2024.2','xc7z020clg400-1','actual_top','','','demo'),
          ('CELLPROP','u_dma/generated/long_register_name','DONT_TOUCH','true')]
    (tmp_path/'records.tsv').write_text(''.join(row[0]+'\t'+'\t'.join(v.encode().hex() for v in row[1:])+'\n' for row in rows))
    s=decode(tmp_path,1,1,'route',[],True)
    assert s.name=='actual_design' and s.top=='actual_top'


def test_oversize_session_is_rejected_before_json_decoding(tmp_path):
    path=tmp_path/'large.json'
    with path.open('wb') as stream:
        stream.truncate(64_000_001)
    with pytest.raises(ValueError,match='64 MB'):
        read_session(path)
