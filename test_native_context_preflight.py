import importlib.util
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

spec = importlib.util.spec_from_file_location('preflight', Path(__file__).with_name('NATIVE-CONTEXT-PREFLIGHT.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
AFTER = datetime(2026,10,13,17,tzinfo=ZoneInfo('America/New_York'))


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.delenv('CC_VAR', raising=False)
    source = tmp_path / 'cc_sdk/cc_sdk/intraday.py'
    source.parent.mkdir(parents=True)
    source.write_text('synthetic prior source\n')
    monkeypatch.setattr(module, 'ORIGINAL', module.hashlib.sha256(source.read_bytes()).hexdigest())
    var = tmp_path / 'var'
    var.mkdir()
    with sqlite3.connect(var / 'cc.db') as db:
        db.executescript('CREATE TABLE bots(id TEXT, mode TEXT); CREATE TABLE positions(qty INTEGER); CREATE TABLE orders(status TEXT);')
        db.executemany('INSERT INTO bots VALUES (?,?)', [(b,'paper') for b in module.BOTS])
    return tmp_path


def mutate(root, sql):
    with sqlite3.connect(root / 'var/cc.db') as db:
        db.execute(sql)


def test_preflight_is_read_only_and_accepts_crlf(root):
    source = root / 'cc_sdk/cc_sdk/intraday.py'
    source.write_bytes(source.read_bytes().replace(b'\n', b'\r\n'))
    before = (root / 'var/cc.db').read_bytes()
    assert module.check(root, AFTER)['source'] == 'ready'
    assert (root / 'var/cc.db').read_bytes() == before


@pytest.mark.parametrize('sql,message', [
    ("UPDATE bots SET mode='live' WHERE id='sip_orb'", 'paper bots'),
    ("DELETE FROM bots WHERE id='nr7'", 'paper bots'),
    ('INSERT INTO positions VALUES (3)', 'Open positions'),
    ("INSERT INTO orders VALUES ('sent')", 'Unresolved orders'),
])
def test_refuses_unsafe_native_state(root, sql, message):
    mutate(root, sql)
    with pytest.raises(ValueError, match=message):
        module.check(root, AFTER)


def test_refuses_unknown_source(root):
    (root / 'cc_sdk/cc_sdk/intraday.py').write_text('unrelated local changes')
    with pytest.raises(ValueError, match='Unexpected intraday'):
        module.check(root, AFTER)


def test_refuses_session_window_and_missing_db(root):
    with pytest.raises(ValueError, match='Install after'):
        module.check(root, AFTER.replace(hour=10))
    (root / 'var/cc.db').unlink()
    with pytest.raises(ValueError, match='ledger is missing'):
        module.check(root, AFTER)
    assert not (root / 'var/cc.db').exists()
