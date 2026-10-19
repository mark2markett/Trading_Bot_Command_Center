"""An owner-approved resume must restore pause protection without releasing SIP."""
import importlib.util
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pytest
from test_holding_maintenance import runtime

ROOT=Path(__file__).parent
NOW=datetime(2026,10,19,13,25,tzinfo=timezone.utc)


def module():
    path=ROOT/'FLEET-PAPER-RESUME.py'
    assert path.exists(), 'No guarded fleet paper resume exists'
    spec=importlib.util.spec_from_file_location('fleet_resume',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def fixture(root):
    runtime(root)
    control=root/'var/control'
    (control/'sip_orb.pause').write_text(json.dumps({'actor':'sdk','reason':'4 consecutive losses'}))
    with sqlite3.connect(root/'var/cc.db') as db:
        db.execute('DROP TABLE kv');db.execute('CREATE TABLE kv(key PRIMARY KEY,value_json,updated_at)')
        db.execute('DROP TABLE controls');db.execute('CREATE TABLE controls(id INTEGER PRIMARY KEY,at,actor,action,target,before_json,after_json,note)')
        db.execute("CREATE TABLE paper_marks(symbol,price,at)")
        db.execute("INSERT INTO paper_marks VALUES('SPY',767.0,?)",(NOW.isoformat(),))
        db.execute("CREATE TABLE paper_equity(id INTEGER PRIMARY KEY,at,equity)")
        db.execute("INSERT INTO paper_equity VALUES(1,?,100000)",((NOW-timedelta(days=1)).isoformat(),))
        db.execute("INSERT INTO kv VALUES('paper_account',?,?)",(json.dumps({'initial_capital':100000}),NOW.isoformat()))
        db.execute("INSERT INTO kv VALUES('ladder_fired',?,?)",(json.dumps({'pause':'old','flatten':'retain','kill':'retain'}),NOW.isoformat()))
    return root


def receipt(m,root):
    return {'at':NOW.isoformat(),'repo':str(root.resolve()),'runtime':m.holding.runtime_snapshot(root),
            'readiness':{'blockers':['FLEET_ENTRY_PAUSE'],'read_errors':[]},
            'freshness':{'riskd':NOW.isoformat(),'monitor':NOW.isoformat(),'position':NOW.isoformat(),'marks':[NOW.isoformat()]},
            'risk':{'entries_paused':True,'killed':False,
                    'drawdown':{'source':'paper','dd':0.0087,'equity':99635,'peak':100510},
                    'exposure':{'usd':99731,'ratio':1.001,'cap':1.5},
                    'limits':{'dd_pause_pct':0.06,'dd_flatten_pct':0.08,'dd_kill_pct':0.1,'daily_loss_limit_pct':0.02,'max_gross_exposure':1.5}},
            'day_pct':0.0078}


def test_only_fleet_pause_and_pause_latch_change_and_audit_exists(tmp_path):
    m=module();root=fixture(tmp_path);r=receipt(m,root)
    sip=(root/'var/control/sip_orb.pause').read_bytes()
    with sqlite3.connect(root/'var/cc.db') as db:
        before={t:db.execute('SELECT * FROM '+t).fetchall() for t in ('positions','orders','fills','trades','bots')}
    result=m.apply(root,r,approved=True,now=NOW)
    assert result['resumed'] is True
    assert not (root/'var/control/PAUSE_ENTRIES').exists()
    assert (root/'var/control/sip_orb.pause').read_bytes()==sip
    with sqlite3.connect(root/'var/cc.db') as db:
        assert json.loads(db.execute("SELECT value_json FROM kv WHERE key='ladder_fired'").fetchone()[0])=={'flatten':'retain','kill':'retain'}
        audit=db.execute("SELECT action,target,before_json,after_json FROM controls").fetchone()
        assert audit[:2]==('resume_entries','fleet')
        assert json.loads(audit[2])['paused'] is True and json.loads(audit[3])['paused'] is False
        for t,rows in before.items():assert db.execute('SELECT * FROM '+t).fetchall()==rows
    # A later drawdown can fire pause again; higher-step latches remain unchanged.
    from cc_sdk.ledger import Ledger
    from cc_server import riskd
    from unittest.mock import patch
    import os
    with patch.dict(os.environ,{'CC_VAR':str(root/'var')}), patch.object(riskd,'portfolio_drawdown',return_value={'dd':0.065}), patch.object(riskd,'plim',side_effect=lambda L,k:{'dd_pause_pct':.06,'dd_flatten_pct':.08,'dd_kill_pct':.1}[k]):
        # Fixture has a deliberately reduced schema; exercise latch via the real ladder using a separate SDK database.
        ledger=Ledger(root/'ladder.db')
        riskd.db.kv_set(ledger,'ladder_fired',{'flatten':'retain','kill':'retain'})
        assert riskd.apply_ladder(ledger)==['pause']
        ledger.conn.close()
    assert (root/'var/control/PAUSE_ENTRIES').exists()


@pytest.mark.parametrize('bad',['approval','stale','future','drawdown','exposure','day_loss','nan','monitor','kill','flatten','changed','sip','wrong_pause'])
def test_unsafe_or_unapproved_resume_changes_nothing(tmp_path,bad):
    m=module();root=fixture(tmp_path);r=receipt(m,root);approved=True
    if bad=='approval':approved=False
    if bad=='stale':r['at']=(NOW-timedelta(seconds=91)).isoformat()
    if bad=='future':r['at']=(NOW+timedelta(seconds=1)).isoformat()
    if bad=='drawdown':r['risk']['drawdown']['dd']=.06
    if bad=='exposure':r['risk']['exposure']['ratio']=1.5
    if bad=='day_loss':r['day_pct']=-.02
    if bad=='nan':r['risk']['drawdown']['dd']=float('nan')
    if bad=='monitor':r['readiness']['blockers'].append('INCIDENT_MONITOR_UNAVAILABLE')
    if bad=='kill':(root/'var/control/KILL').write_text('{}')
    if bad=='flatten':(root/'var/control/spy_mr.flatten').write_text('{}')
    if bad=='changed':
        with sqlite3.connect(root/'var/cc.db') as db:db.execute('UPDATE positions SET qty=129')
    if bad=='sip':(root/'var/control/sip_orb.pause').unlink()
    if bad=='wrong_pause':(root/'var/control/PAUSE_ENTRIES').write_text('{"actor":"operator","reason":"manual"}')
    before=(root/'var/cc.db').read_bytes();pause=(root/'var/control/PAUSE_ENTRIES').read_bytes()
    with pytest.raises((ValueError,KeyError)):m.apply(root,r,approved=approved,now=NOW)
    assert (root/'var/cc.db').read_bytes()==before
    assert (root/'var/control/PAUSE_ENTRIES').read_bytes()==pause


def test_unlink_failure_keeps_pause_and_audits_only_intent(tmp_path,monkeypatch):
    m=module();root=fixture(tmp_path);r=receipt(m,root)
    original=Path.unlink
    def fail(path,*args,**kwargs):
        if path.name=='PAUSE_ENTRIES':raise PermissionError('locked')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'unlink',fail)
    with pytest.raises(PermissionError):m.apply(root,r,approved=True,now=NOW)
    assert (root/'var/control/PAUSE_ENTRIES').exists()


