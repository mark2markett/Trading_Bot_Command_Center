import importlib.util
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

spec = importlib.util.spec_from_file_location('oct14_gate', Path(__file__).with_name('NATIVE-OCT14-PREFLIGHT.py'))
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
AFTER = datetime(2026, 10, 14, 17, tzinfo=ZoneInfo('America/New_York'))


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.delenv('CC_VAR', raising=False)
    target = tmp_path / 'README.md'
    target.write_text('fixture source\n')
    digest = gate.hashlib.sha256(target.read_bytes()).hexdigest()
    monkeypatch.setattr(gate, 'TARGETS', ('README.md',))
    monkeypatch.setattr(gate, 'SOURCE', {'stages': {'original': {'README.md': digest}}})
    (tmp_path / 'var').mkdir()
    with sqlite3.connect(tmp_path / 'var/cc.db') as db:
        db.executescript('CREATE TABLE bots(id TEXT, mode TEXT); CREATE TABLE positions(qty INTEGER); CREATE TABLE orders(id INTEGER PRIMARY KEY,bot_id TEXT,at TEXT,broker_order_id TEXT,side TEXT,qty INTEGER,type TEXT,status TEXT,symbol TEXT,ref_price REAL); CREATE TABLE fills(order_id INTEGER);')
        db.executemany('INSERT INTO bots VALUES (?,?)', [(bot, 'paper') for bot in gate.BOTS])
    return tmp_path


def test_known_source_is_read_only_and_crlf_is_equivalent(root):
    path = root / 'README.md'
    path.write_bytes(path.read_bytes().replace(b'\n', b'\r\n'))
    before = (root / 'var/cc.db').read_bytes()
    assert gate.check(root, AFTER)['source'] == 'original'
    assert (root / 'var/cc.db').read_bytes() == before


@pytest.mark.parametrize('sql', ["UPDATE bots SET mode='live'", "DELETE FROM bots WHERE id='nr7'",
                                'INSERT INTO positions VALUES(1)', "INSERT INTO orders(status) VALUES('sent')"])
def test_refuses_active_or_wrong_fleet_state(root, sql):
    with sqlite3.connect(root / 'var/cc.db') as db:
        db.execute(sql)
    with pytest.raises(ValueError):
        gate.check(root, AFTER)


def test_unknown_source_and_missing_ledger_block(root):
    (root / 'README.md').write_text('changed')
    with pytest.raises(ValueError, match='Unexpected repair source'):
        gate.check(root, AFTER)
    (root / 'README.md').write_text('fixture source\n')
    (root / 'var/cc.db').unlink()
    with pytest.raises(ValueError, match='ledger is missing'):
        gate.check(root, AFTER)


@pytest.mark.parametrize('hour,minute', [(9, 20), (15, 59), (16, 14)])
def test_refuses_trading_window(root, hour, minute):
    with pytest.raises(ValueError, match='after 16:15'):
        gate.check(root, AFTER.replace(hour=hour, minute=minute))


def test_installation_hours_have_no_undocumented_weekend_exception(root):
    with pytest.raises(ValueError, match='after 16:15'):
        gate.check(root, AFTER.replace(day=17, hour=12))


@pytest.mark.parametrize('stage', ['original', 'context', 'installed'])
def test_accepts_only_a_complete_known_stage(root, monkeypatch, stage):
    expected = gate.SOURCE['stages']['original']
    monkeypatch.setattr(gate, 'SOURCE', {'stages': {stage: expected}})
    assert gate.check(root, AFTER)['source'] == stage


def pending_daily(root):
    """Reconstruct the observed order with the daily broker's actual queue format."""
    folder = root / 'bots/spy_mr_bot'
    folder.mkdir(parents=True, exist_ok=True)
    state = {'in_position': False, 'qty': 0, 'stop_order_id': None,
             'last_decide': '2026-10-14', 'pending': {'side': 'BUY', 'qty': 130,
             'date': '2026-10-14', 'reason': 'rsi2_entry', 'order_id': 'paper-1792007403203'}}
    paper = {'cash': 100000., 'positions': {}, 'pending': [{'id': 'paper-1792007403203',
             'kind': 'BUY_MOC', 'symbol': 'SPY', 'qty': 130, 'queued': '2026-10-14T19:50:03.203000+00:00'}],
             'fills': [], 'stops': {}}
    (folder / 'state_paper.json').write_text(json.dumps(state))
    (folder / 'paper_ledger.json').write_text(json.dumps(paper))
    with sqlite3.connect(root / 'var/cc.db') as db:
        db.execute("INSERT INTO orders VALUES(11,'spy_mr','2026-10-14T19:50:03+00:00','paper-1792007403203','BUY',130,'MOC','sent','SPY',768.99)")
    return folder


