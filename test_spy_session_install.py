"""SPY-only source installation must not alter running intraday code or paper state."""
import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest

ROOT=Path(__file__).parent


def module():
    p=ROOT/'SPY-SESSION-INSTALL.py'
    assert p.is_file(),'SPY-only installer is missing'
    spec=importlib.util.spec_from_file_location('spy_session_install_test',p)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m


def setup(tmp_path):
    from test_paper_exit_state import fixture,fetcher
    repo,_=fixture(tmp_path)
    manifest=json.loads((ROOT/'ACTIVITY-DASHBOARD.json').read_text())
    import subprocess
    source=tmp_path/'fixture-source'
    subprocess.run(['git','clone','--quiet',str(ROOT/'activity-dashboard-source.bundle'),str(source)],check=True,capture_output=True)
    original=subprocess.run(['git','show',manifest['compatible_base']+':bots/spy_mr_bot/bot.py'],cwd=source,check=True,capture_output=True).stdout
    with sqlite3.connect(repo/'var/cc.db') as db:db.execute('ALTER TABLE trades ADD COLUMN bot_id')
    target=repo/'bots/spy_mr_bot/bot.py';target.write_bytes(original.replace(b'\n',b'\r\n'))
    shared=repo/'cc_sdk/cc_sdk/ledger.py';shared.parent.mkdir(parents=True);shared.write_text('RUNNING SDK: do not touch')
    return repo,fetcher(repo)


def protected(repo):
    from test_paper_exit_state import snapshot
    return snapshot(repo)


def test_only_spy_source_is_replaced_and_repeat_is_idempotent(tmp_path):
    m=module();repo,fetch=setup(tmp_path);before=protected(repo)
    shared=(repo/'cc_sdk/cc_sdk/ledger.py').read_bytes()
    plan=m.prepare(repo,ROOT,fetcher=fetch)
    assert protected(repo)==before
    result=m.apply(repo,ROOT,plan['receipt'],fetcher=fetch)
    assert result['ok'] and result['financial_writes']==0 and result['server_restarted'] is False
    assert result['spy_status']['qty']==130 and result['spy_status']['pending']['date']=='2026-10-20'
    assert protected(repo)==before and (repo/'cc_sdk/cc_sdk/ledger.py').read_bytes()==shared
    assert m.verify(repo,ROOT,plan['receipt'],fetcher=fetch)['ok']
    assert m.apply(repo,ROOT,plan['receipt'],fetcher=fetch)['already_installed']


@pytest.mark.parametrize('problem',['source_changed','paper_changed','live','policy_missing','wrong_api'])
def test_changed_or_unsafe_evidence_refuses_source_replacement(tmp_path,problem):
    m=module();repo,fetch=setup(tmp_path)
    if problem=='wrong_api':
        def fetch(route):return b'{"ok":true,"db":"/wrong/cc.db"}'
    if problem=='live':
        with sqlite3.connect(repo/'var/cc.db') as db:db.execute("UPDATE bots SET mode='live'")
    if problem=='policy_missing':(repo/'var/control/OPTIONS_ONLY').unlink()
    if problem in {'live','policy_missing','wrong_api'}:
        with pytest.raises(ValueError):m.prepare(repo,ROOT,fetcher=fetch)
        return
    plan=m.prepare(repo,ROOT,fetcher=fetch)
    if problem=='source_changed':(repo/'bots/spy_mr_bot/bot.py').write_text('owner source edit')
    else:(repo/'bots/spy_mr_bot/state_paper.json').write_text('{"changed":true}')
    before=(repo/'bots/spy_mr_bot/bot.py').read_bytes();saved=protected(repo)
    with pytest.raises(ValueError):m.apply(repo,ROOT,plan['receipt'],fetcher=fetch)
    assert (repo/'bots/spy_mr_bot/bot.py').read_bytes()==before and protected(repo)==saved


def test_other_bots_can_trade_without_being_overwritten_or_blocking_this_source_only_update(tmp_path):
    m=module();repo,fetch=setup(tmp_path);plan=m.prepare(repo,ROOT,fetcher=fetch)
    with sqlite3.connect(repo/'var/cc.db') as db:
        db.execute("INSERT INTO orders VALUES(50,'gap_go_spread','QQQ','BUY_TO_OPEN',1,'LMT','sent','paper-options',NULL,'','2026-10-21T14:00:00Z')")
    before=protected(repo)
    assert m.apply(repo,ROOT,plan['receipt'],fetcher=fetch)['ok']
    assert protected(repo)==before
