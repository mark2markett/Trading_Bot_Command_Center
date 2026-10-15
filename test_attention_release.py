"""Actual source bundle round trip under idle/pending-MOC runtime guards."""
import importlib.util
import json
import sqlite3
from pathlib import Path
import pytest
from test_native_oct14_release import git,NATIVE,AFTER
from test_native_oct14_preflight import pending_daily,gate
HERE=Path(__file__).parent

@pytest.mark.parametrize('pending',[False,True])
def test_real_attention_bundle_install_repeat_and_rollback_preserve_runtime(tmp_path,monkeypatch,pending):
    monkeypatch.delenv('CC_VAR',raising=False)
    release=json.loads((HERE/'ATTENTION-NATIVE-SOURCE.json').read_text())
    root=tmp_path/'native'
    git(tmp_path,'clone','--no-hardlinks','--no-checkout',str(NATIVE),str(root))
    git(root,'config','user.name','Isolated rehearsal'); git(root,'config','user.email','test@example.invalid')
    git(root,'checkout','-b','feat/options-m7',release['base'])
    owner={'bots/spy_mr_bot/bot.log':b'owner log\n','scripts/dev.sh':b'owner launcher\n','docs/handoffs/owner.md':b'owner handoff\n'}
    for name,data in owner.items():
        path=root/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(data)
    runtime=root/'var'; runtime.mkdir(exist_ok=True)
    with sqlite3.connect(runtime/'cc.db') as db:
        db.executescript('CREATE TABLE bots(id TEXT,mode TEXT);CREATE TABLE positions(qty INTEGER);CREATE TABLE orders(id INTEGER PRIMARY KEY,bot_id TEXT,at TEXT,broker_order_id TEXT,side TEXT,qty INTEGER,type TEXT,status TEXT,symbol TEXT,ref_price REAL);CREATE TABLE fills(order_id INTEGER);')
        db.executemany('INSERT INTO bots VALUES(?,?)',[(b,'paper') for b in gate.BOTS])
    if pending: pending_daily(root)
    paths=[runtime/'cc.db',*(root/'bots/spy_mr_bot').glob('*paper*.json')]
    before={str(p):p.read_bytes() for p in paths}
    spec=importlib.util.spec_from_file_location('attention_gate',HERE/'ATTENTION-PREFLIGHT.py')
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    original=m.check(root,AFTER)
    assert original['source']=='before'
    git(root,'bundle','verify',str(HERE/'attention-native.bundle'))
    git(root,'fetch',str(HERE/'attention-native.bundle'),release['branch']+':refs/test/attention')
    commits=git(root,'rev-list','--reverse',release['base']+'..'+release['tip']).splitlines()
    for commit in commits: git(root,'cherry-pick',commit)
    installed=m.check(root,AFTER)
    assert installed['source']=='installed' and installed['runtime_fingerprint']==original['runtime_fingerprint']
    assert m.check(root,AFTER)==installed
    assert all(p.read_bytes()==before[str(p)] for p in paths)
    assert all((root/name).read_bytes()==value for name,value in owner.items())
    if commits: git(root,'revert','--no-edit',*reversed(commits))
    assert m.check(root,AFTER)['source']=='before'
    assert all(p.read_bytes()==before[str(p)] for p in paths)
    assert all((root/name).read_bytes()==value for name,value in owner.items())

@pytest.mark.parametrize('prefix',[1,4])
def test_partial_install_receipt_stage_can_be_reverted(tmp_path,monkeypatch,prefix):
    monkeypatch.delenv('CC_VAR',raising=False)
    release=json.loads((HERE/'ATTENTION-NATIVE-SOURCE.json').read_text())
    root=tmp_path/'partial'
    git(tmp_path,'clone','--no-hardlinks','--no-checkout',str(NATIVE),str(root))
    git(root,'config','user.name','Partial rehearsal');git(root,'config','user.email','partial@example.invalid')
    git(root,'checkout','-b','feat/options-m7',release['base'])
    (root/'var').mkdir()
    with sqlite3.connect(root/'var/cc.db') as db:
        db.executescript('CREATE TABLE bots(id TEXT,mode TEXT);CREATE TABLE positions(qty INTEGER);CREATE TABLE orders(id INTEGER PRIMARY KEY,status TEXT);CREATE TABLE fills(order_id INTEGER);')
        db.executemany('INSERT INTO bots VALUES(?,?)',[(b,'paper') for b in gate.BOTS])
    spec=importlib.util.spec_from_file_location('partial_gate',HERE/'ATTENTION-PREFLIGHT.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    before=(root/'var/cc.db').read_bytes()
    commits=git(root,'rev-list','--reverse',release['base']+'..'+release['tip']).splitlines()[:prefix]
    for commit in commits: git(root,'cherry-pick',commit)
    assert m.check(root,AFTER)['source'].startswith('step_')
    git(root,'revert','--no-edit',*reversed(commits))
    assert m.check(root,AFTER)['source']=='before'
    assert (root/'var/cc.db').read_bytes()==before
