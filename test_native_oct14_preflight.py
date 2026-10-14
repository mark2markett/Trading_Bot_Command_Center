import importlib.util
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
        db.executescript('CREATE TABLE bots(id TEXT, mode TEXT); CREATE TABLE positions(qty INTEGER); CREATE TABLE orders(status TEXT);')
        db.executemany('INSERT INTO bots VALUES (?,?)', [(bot, 'paper') for bot in gate.BOTS])
    return tmp_path


def test_known_source_is_read_only_and_crlf_is_equivalent(root):
    path = root / 'README.md'
    path.write_bytes(path.read_bytes().replace(b'\n', b'\r\n'))
    before = (root / 'var/cc.db').read_bytes()
    assert gate.check(root, AFTER)['source'] == 'original'
    assert (root / 'var/cc.db').read_bytes() == before


@pytest.mark.parametrize('sql', ["UPDATE bots SET mode='live'", "DELETE FROM bots WHERE id='nr7'",
                                'INSERT INTO positions VALUES(1)', "INSERT INTO orders VALUES('sent')"])
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