def test_fallback_pause_is_exclusive_and_does_not_overwrite_controls(tmp_path):
    m=module();root=fixture(tmp_path);r=receipt(m,root)
    old=(root/'var/control/PAUSE_ENTRIES').read_bytes()
    assert m.block(root,r)['entries_paused'] is True
    assert (root/'var/control/PAUSE_ENTRIES').read_bytes()==old
    (root/'var/control/PAUSE_ENTRIES').unlink()
    assert m.block(root,r)['entries_paused'] is True
    value=json.loads((root/'var/control/PAUSE_ENTRIES').read_text())
    assert value['actor']=='fleet-resume-guard'
    assert (root/'var/control/sip_orb.pause').exists()


def test_unreviewed_per_bot_pause_is_not_silently_overridden(tmp_path):
    m=module();root=fixture(tmp_path);r=receipt(m,root)
    (root/'var/control/nr7.pause').write_text('{"reason":"manual"}')
    with pytest.raises(ValueError):m.apply(root,r,approved=True,now=NOW)
    assert (root/'var/control/PAUSE_ENTRIES').exists()


@pytest.mark.parametrize('key,age',[('riskd',91),('monitor',91),('position',61),('marks',61)])
def test_individual_observations_expire_before_release(tmp_path,key,age):
    m=module();root=fixture(tmp_path);r=receipt(m,root)
    stamp=(NOW-timedelta(seconds=age)).isoformat()
    r['freshness'][key]=[stamp] if key=='marks' else stamp
    with pytest.raises(ValueError,match='Stale'):m.apply(root,r,approved=True,now=NOW)
    assert (root/'var/control/PAUSE_ENTRIES').exists()


