"""A display-only update must preserve an open holding, its stop and all source/state."""
import hashlib
import importlib.util
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest


def load():
    path = Path(__file__).with_name('APPLY-ATTENTION-DISPLAY.py')
    assert path.exists(), 'Display-only deployment is missing'
    spec = importlib.util.spec_from_file_location('display_update', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture(tmp_path):
    repo, package = tmp_path / 'repo', tmp_path / 'package'
    dist = repo / 'cc_web' / 'dist'
    (dist / 'assets').mkdir(parents=True)
    (dist / 'index.html').write_bytes(b'old dashboard')
    (dist / 'assets' / 'old.js').write_bytes(b'old client still loading')
    (repo / 'var' / 'control').mkdir(parents=True)
    (repo / 'var' / 'control' / 'PAUSE_ENTRIES').write_bytes(b'{"reason":"keep"}')
    (repo / 'bots').mkdir()
    (repo / 'bots' / 'source.py').write_bytes(b'unchanged bot')
    dbpath = repo / 'var' / 'cc.db'
    with sqlite3.connect(dbpath) as db:
        db.executescript('CREATE TABLE positions(symbol,qty); INSERT INTO positions VALUES("SPY",130);'
                         'CREATE TABLE orders(symbol,side,qty); INSERT INTO orders VALUES("SPY","STOP",130);')
    package.mkdir()
    with zipfile.ZipFile(package / 'attention-dashboard.zip', 'w') as z:
        z.writestr('index.html', '<script src="/assets/new.js"></script>')
        z.writestr('assets/new.js', 'Monitor unavailable')
    digest = hashlib.sha256((package / 'attention-dashboard.zip').read_bytes()).hexdigest()
    (package / 'ATTENTION-SHA256.txt').write_text(digest + '  attention-dashboard.zip\n')

    def fetch(path):
        if path == '/api/health':
            return json.dumps({'ok': True, 'db': str(dbpath)}).encode()
        return (dist / ('index.html' if path == '/' else path.lstrip('/'))).read_bytes()

    protected = [dbpath, repo / 'var' / 'control' / 'PAUSE_ENTRIES', repo / 'bots' / 'source.py']
    return repo, package, dist, fetch, {p: p.read_bytes() for p in protected}


def test_display_update_preserves_open_holding_stops_controls_source_and_old_assets(tmp_path):
    module = load()
    repo, package, dist, fetch, before = fixture(tmp_path)
    result = module.install(repo, package, fetch=fetch)
    assert result['ok'] and result['scope'] == 'DISPLAY_ONLY'
    assert (dist / 'assets' / 'new.js').read_text() == 'Monitor unavailable'
    assert (dist / 'assets' / 'old.js').read_bytes() == b'old client still loading'
    assert (Path(result['receipt']) / 'index.html').read_bytes() == b'old dashboard'
    assert all(p.read_bytes() == value for p, value in before.items())
    assert module.install(repo, package, fetch=fetch)['already_installed']


def test_failed_http_verification_restores_old_index_without_touching_trading_state(tmp_path):
    module = load()
    repo, package, dist, fetch, before = fixture(tmp_path)

    def failed(path):
        return b'wrong page' if path == '/' else fetch(path)

    with pytest.raises(ValueError, match='served'):
        module.install(repo, package, fetch=failed)
    assert (dist / 'index.html').read_bytes() == b'old dashboard'
    assert all(p.read_bytes() == value for p, value in before.items())


def test_wrong_server_root_and_bad_payload_fail_before_changes(tmp_path):
    module = load()
    repo, package, dist, fetch, before = fixture(tmp_path)
    with pytest.raises(ValueError, match='repository'):
        module.install(repo, package, fetch=lambda _: b'{"ok":true,"db":"/another/cc.db"}')
    (package / 'attention-dashboard.zip').write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='checksum'):
        module.install(repo, package, fetch=fetch)
    assert (dist / 'index.html').read_bytes() == b'old dashboard'
    assert all(p.read_bytes() == value for p, value in before.items())


def test_asset_collision_is_refused_before_replacing_index(tmp_path):
    module = load()
    repo, package, dist, fetch, _before = fixture(tmp_path)
    (dist / 'assets' / 'new.js').write_bytes(b'owner asset')
    with pytest.raises(ValueError, match='collision'):
        module.install(repo, package, fetch=fetch)
    assert (dist / 'index.html').read_bytes() == b'old dashboard'
    assert (dist / 'assets' / 'new.js').read_bytes() == b'owner asset'
