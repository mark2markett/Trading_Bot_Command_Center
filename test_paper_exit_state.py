"""Retire one proven stale paper stop; never submit, cancel, fill or flatten."""
import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest

ROOT=Path(__file__).parent


def module():
    path=ROOT/'PAPER-EXIT-STATE.py'
    assert path.is_file(),'Guarded stale-paper-stop repair is not implemented'
    spec=importlib.util.spec_from_file_location('paper_exit_state_repair',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m


def fixture(root):
    for name in ['var/control','var/backups','bots/spy_mr_bot']:(root/name).mkdir(parents=True,exist_ok=True)
    for name in ['OPTIONS_ONLY','spy_mr.pause','gap_go.pause','nr7.pause','sip_orb.pause']:
        (root/'var/control'/name).write_text('{"reason":"preserve"}')
    with sqlite3.connect(root/'var/cc.db') as db:
        db.executescript('''CREATE TABLE bots(id,mode);
CREATE TABLE positions(bot_id,symbol,qty,avg_price,entry_at);
CREATE TABLE orders(id INTEGER PRIMARY KEY,bot_id,symbol,side,qty,type,status,broker_order_id,stop_price,reason,at);
CREATE TABLE fills(id INTEGER PRIMARY KEY,order_id,bot_id,qty);
CREATE TABLE trades(id INTEGER PRIMARY KEY,pnl);
CREATE TABLE controls(id INTEGER PRIMARY KEY,at,actor,action,target,before_json,after_json,note);
CREATE TABLE limits(scope,key,value);
INSERT INTO positions VALUES('spy_mr','SPY',130,769.6,'2026-10-14');
INSERT INTO orders VALUES(21,'spy_mr','SPY','SELL',130,'STOP','sent','paper-stop-SPY',731.12,'','2026-10-15T13:45:00+00:00');
INSERT INTO orders VALUES(29,'spy_mr','SPY','SELL',130,'MOC','sent','paper-1792525802377',NULL,'','2026-10-20T19:50:02+00:00');''')
        db.executemany('INSERT INTO bots VALUES(?,?)',[(name,'paper') for name in ['spy_mr','gap_go','gap_go_spread','nr7','sip_orb']])
    state={'in_position':True,'qty':130,'entry_price':769.6,'entry_date':'2026-10-14','stop_order_id':'paper-stop-SPY',
           'last_decide':'2026-10-20','pending':{'side':'SELL','qty':130,'date':'2026-10-20','reason':'exit_sma','order_id':'paper-1792525802377'}}
    paper={'cash':123.45,'positions':{'SPY':130},'pending':[{'id':'paper-1792525802377','kind':'SELL_MOC','symbol':'SPY','qty':130,'queued':'2026-10-20T19:50:02.377418+00:00'}],'stops':{},'fills':[]}
    folder=root/'bots/spy_mr_bot'
    (folder/'state_paper.json').write_text(json.dumps(state))
    (folder/'paper_ledger.json').write_text(json.dumps(paper))
    return root,root/'var/backups/paper-exit-test.json'


def fetcher(root):
    return lambda route:json.dumps({'ok':True,'db':str(root/'var/cc.db')}).encode()


def snapshot(root):
    result={str(p.relative_to(root)):p.read_bytes() for p in (root/'var/control').iterdir()}
    for name in ['state_paper.json','paper_ledger.json']:
        result[name]=(root/'bots/spy_mr_bot'/name).read_bytes()
    with sqlite3.connect(root/'var/cc.db') as db:
        result['db']={name:db.execute('SELECT * FROM '+name+' ORDER BY rowid').fetchall() for name in ['bots','positions','orders','fills','trades','controls','limits']}
    return result


def test_retires_only_proven_stale_stop_and_clears_its_reference_with_audit(tmp_path):
    m=module();root,receipt=fixture(tmp_path);before=snapshot(root)
    plan=m.prepare(root,receipt,fetcher=fetcher(root))
    assert plan['stop_order_id']==21 and plan['pending_exit_order_id']==29
    assert snapshot(root)==before
    assert m.apply(root,receipt,fetcher=fetcher(root))['ok']
    after=snapshot(root)
    assert after['paper_ledger.json']==before['paper_ledger.json']
    assert json.loads(after['state_paper.json'])=={**json.loads(before['state_paper.json']),'stop_order_id':None}
    for name in ['bots','positions','fills','trades','limits']:assert after['db'][name]==before['db'][name]
    assert after['db']['orders'][1]==before['db']['orders'][1]
    assert after['db']['orders'][0][6]=='cancelled'
    assert len(after['db']['controls'])==1
    assert after['db']['controls'][0][3]=='reconcile_paper_stop_metadata'
    for key,value in before.items():
        if key.startswith('var/control/'):assert after[key]==value
    assert m.verify(root,receipt,fetcher=fetcher(root))['ok']
    assert m.apply(root,receipt,fetcher=fetcher(root))['ok']
    assert snapshot(root)==after


@pytest.mark.parametrize('problem',['actual_stop','wrong_queue_id','wrong_queue_qty','wrong_state_qty','wrong_position','duplicate_stop','filled_exit','live_mode','missing_policy','wrong_api'])
def test_ambiguous_or_changed_execution_evidence_refuses_before_writes(tmp_path,problem):
    m=module();root,receipt=fixture(tmp_path)
    sp=root/'bots/spy_mr_bot/state_paper.json';pp=root/'bots/spy_mr_bot/paper_ledger.json'
    state=json.loads(sp.read_text());paper=json.loads(pp.read_text())
    if problem=='actual_stop':paper['stops']={'SPY':{'qty':130,'stop':731.12}}
    if problem=='wrong_queue_id':paper['pending'][0]['id']='paper-other'
    if problem=='wrong_queue_qty':paper['pending'][0]['qty']=129
    if problem=='wrong_state_qty':state['qty']=129
    sp.write_text(json.dumps(state));pp.write_text(json.dumps(paper))
    with sqlite3.connect(root/'var/cc.db') as db:
        if problem=='wrong_position':db.execute('UPDATE positions SET qty=129')
        if problem=='duplicate_stop':db.execute("INSERT INTO orders SELECT 22,bot_id,symbol,side,qty,type,status,broker_order_id,stop_price,reason,at FROM orders WHERE id=21")
        if problem=='filled_exit':db.execute("INSERT INTO fills VALUES(1,29,'spy_mr',1)")
        if problem=='live_mode':db.execute("UPDATE bots SET mode='live' WHERE id='spy_mr'")
    if problem=='missing_policy':(root/'var/control/OPTIONS_ONLY').unlink()
    before=snapshot(root)
    get=(lambda route:b'{"ok":true,"db":"/wrong/cc.db"}') if problem=='wrong_api' else fetcher(root)
    with pytest.raises((ValueError,OSError)):m.prepare(root,receipt,fetcher=get)
    assert snapshot(root)==before and not receipt.exists()


def test_changed_pending_state_after_prepare_cannot_be_overwritten(tmp_path):
    m=module();root,receipt=fixture(tmp_path);m.prepare(root,receipt,fetcher=fetcher(root))
    sp=root/'bots/spy_mr_bot/state_paper.json'
    state=json.loads(sp.read_text());state['pending']['qty']=129;sp.write_text(json.dumps(state))
    before=snapshot(root)
    with pytest.raises(ValueError):m.apply(root,receipt,fetcher=fetcher(root))
    assert snapshot(root)==before


def test_database_write_failure_restores_state_and_keeps_a_recovery_receipt(tmp_path):
    m=module();root,receipt=fixture(tmp_path);m.prepare(root,receipt,fetcher=fetcher(root))
    with sqlite3.connect(root/'var/cc.db') as db:
        db.execute("CREATE TRIGGER forbidden_audit AFTER INSERT ON controls BEGIN INSERT INTO fills VALUES(99,29,'spy_mr',130); END")
    before=snapshot(root)
    with pytest.raises(sqlite3.DatabaseError):m.apply(root,receipt,fetcher=fetcher(root))
    assert snapshot(root)==before and receipt.is_file()


def test_trigger_mutating_another_order_cannot_commit(tmp_path):
    m=module();root,receipt=fixture(tmp_path);m.prepare(root,receipt,fetcher=fetcher(root))
    with sqlite3.connect(root/'var/cc.db') as db:
        db.execute("CREATE TRIGGER changed_exit AFTER UPDATE OF status ON orders WHEN NEW.id=21 BEGIN UPDATE orders SET status='cancelled' WHERE id=29; END")
    before=snapshot(root)
    with pytest.raises(ValueError):m.apply(root,receipt,fetcher=fetcher(root))
    assert snapshot(root)==before


def test_recovers_crash_after_state_write_before_database_commit(tmp_path):
    import base64
    m=module();root,receipt=fixture(tmp_path);m.prepare(root,receipt,fetcher=fetcher(root))
    saved=json.loads(receipt.read_text())
    (root/'bots/spy_mr_bot/state_paper.json').write_bytes(base64.b64decode(saved['updated_state']))
    assert m.apply(root,receipt,fetcher=fetcher(root))['ok']
    assert m.verify(root,receipt,fetcher=fetcher(root))['ok']


def test_unknown_status_order_cannot_be_ignored_in_preflight(tmp_path):
    m=module();root,receipt=fixture(tmp_path)
    with sqlite3.connect(root/'var/cc.db') as db:
        db.execute("INSERT INTO orders SELECT 30,bot_id,symbol,side,qty,type,'unrecognized','paper-other',stop_price,reason,at FROM orders WHERE id=29")
    before=snapshot(root)
    with pytest.raises(ValueError):m.prepare(root,receipt,fetcher=fetcher(root))
    assert snapshot(root)==before and not receipt.exists()