def test_new_marks_cannot_release_pause_after_risk_crossed_limit(tmp_path):
    m=module();root=fixture(tmp_path);r=receipt(m,root)
    with sqlite3.connect(root/'var/cc.db') as db:
        db.execute("UPDATE paper_marks SET price=700")
    with pytest.raises(ValueError,match='breaches a limit'):m.apply(root,r,approved=True,now=NOW)
    assert (root/'var/control/PAUSE_ENTRIES').exists()
    with sqlite3.connect(root/'var/cc.db') as db:assert db.execute('SELECT COUNT(*) FROM controls').fetchone()[0]==0


def test_new_equity_peak_cannot_bypass_drawdown_guard(tmp_path):
    m=module();root=fixture(tmp_path);r=receipt(m,root)
    with sqlite3.connect(root/'var/cc.db') as db:db.execute('INSERT INTO paper_equity VALUES(2,?,110000)',(NOW.isoformat(),))
    with pytest.raises(ValueError,match='breaches a limit'):m.apply(root,r,approved=True,now=NOW)
    assert (root/'var/control/PAUSE_ENTRIES').exists()


def test_real_native_api_readiness_risk_and_release_integration(tmp_path,monkeypatch):
    """Use real native valuation, API, observer and reviewed source; fake only monitor transport."""
    import subprocess
    import io
    import os
    from contextlib import contextmanager
    from cc_sdk.ledger import Ledger
    from cc_sdk import paper_account
    from cc_server import api,db as native_db,position_monitor
    from cc_server.main import app
    from fastapi.testclient import TestClient
    m=module();root=tmp_path/'native'
    subprocess.run(['git','clone','--quiet',str(ROOT/'holding-maintenance.bundle'),str(root)],check=True)
    manifest=json.loads((ROOT/'HOLDING-MAINTENANCE-SOURCE.json').read_text())
    subprocess.run(['git','-C',str(root),'checkout','--quiet',manifest['tip']],check=True)
    monkeypatch.setenv('CC_VAR',str(root/'var'))
    (root/'var/control').mkdir(parents=True)
    L=Ledger(root/'var/cc.db')
    try:
        for bot in m.holding.BOTS:
            L.x('INSERT INTO bots(id,name,mode,instrument) VALUES(?,?,?,?)',(bot,bot,'paper','SPY'))
        paper_account.configure(L,100000)
        L.set_position('spy_mr','SPY',130,769.6,'2026-10-14',2)
        L.order('spy_mr',side='SELL',qty=130,type_='STOP',symbol='SPY',status='sent',stop_price=731.12,broker_order_id='paper-stop-SPY',reason='fixture',risk_result={})
        paper_account.mark(L,'SPY',767,datetime.now(timezone.utc))
        folder=root/'bots/spy_mr_bot'
        (folder/'state_paper.json').write_text(json.dumps({'in_position':True,'qty':130,'pending':None,'stop_order_id':'paper-stop-SPY'}))
        (folder/'paper_ledger.json').write_text(json.dumps({'positions':{'SPY':130},'pending':[],'stops':{'SPY':{'qty':130,'stop':731.12}}}))
        (root/'var/control/PAUSE_ENTRIES').write_text('{"actor":"riskd","reason":"portfolio dd 6.9%"}')
        (root/'var/control/sip_orb.pause').write_text('{"actor":"sdk","reason":"4 consecutive losses"}')
        native_db.kv_set(L,'riskd_last',{'at':datetime.now(timezone.utc).isoformat(),'paper_account':paper_account.snapshot(L)})
        native_db.kv_set(L,'ladder_fired',{'pause':'old'})
        position_monitor.tick(L)
        monkeypatch.setattr(api,'_L',L)
        client=TestClient(app)
        @contextmanager
        def transport(request,timeout):
            url=request.full_url if hasattr(request,'full_url') else request
            route=url.split('8585')[1]
            if route.startswith('/api/incidents'):
                payload={'monitor':{'status':'checking','last_completed_at':datetime.now(timezone.utc).isoformat()}}
            else:
                response=client.get(route);assert response.status_code==200;payload=response.json()
            response=io.BytesIO(json.dumps(payload).encode());response.status=200
            yield response
        monkeypatch.setattr(m.urllib.request,'urlopen',transport)
        r=m.check(root)
        assert r['readiness']['blockers']==['FLEET_ENTRY_PAUSE']
        assert m.apply(root,r,approved=True)['resumed'] is True
        assert m.verify(root,r)['verified']=='FLEET_PAPER_RESUMED_SIP_PAUSED'
        assert client.get('/api/risk').json()['entries_paused'] is False
        assert json.loads((root/'var/control/sip_orb.pause').read_text())['reason']=='4 consecutive losses'
    finally:L.conn.close()
