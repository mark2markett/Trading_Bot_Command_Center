"""A completed paper round trip permits only retiring its orphaned stop metadata."""
import json
import sqlite3

import pytest
from test_paper_exit_state import module,fixture,fetcher,snapshot


def closed_fixture(tmp_path):
    repo,receipt=fixture(tmp_path)
    sp=repo/'bots/spy_mr_bot/state_paper.json';pp=repo/'bots/spy_mr_bot/paper_ledger.json'
    state=json.loads(sp.read_text());state.update(in_position=False,qty=0,pending=None,stop_order_id=None,entry_price=None,entry_date=None,last_reconcile='2026-10-21T09:46:53.536709-04:00')
    paper=json.loads(pp.read_text());sale=paper['pending'][0];paper.update(positions={'SPY':0},pending=[],fills=[{**sale,'fill':769.04,'date':'2026-10-20'}])
    sp.write_text(json.dumps(state));pp.write_text(json.dumps(paper))
    with sqlite3.connect(repo/'var/cc.db') as db:
        db.executescript("""DELETE FROM positions;
UPDATE orders SET status='filled' WHERE id=29;
INSERT INTO orders VALUES(11,'spy_mr','SPY','BUY',130,'MOC','filled','paper-entry-SPY',NULL,'','2026-10-14T19:50:00+00:00');
ALTER TABLE fills ADD COLUMN price;
ALTER TABLE fills ADD COLUMN commission;
INSERT INTO fills VALUES(19,11,'spy_mr',130,769.6,0);
INSERT INTO fills VALUES(24,29,'spy_mr',130,769.05,0);
ALTER TABLE trades ADD COLUMN bot_id;
ALTER TABLE trades ADD COLUMN qty;
ALTER TABLE trades ADD COLUMN entry_px;
ALTER TABLE trades ADD COLUMN exit_px;
ALTER TABLE trades ADD COLUMN entry_at;
ALTER TABLE trades ADD COLUMN exit_at;
INSERT INTO trades VALUES(11,-71.50000000000887,'spy_mr',130,769.6,769.05,'2026-10-14','2026-10-20');""")
    return repo,receipt


def test_closed_trade_cleanup_changes_only_orphan_order_and_audits_without_touching_state(tmp_path):
    m=module();repo,receipt=closed_fixture(tmp_path);before=snapshot(repo)
    plan=m.prepare(repo,receipt,fetcher=fetcher(repo),closed=True)
    assert snapshot(repo)==before
    assert plan['closed_trade']['pnl']==pytest.approx(-71.5)
    assert plan['closed_trade']['paper_exit_price']==769.04
    assert m.apply(repo,receipt,fetcher=fetcher(repo))['ok']
    after=snapshot(repo)
    assert after['state_paper.json']==before['state_paper.json']
    assert after['paper_ledger.json']==before['paper_ledger.json']
    for name in ['bots','positions','fills','trades','limits']:assert after['db'][name]==before['db'][name]
    assert len(after['db']['controls'])==1
    orders={r[0]:r for r in after['db']['orders']}
    old={r[0]:r for r in before['db']['orders']}
    assert orders[11]==old[11] and orders[29]==old[29]
    assert orders[21][6]=='cancelled' and 'closed paper' in orders[21][9].lower()
    assert m.verify(repo,receipt,fetcher=fetcher(repo))['position']=='flat'
    assert m.apply(repo,receipt,fetcher=fetcher(repo))['already_applied']
    assert snapshot(repo)==after


@pytest.mark.parametrize('problem',['native_holding','paper_holding','pending','actual_stop','stop_fill','missing_exit_fill','partial_exit','missing_trade','wrong_pnl','wrong_entry_date','wrong_exit_order_date','wrong_paper_id','duplicate_stop','live'])
def test_closed_cleanup_rejects_incomplete_or_conflicting_proof_before_writes(tmp_path,problem):
    m=module();repo,receipt=closed_fixture(tmp_path)
    pp=repo/'bots/spy_mr_bot/paper_ledger.json';paper=json.loads(pp.read_text())
    if problem=='paper_holding':paper['positions']['SPY']=1
    if problem=='pending':paper['pending']=[{'symbol':'SPY','kind':'SELL_MOC','qty':130}]
    if problem=='actual_stop':paper['stops']['SPY']={'qty':130,'stop':731.12}
    if problem=='wrong_paper_id':paper['fills'][0]['id']='paper-other'
    pp.write_text(json.dumps(paper))
    with sqlite3.connect(repo/'var/cc.db') as db:
        if problem=='native_holding':db.execute("INSERT INTO positions VALUES('spy_mr','SPY',1,769.6,'2026-10-14')")
        if problem=='stop_fill':db.execute("INSERT INTO fills VALUES(25,21,'spy_mr',1,731.12,0)")
        if problem=='missing_exit_fill':db.execute('DELETE FROM fills WHERE id=24')
        if problem=='partial_exit':db.execute('UPDATE fills SET qty=129 WHERE id=24')
        if problem=='missing_trade':db.execute('DELETE FROM trades')
        if problem=='wrong_pnl':db.execute('UPDATE trades SET pnl=100')
        if problem=='wrong_entry_date':db.execute("UPDATE trades SET entry_at='2026-10-13'")
        if problem=='wrong_exit_order_date':db.execute("UPDATE orders SET at='2026-10-19T19:50:00+00:00' WHERE id=29")
        if problem=='duplicate_stop':db.execute("INSERT INTO orders SELECT 22,bot_id,symbol,side,qty,type,status,broker_order_id,stop_price,reason,at FROM orders WHERE id=21")
        if problem=='live':db.execute("UPDATE bots SET mode='live' WHERE id='spy_mr'")
    before=snapshot(repo)
    with pytest.raises(ValueError):m.prepare(repo,receipt,fetcher=fetcher(repo),closed=True)
    assert snapshot(repo)==before and not receipt.exists()


def test_closed_cleanup_failure_rolls_back_without_rewriting_either_paper_file(tmp_path):
    m=module();repo,receipt=closed_fixture(tmp_path);m.prepare(repo,receipt,fetcher=fetcher(repo),closed=True)
    with sqlite3.connect(repo/'var/cc.db') as db:
        db.execute("CREATE TRIGGER changed_trade AFTER UPDATE OF status ON orders BEGIN UPDATE trades SET pnl=100; END")
    before=snapshot(repo)
    with pytest.raises(sqlite3.DatabaseError):m.apply(repo,receipt,fetcher=fetcher(repo))
    assert snapshot(repo)==before
