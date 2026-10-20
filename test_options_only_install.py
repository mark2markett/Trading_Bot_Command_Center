"""Audit-first restrictive policy, preserving the inherited holding and options controls."""
import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest

from test_activity_dashboard_install import fixture, installer

ROOT=Path(__file__).parent
STOCKS={'spy_mr','gap_go','nr7','sip_orb'}


def module():
    path=ROOT/'OPTIONS-ONLY.py'
    assert path.is_file(),'Options-only activation helper is missing'
    spec=importlib.util.spec_from_file_location('options_only_install',path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def setup(tmp_path):
    repo,package,payload,_=fixture(tmp_path)
    with sqlite3.connect(repo/'var/cc.db') as db:
        db.executemany('INSERT INTO bots VALUES(?,?)',[(bot,'paper') for bot in STOCKS|{'gap_go_spread'} if bot!='spy_mr'])
        for name in ('at','actor','action','target','before_json','after_json','note'):
            db.execute('ALTER TABLE controls ADD COLUMN '+name+' TEXT')
    (repo/'var/control/gap_go_spread.pause').write_text('{"reason":"independent options risk pause"}')
    state={'posts':[], 'orders':[{'id':1,'symbol':'SPY','side':'SELL','type':'STOP','qty':130}], 'fail':None}
    def fetcher(route,body=None):
        if route=='/api/health':return json.dumps({'ok':True,'db':str(repo/'var/cc.db')}).encode()
        if route=='/api/activity':
            policy=(repo/'var/control/OPTIONS_ONLY').exists()
            bots=[]
            for bot in sorted(STOCKS|{'gap_go_spread'}):
                paused=(repo/('var/control/'+bot+'.pause')).exists()
                bots.append({'id':bot,'mode':'paper','entry_state':'paused' if paused else 'clear'})
            return json.dumps({'entry_policy':{'options_only':policy},'bots':bots,'working_orders':state['orders'],
                'positions':[{'symbol':'SPY','kind':'shares','quantity':130}], 'summary':{'open_positions':1}}).encode()
        if route.startswith('/api/controls/bot/'):
            bot=route.split('/')[-2];state['posts'].append(bot)
            if bot==state['fail']:raise TimeoutError('simulated API pause timeout')
            assert bot in STOCKS and route.endswith('/pause')
            with sqlite3.connect(repo/'var/cc.db') as db:
                db.execute("INSERT INTO controls(action,target) VALUES('pause',?)",(bot,))
            (repo/('var/control/'+bot+'.pause')).write_text(json.dumps({'reason':body['note']}))
            return b'{"ok":true}'
        raise AssertionError(route)
    receipt=repo/'var/backups/options-only-test.json'
    return repo,package,payload,receipt,fetcher,state


def financial(repo):
    with sqlite3.connect(repo/'var/cc.db') as db:
        return {table:db.execute('SELECT * FROM '+table).fetchall() for table in ('positions','orders','fills','trades','limits')}


def installed(repo,payload):
    for name in installer.SOURCE:
        (repo/name).parent.mkdir(parents=True,exist_ok=True);(repo/name).write_bytes(payload[name])


def test_policy_is_audited_before_flag_and_preserves_share_holding_options_pause(tmp_path,monkeypatch):
    m=module();repo,package,payload,receipt,fetcher,state=setup(tmp_path)
    before=financial(repo);sip=(repo/'var/control/sip_orb.pause').read_bytes()
    options=(repo/'var/control/gap_go_spread.pause').read_bytes()
    m.contain(repo,receipt,fetcher=fetcher)
    installed(repo,payload)
    original=Path.open
    def observe_open(path,mode='r',*args,**kwargs):
        if path.name=='OPTIONS_ONLY' and mode=='x':
            with sqlite3.connect(repo/'var/cc.db') as db:
                assert db.execute("SELECT 1 FROM controls WHERE action='options_only'").fetchone()
        return original(path,mode,*args,**kwargs)
    monkeypatch.setattr(Path,'open',observe_open)
    assert m.activate(repo,package,receipt,fetcher=fetcher)['options_only'] is True
    result=m.verify(repo,receipt,fetcher=fetcher)
    assert result['ok'] and result['existing_share_positions'][0]['quantity']==130
    assert financial(repo)==before
    assert (repo/'var/control/sip_orb.pause').read_bytes()==sip
    assert (repo/'var/control/gap_go_spread.pause').read_bytes()==options
    assert set(state['posts'])==STOCKS-{'sip_orb'}


def test_pending_share_entry_is_reported_without_fake_cancellation(tmp_path):
    m=module();repo,package,payload,receipt,fetcher,state=setup(tmp_path)
    state['orders'].append({'id':2,'symbol':'SPY','side':'BUY','type':'MOC','qty':5})
    m.contain(repo,receipt,fetcher=fetcher);installed(repo,payload)
    with pytest.raises(ValueError,match='Pending share'):
        m.activate(repo,package,receipt,fetcher=fetcher)
    assert not (repo/'var/control/OPTIONS_ONLY').exists()
    assert state['orders'][-1]['side']=='BUY'
    assert all((repo/('var/control/'+bot+'.pause')).is_file() for bot in STOCKS)


def test_source_change_refuses_activation_without_unpausing_stocks(tmp_path):
    m=module();repo,package,payload,receipt,fetcher,state=setup(tmp_path)
    m.contain(repo,receipt,fetcher=fetcher);installed(repo,payload)
    (repo/'cc_server/cc_server/api.py').write_text('# owner change')
    with pytest.raises(ValueError,match='source'):
        m.activate(repo,package,receipt,fetcher=fetcher)
    assert not (repo/'var/control/OPTIONS_ONLY').exists()
    assert all((repo/('var/control/'+bot+'.pause')).exists() for bot in STOCKS)


def test_pause_failure_does_not_resume_anything_or_enable_policy(tmp_path):
    m=module();repo,package,payload,receipt,fetcher,state=setup(tmp_path)
    state['fail']='nr7'
    with pytest.raises(TimeoutError):m.contain(repo,receipt,fetcher=fetcher)
    assert (repo/'var/control/gap_go.pause').exists()
    assert (repo/'var/control/sip_orb.pause').exists()
    assert (repo/'var/control/gap_go_spread.pause').exists()
    assert not (repo/'var/control/OPTIONS_ONLY').exists()
    assert receipt.exists()


def test_wrong_running_ledger_is_refused_before_controls(tmp_path):
    m=module();repo,package,payload,receipt,fetcher,state=setup(tmp_path)
    with pytest.raises(ValueError,match='ledger'):
        m.contain(repo,receipt,fetcher=lambda *args:b'{"ok":true,"db":"/wrong/cc.db"}')
    assert state['posts']==[]


def test_audit_trigger_cannot_write_positions_before_marker(tmp_path):
    m=module();repo,package,payload,receipt,fetcher,state=setup(tmp_path)
    m.contain(repo,receipt,fetcher=fetcher);installed(repo,payload)
    before=financial(repo)
    with sqlite3.connect(repo/'var/cc.db') as db:
        db.execute("CREATE TRIGGER unsafe_control AFTER INSERT ON controls BEGIN UPDATE positions SET qty=0; END")
    with pytest.raises(sqlite3.DatabaseError):m.activate(repo,package,receipt,fetcher=fetcher)
    assert not (repo/'var/control/OPTIONS_ONLY').exists()
    assert financial(repo)==before


def test_repeated_install_keeps_existing_restriction_and_audit(tmp_path):
    m=module();repo,package,payload,receipt,fetcher,state=setup(tmp_path)
    m.contain(repo,receipt,fetcher=fetcher);installed(repo,payload)
    m.activate(repo,package,receipt,fetcher=fetcher);m.verify(repo,receipt,fetcher=fetcher)
    marker=(repo/'var/control/OPTIONS_ONLY').read_bytes();posts=state['posts'][:]
    receipt=receipt.with_name('options-only-repeat.json')
    m.contain(repo,receipt,fetcher=fetcher);m.activate(repo,package,receipt,fetcher=fetcher)
    assert m.verify(repo,receipt,fetcher=fetcher)['ok']
    assert marker==(repo/'var/control/OPTIONS_ONLY').read_bytes() and state['posts']==posts
    with sqlite3.connect(repo/'var/cc.db') as db:
        assert db.execute("SELECT COUNT(*) FROM controls WHERE action='options_only'").fetchone()[0]==1
