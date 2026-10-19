import importlib.util
from datetime import datetime,timezone
from pathlib import Path


def module():
    path=Path(__file__).with_name('CHECK-OPEN-READINESS.py')
    assert path.exists(),'No combined opening readiness report exists'
    spec=importlib.util.spec_from_file_location('open_readiness',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def test_healthy_server_does_not_mask_pauses_missing_quotes_or_missing_monitor():
    m=module();now=datetime(2026,10,19,13,15,tzinfo=timezone.utc)
    result=m.assess({'ok':True,'riskd_last':{'at':now.isoformat()}},
                    {'entries_paused':True,'killed':False,'paper_fleet':True,'bot_count':5,'bot_ids':list(m.BOTS),'paper_account':{'ready':False,'reason':'Stale SPY'}},
                    {},{},now)
    assert result['verdict']=='NOT_READY_FOR_NEW_ENTRIES'
    assert {'FLEET_ENTRY_PAUSE','VALUATION_UNAVAILABLE','INCIDENT_MONITOR_UNAVAILABLE','POSITION_MONITOR_UNAVAILABLE'}<=set(result['blockers'])


def test_recent_checks_without_current_quotes_never_certify_position_safety():
    m=module();now=datetime(2026,10,19,13,32,tzinfo=timezone.utc)
    result=m.assess({'ok':True,'riskd_last':{'at':now.isoformat()}},
                    {'entries_paused':False,'killed':False,'paper_fleet':True,'bot_count':5,'bot_ids':list(m.BOTS),'paper_account':{'ready':False}},
                    {'monitor':{'status':'checking','last_completed_at':now.isoformat()}},
                    {'spy_mr':{'checked_at':now.isoformat(),'issues':[],'positions':[{'quote_status':'market_closed','mark_at':now.isoformat()}]}},now)
    assert 'VALUATION_UNAVAILABLE' in result['blockers']
    assert 'OPEN_POSITION_QUOTE_UNVERIFIED' in result['blockers']
    assert result['scanner']=='Current-session publication and native selection still require verification before 09:40 ET'


def test_failed_health_request_reports_transport_error_not_wrong_ledger(tmp_path,monkeypatch):
    import io
    from contextlib import contextmanager
    import pytest
    m=module()
    @contextmanager
    def transport(request,timeout):
        if request.full_url.endswith('/health'):raise TimeoutError('busy')
        r=io.BytesIO(b'{}');r.status=200;yield r
    monkeypatch.setattr(m.urllib.request,'urlopen',transport)
    with pytest.raises(ValueError,match='health:TimeoutError'):
        m.capture(tmp_path)


def test_ledger_identity_uses_existing_file_identity(tmp_path):
    import os
    import pytest
    m=module();database=tmp_path/'cc.db';database.write_bytes(b'ledger')
    alias=tmp_path/'alias.db';os.link(database,alias)
    m.verify_ledger_identity({'db':str(database)},database)
    with pytest.raises(ValueError,match='does not match'):
        m.verify_ledger_identity({'db':str(alias)},database)
    other=tmp_path/'other.db';other.write_bytes(b'other')
    with pytest.raises(ValueError,match='does not match'):
        m.verify_ledger_identity({'db':str(other)},database)
    with pytest.raises(ValueError,match='missing'):
        m.verify_ledger_identity({},database)
    with pytest.raises(ValueError):
        m.verify_ledger_identity({'db':str(tmp_path/'absent.db')},database)


def test_canonical_database_link_uses_the_same_wal_location(tmp_path):
    import pytest
    m=module();database=tmp_path/'cc.db';database.write_bytes(b'ledger')
    link=tmp_path/'link.db'
    try:link.symlink_to(database)
    except OSError:pytest.skip('Symbolic links are unavailable for this account')
    m.verify_ledger_identity({'db':str(link)},database)


def test_one_transient_health_timeout_is_retried_without_weakening_readiness(tmp_path,monkeypatch):
    import io
    import json
    import sqlite3
    from contextlib import contextmanager,closing
    m=module();(tmp_path/'var').mkdir();database=tmp_path/'var/cc.db'
    with closing(sqlite3.connect(database)) as db:
        db.execute('CREATE TABLE kv(key,value_json)');db.commit()
    calls=[]
    @contextmanager
    def transport(request,timeout):
        route=request.full_url.rsplit('/',1)[-1]
        calls.append(route)
        if calls==['health']:raise TimeoutError('transient')
        payload={'ok':True,'db':str(database),'riskd_last':{}} if route=='health' else {}
        r=io.BytesIO(json.dumps(payload).encode());r.status=200;yield r
    monkeypatch.setattr(m.urllib.request,'urlopen',transport)
    result=m.capture(tmp_path)
    assert calls.count('health')==2
    assert not result['read_errors']
    assert result['verdict']=='NOT_READY_FOR_NEW_ENTRIES'
    assert 'SERVER_OR_RISK_MONITOR_UNAVAILABLE' in result['blockers']
