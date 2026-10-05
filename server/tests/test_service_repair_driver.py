"""The repair driver must refuse overlapping unfinished evidence stages."""
import importlib.util
import json
from pathlib import Path
import sys
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
spec=importlib.util.spec_from_file_location('service_repair_driver',ROOT/'tools/verify_service_repair_model.py')
driver=importlib.util.module_from_spec(spec);spec.loader.exec_module(driver)


@pytest.mark.parametrize('soak,focus,message',[
    ({'run_id':'world','complete':False,'replay_matches':True},{},'soak must complete'),
    ({'run_id':'world','complete':True,'replay_matches':True},{'run_id':'world','replay_matches':False},'focused follow-on must finish'),
])
def test_unfinished_stage_never_opens_or_creates_save(tmp_path,monkeypatch,soak,focus,message):
    soak_path=tmp_path/'soak.json';focus_path=tmp_path/'focus.json'
    soak_path.write_text(json.dumps(soak));focus_path.write_text(json.dumps(focus))
    database=tmp_path/'must-not-exist.db'
    monkeypatch.setattr(sys,'argv',['driver','--database',str(database),'--run-id','world',
        '--soak-report',str(soak_path),'--focused-report',str(focus_path),'--output',str(tmp_path/'out.json')])
    with pytest.raises(RuntimeError,match=message):driver.main()
    assert not database.exists()
