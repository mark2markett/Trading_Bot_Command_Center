import importlib.util
import json
from pathlib import Path
import sqlite3
from contextlib import closing
from test_holding_maintenance import runtime


def module():
    path=Path(__file__).with_name('DIAGNOSE-FLEET-BLOCKERS.py')
    assert path.exists(),'No current-state fleet diagnostic exists'
    spec=importlib.util.spec_from_file_location('fleet_blockers',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def test_current_sip_failure_is_reported_without_changes(tmp_path,monkeypatch):
    m=module();root=runtime(tmp_path)
    with closing(sqlite3.connect(root/'var/cc.db')) as db:
        db.executescript('CREATE TABLE heartbeats(id INTEGER PRIMARY KEY,bot_id,run,at,ok,detail); CREATE TABLE decisions(id INTEGER PRIMARY KEY,bot_id,at,action,reason);')
        db.execute("INSERT INTO heartbeats VALUES(1,'sip_orb','session','2026-10-19T14:47:00Z',0,?)",(json.dumps({'data_errors':{'scanner':'unavailable'}}),))
        db.execute("INSERT INTO decisions VALUES(1,'sip_orb','2026-10-19T13:40:00Z','SCANNER_UNAVAILABLE','deadline')");db.commit()
    before=(root/'var/cc.db').read_bytes();flag=(root/'var/control/PAUSE_ENTRIES').read_bytes()
    def request(route):
        if route=='health':return {'ok':True,'db':str(root/'var/cc.db')}
        if route=='incidents?limit=20':return {'monitor':{'status':'checking'},'open_count':1,'open':[{'condition':'sip_opening','scope':'sip_orb','state':'checking','evidence':{}}]}
        return {'entries_paused':True} if route=='risk' else {}
    monkeypatch.setattr(m,'request',request)
    result=m.capture(root)
    assert result['ledger_identity']=='MATCH'
    assert result['collection_complete'] is True and result['fleet_entries_paused'] is True
    assert result['sip_heartbeats'][0]['ok']==0
    assert result['sip_decisions'][0]['action']=='SCANNER_UNAVAILABLE'
    assert result['incidents']['open'][0]['condition']=='sip_opening'
    assert (root/'var/cc.db').read_bytes()==before
    assert (root/'var/control/PAUSE_ENTRIES').read_bytes()==flag
