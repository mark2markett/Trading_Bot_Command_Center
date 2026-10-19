"""Holding-safe maintenance must never loosen the full accounting installer."""
import importlib.util
import json
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest
ROOT=Path(__file__).parent
NOW=datetime(2026,10,18,22,tzinfo=ZoneInfo("America/New_York"))


def module():
    path=ROOT/"HOLDING-MAINTENANCE.py"
    assert path.exists(), "No position-preserving maintenance gate exists"
    spec=importlib.util.spec_from_file_location("holding_maintenance",path)
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def runtime(root):
    (root/"var/control").mkdir(parents=True,exist_ok=True)
    (root/"var/control/PAUSE_ENTRIES").write_text('{"actor":"riskd","reason":"portfolio dd 6.9%"}')
    folder=root/"bots/spy_mr_bot"; folder.mkdir(parents=True,exist_ok=True)
    (folder/"state_paper.json").write_text(json.dumps({"in_position":True,"qty":130,"pending":None,"stop_order_id":"paper-stop-SPY"}))
    (folder/"paper_ledger.json").write_text(json.dumps({"positions":{"SPY":130},"pending":[],"stops":{"SPY":{"qty":130,"stop":731.12}},"cash":-47.93}))
    with sqlite3.connect(root/"var/cc.db") as db:
        db.executescript("CREATE TABLE bots(id,mode); CREATE TABLE positions(bot_id,symbol,qty,avg_price); CREATE TABLE orders(id,bot_id,symbol,side,qty,type,status,stop_price,broker_order_id); CREATE TABLE fills(id,price); CREATE TABLE trades(id,pnl); CREATE TABLE controls(id,action); CREATE TABLE kv(key,value);")
        db.executemany("INSERT INTO bots VALUES(?,?)",[(b,"paper") for b in ("spy_mr","sip_orb","gap_go","gap_go_spread","nr7")])
        db.execute("INSERT INTO positions VALUES('spy_mr','SPY',130,769.60)")
        db.execute("INSERT INTO orders VALUES(21,'spy_mr','SPY','SELL',130,'STOP','sent',731.12,'paper-stop-SPY')")
    return root


def test_matching_paper_holding_and_stop_are_preserved_read_only(tmp_path):
    m=module(); root=runtime(tmp_path)
    before=(root/"var/cc.db").read_bytes()
    result=m.runtime_snapshot(root)
    assert result['holding']=={'bot_id':'spy_mr','symbol':'SPY','qty':130}
    assert len(result['fingerprint'])==64
    assert (root/"var/cc.db").read_bytes()==before
    with sqlite3.connect(root/"var/cc.db") as db: db.execute("INSERT INTO kv VALUES('riskd_last','moving')")
    assert m.runtime_snapshot(root)['fingerprint']==result['fingerprint']


@pytest.mark.parametrize('change', ['live','other_position','pending','stop_mismatch','missing_pause','state_mismatch'])
def test_financial_ambiguity_is_refused(tmp_path,change):
    m=module(); root=runtime(tmp_path)
    with sqlite3.connect(root/"var/cc.db") as db:
        if change=='live': db.execute("UPDATE bots SET mode='live' WHERE id='spy_mr'")
        if change=='other_position': db.execute("INSERT INTO positions VALUES('nr7','IWM',2,100)")
        if change=='pending': db.execute("INSERT INTO orders VALUES(22,'spy_mr','SPY','BUY',1,'MOC','sent',NULL,'paper-22')")
        if change=='stop_mismatch': db.execute("UPDATE orders SET qty=129")
    if change=='missing_pause': (root/'var/control/PAUSE_ENTRIES').unlink()
    if change=='state_mismatch': (root/'bots/spy_mr_bot/state_paper.json').write_text('{"in_position":true,"qty":129}')
    with pytest.raises(ValueError): m.runtime_snapshot(root)


def test_changed_financial_records_or_controls_change_fingerprint(tmp_path):
    m=module(); root=runtime(tmp_path); first=m.runtime_snapshot(root)['fingerprint']
    with sqlite3.connect(root/'var/cc.db') as db: db.execute("INSERT INTO fills VALUES(1,769.61)")
    second=m.runtime_snapshot(root)['fingerprint']; assert second!=first
    (root/'var/control/PAUSE_ENTRIES').write_text('{"reason":"changed"}')
    assert m.runtime_snapshot(root)['fingerprint']!=second


