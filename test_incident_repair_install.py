"""Operational repair installs must preserve holdings, controls and incident history."""
import importlib.util
import json
import sqlite3
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parent
NATIVE = Path('/workspace/scratch/native-readiness')
NAMES = {f'cc_server/cc_server/incidents/{name}.py' for name in
         ('__init__', 'models', 'store', 'observe', 'classify', 'readback')}


def load():
    path = ROOT / 'INSTALL-INCIDENT-REPAIR.py'
    if not path.exists():
        pytest.fail('Guarded incident repair installer is not implemented')
    spec = importlib.util.spec_from_file_location('incident_repair_install', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_package(module, package, manifest, payload):
    with zipfile.ZipFile(package / 'incident-repair.zip', 'w') as archive:
        for name, value in payload.items():
            archive.writestr(name, value)
    manifest['archive_sha256'] = module.base.digest((package / 'incident-repair.zip').read_bytes())
    manifest['files'] = {name: module.base.digest(value) for name, value in payload.items()}
    (package / 'INCIDENT-REPAIR.json').write_text(json.dumps(manifest))


def fixture(tmp_path):
    module = load()
    repo, package = tmp_path / 'owner checkout', tmp_path / 'package'
    package.mkdir()
    for folder in ('var/control', 'var/monitor', 'var/backups'):
        (repo / folder).mkdir(parents=True)
    payload, compatible = {}, {}
    for name in NAMES:
        original = subprocess.check_output(['git', '-C', str(NATIVE), 'show', 'c843780:' + name])
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(original.replace(b'\n', b'\r\n'))
        payload[name] = (NATIVE / name).read_bytes()
        compatible[name] = module.base.normalized(original)
    write_package(module, package, {'compatible': compatible}, payload)
    (repo / 'var/control/sip_orb.pause').write_bytes(b'{"reason":"4 consecutive losses"}')
    (repo / 'var/monitor/incidents.db').write_bytes(b'preserve operation history')
    db = sqlite3.connect(repo / 'var/cc.db')
    try:
        db.executescript('CREATE TABLE bots(id,mode); INSERT INTO bots VALUES("spy_mr","paper");'
                         'CREATE TABLE positions(symbol,qty); INSERT INTO positions VALUES("SPY",130);'
                         + ''.join('CREATE TABLE ' + name + '(id);' for name in ('orders','fills','trades','limits','controls')))
        db.commit()
    finally:
        db.close()
    def fetcher(route):
        if route == '/api/health':
            return json.dumps({'ok': True, 'db': str(repo / 'var/cc.db')}).encode()
        if route == '/api/incidents?limit=1':
            return b'{"monitor":{"status":"checking"},"open_count":3,"open":[]}'
        raise AssertionError('Unexpected endpoint: ' + route)
    return module, repo, package, payload, fetcher


def protected(repo):
    return {p.relative_to(repo).as_posix(): p.read_bytes() for p in (repo / 'var').rglob('*')
            if p.is_file() and 'backups' not in p.parts}


def test_repair_preserves_open_holding_pauses_and_operations_database(tmp_path):
    module, repo, package, payload, fetcher = fixture(tmp_path)
    before = protected(repo)
    receipt = Path(module.prepare(repo, package, fetcher)['receipt'])
    module.apply(repo, package, receipt)
    assert module.verify(repo, package, receipt, fetcher)['ok']
    assert protected(repo) == before
    assert all((repo / name).read_bytes() == value for name, value in payload.items())
    module.rollback(repo, package, receipt)
    assert protected(repo) == before
    assert b'previous = self.conn.execute' not in (repo / 'cc_server/cc_server/incidents/store.py').read_bytes()


def test_repair_refuses_unreviewed_source_before_changes(tmp_path):
    module, repo, package, _payload, fetcher = fixture(tmp_path)
    path = repo / 'cc_server/cc_server/incidents/store.py'
    path.write_text('# owner modification\n')
    with pytest.raises(ValueError, match='source differs'):
        module.prepare(repo, package, fetcher)
    assert path.read_text() == '# owner modification\n'


def test_repair_rejects_changed_source_after_preflight(tmp_path):
    module, repo, package, _payload, fetcher = fixture(tmp_path)
    receipt = Path(module.prepare(repo, package, fetcher)['receipt'])
    path = repo / 'cc_server/cc_server/incidents/classify.py'
    path.write_text('# concurrent owner edit\n')
    with pytest.raises(ValueError, match='changed since preflight'):
        module.apply(repo, package, receipt)
    assert path.read_text() == '# concurrent owner edit\n'


def test_repair_refuses_wrong_api_ledger(tmp_path):
    module, repo, package, _payload, _fetcher = fixture(tmp_path)
    with pytest.raises(ValueError, match='ledger does not match'):
        module.prepare(repo, package, lambda _: b'{"ok":true,"db":"/wrong/cc.db"}')


def test_partial_install_restores_original_sources(tmp_path, monkeypatch):
    module, repo, package, _payload, fetcher = fixture(tmp_path)
    receipt = Path(module.prepare(repo, package, fetcher)['receipt'])
    before = protected(repo)
    original, failed = module.base.atomic, False
    def fail_once(path, value):
        nonlocal failed
        if path.name == 'store.py' and not failed:
            failed = True
            raise OSError('disk failure')
        return original(path, value)
    monkeypatch.setattr(module.base, 'atomic', fail_once)
    with pytest.raises(OSError, match='disk failure'):
        module.apply(repo, package, receipt)
    assert protected(repo) == before
    assert all((repo / name).read_bytes() == (receipt / name).read_bytes() for name in NAMES)


def test_rollback_refuses_altered_backup(tmp_path):
    module, repo, package, payload, fetcher = fixture(tmp_path)
    receipt = Path(module.prepare(repo, package, fetcher)['receipt'])
    module.apply(repo, package, receipt)
    (receipt / 'cc_server/cc_server/incidents/store.py').write_text('# altered backup\n')
    with pytest.raises(ValueError, match='Backup checksum'):
        module.rollback(repo, package, receipt)
    assert (repo / 'cc_server/cc_server/incidents/store.py').read_bytes() == payload['cc_server/cc_server/incidents/store.py']


def test_archive_path_escape_is_refused(tmp_path):
    module, repo, package, payload, fetcher = fixture(tmp_path)
    manifest = json.loads((package / 'INCIDENT-REPAIR.json').read_text())
    payload['../escape.py'] = b'# bad\n'
    write_package(module, package, manifest, payload)
    with pytest.raises(ValueError, match='Unsafe'):
        module.prepare(repo, package, fetcher)


def test_repair_requires_a_genuine_cross_session_recovery_before_install(tmp_path):
    module, repo, package, payload, fetcher = fixture(tmp_path)
    manifest = json.loads((package / 'INCIDENT-REPAIR.json').read_text())
    payload['cc_server/cc_server/incidents/store.py'] = subprocess.check_output(
        ['git', '-C', str(NATIVE), 'show', 'c843780:cc_server/cc_server/incidents/store.py'])
    write_package(module, package, manifest, payload)
    with pytest.raises(ValueError, match='recovery probe'):
        module.prepare(repo, package, fetcher)


def test_repeated_install_is_safe_and_preserves_runtime_history(tmp_path):
    module, repo, package, payload, fetcher = fixture(tmp_path)
    before = protected(repo)
    for _ in range(2):
        receipt = Path(module.prepare(repo, package, fetcher)['receipt'])
        module.apply(repo, package, receipt)
        assert module.verify(repo, package, receipt, fetcher)['ok']
    assert protected(repo) == before
    assert all((repo / name).read_bytes() == value for name, value in payload.items())