def test_preserves_normal_queued_daily_buy_without_settling_it(root):
    folder = pending_daily(root)
    paths = [root / 'var/cc.db', folder / 'state_paper.json', folder / 'paper_ledger.json']
    before = [p.read_bytes() for p in paths]
    result = gate.check(root, AFTER)
    assert result['preserved_daily_order'] == {'id': 11, 'symbol': 'SPY', 'qty': 130, 'session_date': '2026-10-14'}
    assert len(result['runtime_fingerprint']) == 64
    assert [p.read_bytes() for p in paths] == before
    assert gate.check(root, AFTER.replace(day=15, hour=9, minute=19))['runtime_fingerprint'] == result['runtime_fingerprint']


@pytest.mark.parametrize('sql', [
    "UPDATE orders SET bot_id='gap_go'", "UPDATE orders SET type='STOP'",
    "UPDATE orders SET side='SELL'", "UPDATE orders SET status='submitted'",
    "UPDATE orders SET symbol='QQQ'", "UPDATE orders SET qty=129",
    "UPDATE orders SET broker_order_id='live-123'", "UPDATE orders SET at='2026-10-13T19:50:03+00:00'",
    "INSERT INTO orders(status) VALUES('pending')", "INSERT INTO fills VALUES(11)",
    "INSERT INTO positions VALUES(130)",
])
def test_daily_exception_refuses_other_or_inconsistent_orders(root, sql):
    pending_daily(root)
    with sqlite3.connect(root / 'var/cc.db') as db:
        db.execute(sql)
    with pytest.raises(ValueError):
        gate.check(root, AFTER)


@pytest.mark.parametrize('file,field,value', [
    ('state_paper.json', 'in_position', True), ('state_paper.json', 'qty', 130),
    ('state_paper.json', 'pending', None), ('state_paper.json', 'last_decide', '2026-10-13'),
    ('paper_ledger.json', 'positions', {'SPY': 130}), ('paper_ledger.json', 'stops', {'SPY': {}}),
    ('paper_ledger.json', 'pending', []), ('paper_ledger.json', 'fills', [{'id': 'paper-1792007403203'}]),
])
def test_daily_exception_requires_matching_unchanged_paper_state(root, file, field, value):
    folder = pending_daily(root)
    path = folder / file
    data = json.loads(path.read_text()); data[field] = value; path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        gate.check(root, AFTER)


def test_stale_or_missing_daily_queue_still_blocks_installation(root):
    folder = pending_daily(root)
    with pytest.raises(ValueError):
        gate.check(root, AFTER.replace(day=15))
    (folder / 'state_paper.json').unlink()
    with pytest.raises((ValueError, OSError)):
        gate.check(root, AFTER)


def test_snapshot_detects_valid_but_changed_daily_state(root):
    folder = pending_daily(root)
    first = gate.check(root, AFTER)['runtime_fingerprint']
    path = folder / 'paper_ledger.json'
    data = json.loads(path.read_text()); data['cash'] -= 1; path.write_text(json.dumps(data))
    assert gate.check(root, AFTER)['runtime_fingerprint'] != first


@pytest.mark.parametrize('cash', [None, '100000', True, float('nan'), float('inf'), -1])
def test_invalid_daily_cash_cannot_qualify_for_maintenance(root, cash):
    folder = pending_daily(root)
    path = folder / 'paper_ledger.json'
    data = json.loads(path.read_text()); data['cash'] = cash; path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='cash'):
        gate.check(root, AFTER)


@pytest.mark.parametrize('price', [None, 0, -1, float('nan'), float('inf'), 'bad'])
def test_invalid_pending_reference_price_blocks_exception(root, price):
    pending_daily(root)
    with sqlite3.connect(root / 'var/cc.db') as db:
        db.execute('UPDATE orders SET ref_price=?', (price,))
    with pytest.raises(ValueError, match='reference price'):
        gate.check(root, AFTER)