def test_market_hours_refused_and_full_installer_remains_flat_only():
    m=module()
    with pytest.raises(ValueError,match='09:20'): m.maintenance_time(NOW.replace(hour=10))
    m.maintenance_time(NOW)
    assert 'Open positions remain' in (ROOT/'NATIVE-OCT14-PREFLIGHT.py').read_text()


def test_release_changes_no_daily_bot_accounting_feed_or_financial_schema():
    m=module(); manifest=json.loads((ROOT/'HOLDING-MAINTENANCE-SOURCE.json').read_text())
    forbidden=('bots/','cc_sdk/cc_sdk/paper_account.py','cc_sdk/cc_sdk/ledger.py','cc_sdk/cc_sdk/schema.sql','cc_sdk/cc_sdk/schwab_feed.py')
    assert not any(name.startswith(forbidden) for name in manifest['stages']['installed'])


def test_old_equity_history_cannot_be_rewritten_but_new_marks_can_append(tmp_path):
    m=module();root=runtime(tmp_path)
    with sqlite3.connect(root/'var/cc.db') as db:
        db.executescript("CREATE TABLE paper_equity(id INTEGER PRIMARY KEY,at,equity);INSERT INTO paper_equity VALUES(1,'old',100000);")
    before=m.runtime_snapshot(root)
    with sqlite3.connect(root/'var/cc.db') as db: db.execute("INSERT INTO paper_equity VALUES(2,'new',99000)")
    assert m.history_preserved(root,before['history'])
    with sqlite3.connect(root/'var/cc.db') as db: db.execute("UPDATE paper_equity SET equity=1 WHERE id=1")
    with pytest.raises(ValueError,match='history'): m.history_preserved(root,before['history'])


def test_actual_bundle_install_rollback_and_owner_files_with_holding(tmp_path,monkeypatch):
    monkeypatch.delenv('CC_VAR',raising=False)
    m=module(); manifest=json.loads((ROOT/'HOLDING-MAINTENANCE-SOURCE.json').read_text())
    root=tmp_path/'native'
    def git(*args):
        return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.PIPE).decode().strip()
    subprocess.run(['git','clone','--no-checkout',str(ROOT/'holding-maintenance.bundle'),str(root)],check=True,capture_output=True)
    git('config','user.name','Maintenance rehearsal');git('config','user.email','review@example.invalid')
    git('config','core.autocrlf','true');git('checkout','-b','feat/options-m7',manifest['base'])
    runtime(root)
    owner=root/'scripts/dev.sh';owner.write_bytes(b'owner changes must survive\n')
    before=m.check(root,NOW)
    assert before['source']=='before'
    git('cherry-pick',manifest['tip'])
    after=m.check(root,NOW)
    assert after['source']=='installed' and after['fingerprint']==before['fingerprint']
    m.history_preserved(root,before['history'])
    assert owner.read_bytes()==b'owner changes must survive\n'
    git('revert','--no-edit','HEAD')
    assert m.check(root,NOW)['source']=='before'
    assert m.check(root,NOW)['fingerprint']==before['fingerprint']
    assert owner.read_bytes()==b'owner changes must survive\n'
    incompatible=root/'cc_sdk/cc_sdk/schema.sql'
    incompatible.write_bytes(incompatible.read_bytes()+b'\n-- local schema change\n')
    with pytest.raises(ValueError,match='SDK/schema'):m.check(root,NOW)


def test_exact_activity_overlay_remains_compatible_without_accepting_other_edits(tmp_path):
    import zipfile
    m=module();manifest=json.loads((ROOT/'HOLDING-MAINTENANCE-SOURCE.json').read_text())
    root=tmp_path/'native'
    subprocess.run(['git','clone',str(ROOT/'holding-maintenance.bundle'),str(root)],check=True,capture_output=True)
    subprocess.run(['git','checkout',manifest['tip']],cwd=root,check=True,capture_output=True)
    with zipfile.ZipFile(ROOT/'activity-dashboard.zip') as z:
        for name in manifest['activity_overlay']:(root/name).write_bytes(z.read(name))
    assert m.source_stage(root,manifest)=='installed'
    api=root/'cc_server/cc_server/api.py'
    api.write_bytes(api.read_bytes()+b'\n# unreviewed edit\n')
    with pytest.raises(ValueError):m.source_stage(root,manifest)
