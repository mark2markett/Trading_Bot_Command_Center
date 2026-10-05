"""Real SQLite cross-thread regressions run in children so a native deadlock is bounded."""
import os
import subprocess
import sys
from pathlib import Path


def run_probe(tmp_path, source):
    script = tmp_path / "probe.py"
    script.write_text(source, encoding="utf-8")
    env = dict(os.environ, CC_VAR=str(tmp_path / "var"), MODE="paper", PYTHONDONTWRITEBYTECODE="1")
    root = Path(__file__).resolve().parents[2]
    env["PYTHONPATH"] = os.pathsep.join(str(root / p) for p in ("cc_sdk", "cc_server", "."))
    executable = sys.executable
    if os.name == "nt" and sys.prefix != sys.base_prefix:
        # Own the interpreter rather than the Windows venv redirector, so the
        # timeout cannot leave a deadlocked child. No dependency on harness code.
        executable = sys._base_executable
        env["__PYVENV_LAUNCHER__"] = sys.executable
    result = subprocess.run([executable, str(script)], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_shared_ledger_preserves_parameter_rows_and_json_under_concurrency(tmp_path):
    run_probe(tmp_path, '''
import json
from concurrent.futures import ThreadPoolExecutor
from cc_sdk.ledger import Ledger
L = Ledger()
L.x('CREATE TABLE probe (id INTEGER PRIMARY KEY, value TEXT NOT NULL)')
for i in range(32):
    L.x('INSERT INTO probe VALUES(?,?)', (i, str(i)))
def worker(number):
    for i in range(150):
        key = (i + number) % 32
        row = L.one('SELECT id,value,? AS marker FROM probe WHERE id=?', (number, key))
        assert row is not None, 'Existing parameterized row disappeared'
        assert (row['id'], row['value'], row['marker']) == (key, str(key), number), 'Cross-thread row contamination'
        rows = L.q('SELECT id FROM probe WHERE id>=? AND id<? ORDER BY id', (key, min(key+3, 32)))
        assert [r['id'] for r in rows] == list(range(key, min(key+3, 32)))
        L.x('INSERT INTO kv VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json',
            (str(number), json.dumps({'worker': number, 'iteration': i}), 'fixture'))
        stored = L.one('SELECT value_json FROM kv WHERE key=?', (str(number),))
        assert stored is not None
        assert json.loads(stored['value_json']) == {'worker': number, 'iteration': i}
with ThreadPoolExecutor(max_workers=16) as pool:
    list(pool.map(worker, range(16)))
assert L.one('SELECT COUNT(*) n FROM kv')['n'] == 16
L.conn.close()
''')


def test_dashboard_endpoints_and_risk_ticks_share_ledger_without_stalling(tmp_path):
    run_probe(tmp_path, '''
from concurrent.futures import ThreadPoolExecutor
from cc_sdk.ledger import Ledger
from cc_sdk.manifest import BotManifest
from cc_server import api, db, riskd
from fastapi import FastAPI
from fastapi.testclient import TestClient
L = Ledger()
L.upsert_bot(BotManifest(id='fixture', name='Fixture', version='1', strategy_line='fixture', instrument='SPY', mode='paper', cadence={}).to_row())
L.heartbeat('fixture', 'session', True)
api._L = L
app = FastAPI()
app.include_router(api.router)
paths = ['/api/health', '/api/bots', '/api/fleet', '/api/risk', '/api/alerts', '/api/research']
with TestClient(app) as client:
    def requests(number):
        for i in range(24):
            path = paths[(number+i) % len(paths)]
            response = client.get(path)
            assert response.status_code == 200, (path, response.status_code)
            data = response.json()
            if path == '/api/bots':
                assert len(data) == 1 and data[0]['id'] == 'fixture'
            elif path == '/api/health':
                assert data['ok'] is True
    def monitor():
        for i in range(24):
            riskd.tick(L)
    with ThreadPoolExecutor(max_workers=11) as pool:
        tasks = [pool.submit(requests, i) for i in range(10)] + [pool.submit(monitor)]
        for task in tasks:
            task.result(timeout=15)
assert db.kv_get(L, 'riskd_last')['at']
assert L.one('PRAGMA quick_check')[0] == 'ok'
L.conn.close()
''')


def test_concurrent_position_migration_preserves_legacy_holdings(tmp_path):
    run_probe(tmp_path, '''
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from cc_sdk.ledger import Ledger, db_path
path = db_path()
path.parent.mkdir(parents=True)
with sqlite3.connect(path) as connection:
    connection.executescript("CREATE TABLE positions(bot_id TEXT PRIMARY KEY, symbol TEXT, qty INTEGER, avg_price REAL, entry_at TEXT, bars_held INTEGER, updated_at TEXT);")
    connection.execute('INSERT INTO positions VALUES(?,?,?,?,?,?,?)', ('fixture', 'SPY', 7, 500, 'entry', 0, 'updated'))
L = Ledger()
barrier = threading.Barrier(12)
def worker(number):
    barrier.wait(timeout=5)
    rows = L.positions_for('fixture')
    assert len(rows) == 1
    assert rows[0]['symbol'] == 'SPY' and rows[0]['qty'] == 7
with ThreadPoolExecutor(max_workers=12) as pool:
    list(pool.map(worker, range(12)))
L.set_position('fixture', 'QQQ', 3, 400, 'entry', 0)
assert [r['symbol'] for r in L.positions_for('fixture')] == ['QQQ', 'SPY']
L.conn.close()
''')
