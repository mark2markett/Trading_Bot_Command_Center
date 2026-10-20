"""Offline safety checks must succeed before recovering an unresponsive server."""
import importlib.util
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
import pytest
from test_options_only_install import setup,financial,STOCKS

ROOT=Path(__file__).parent

def module():
    path=ROOT/'OPERATIONS-REPAIR.py'
    assert path.is_file(),'Operations repair preflight missing'
    spec=importlib.util.spec_from_file_location('operations_repair',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def ready(tmp_path):
    repo,package,payload,_,fetcher,state=setup(tmp_path)
    for bot in STOCKS:
        path=repo/('var/control/'+bot+'.pause')
        if not path.exists():path.write_text('{"reason":"options-only"}')
    (repo/'var/control/OPTIONS_ONLY').write_text('{"actor":"previous audited activation"}')
    def fetch(route):
        if route=='/api/incidents?limit=1':
            return json.dumps({'monitor':{'status':'checking','last_completed_at':datetime.now(timezone.utc).isoformat(),'errors':[]},'open_count':11}).encode()
        return fetcher(route)
    return repo,fetch


def test_offline_preflight_and_runtime_verification_preserve_financial_state(tmp_path):
    m=module();repo,fetch=ready(tmp_path);before=financial(repo)
    result=m.prepare(repo);receipt=Path(result['receipt'])
    assert receipt.is_file() and result['paper_fleet'] is True
    assert m.verify(repo,receipt,fetcher=fetch)['options_only'] is True
    assert financial(repo)==before


def test_missing_restriction_refuses_before_any_recovery(tmp_path):
    m=module();repo,fetch=ready(tmp_path)
    (repo/'var/control/OPTIONS_ONLY').unlink()
    with pytest.raises(ValueError,match='Options-only'):m.prepare(repo)
    assert not list((repo/'var/backups').glob('operations-repair-*'))


def test_old_monitor_tick_cannot_verify_a_repaired_monitor(tmp_path):
    m=module();repo,fetch=ready(tmp_path);receipt=Path(m.prepare(repo)['receipt'])
    def stale(route):
        if route=='/api/incidents?limit=1':return json.dumps({'monitor':{'status':'checking','last_completed_at':(datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat(),'errors':[]},'open_count':11}).encode()
        return fetch(route)
    with pytest.raises(ValueError,match='monitor'):m.verify(repo,receipt,fetcher=stale)


def test_existing_risk_pause_cannot_be_removed_silently(tmp_path):
    m=module();repo,fetch=ready(tmp_path);receipt=Path(m.prepare(repo)['receipt'])
    (repo/'var/control/sip_orb.pause').unlink()
    with pytest.raises(ValueError,match='control'):m.verify(repo,receipt,fetcher=fetch)
