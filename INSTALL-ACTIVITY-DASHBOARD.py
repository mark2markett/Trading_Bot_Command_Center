"""Guarded source/static update. Never opens the trading database for writing."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
import tempfile
import urllib.request
import uuid
import zipfile

SOURCE = {'cc_server/cc_server/api.py', 'cc_server/cc_server/activity.py', 'cc_server/cc_server/risk_reporting.py'}
INDEX = 'cc_web/dist/index.html'

def digest(value):
    return hashlib.sha256(value).hexdigest()

def normalized(value):
    return digest(value.replace(b'\r\n', b'\n'))

def atomic(path, value):
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.activity-', delete=False) as stream:
        stream.write(value)
        tmp = Path(stream.name)
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)

def safe_target(repo, name):
    target = repo / name
    if not target.resolve(strict=False).is_relative_to(repo) or target.is_symlink() or any(p.is_symlink() or getattr(p, 'is_junction', lambda: False)() for p in target.parents if p != repo and repo in p.parents):
        raise ValueError('Symbolic-link target refused: ' + name)
    if target.exists() and not target.is_file():
        raise ValueError('Non-file target refused: ' + name)
    return target

def read_package(package):
    manifest = json.loads((package / 'ACTIVITY-DASHBOARD.json').read_text())
    if not SOURCE.issubset(manifest['compatible']):
        raise ValueError('Activity source compatibility manifest is incomplete')
    archive = package / 'activity-dashboard.zip'
    if digest(archive.read_bytes()) != manifest['archive_sha256']:
        raise ValueError('Activity archive checksum mismatch')
    payload = {}
    with zipfile.ZipFile(archive) as z:
        if len(z.infolist()) > 1000 or sum(i.file_size for i in z.infolist()) > 20_000_000:
            raise ValueError('Activity archive exceeds limits')
        for info in z.infolist():
            p = PurePosixPath(info.filename)
            allowed = info.filename in SOURCE or info.filename in {INDEX, 'cc_web/dist/favicon.svg', 'cc_web/dist/icons.svg'} or (info.filename.startswith('cc_web/dist/assets/') and len(p.parts) == 4)
            if not allowed or info.is_dir() or p.is_absolute() or '..' in p.parts or '\\' in info.filename or ':' in info.filename or str(p) != info.filename or info.filename in payload:
                raise ValueError('Unsafe activity archive path')
            payload[info.filename] = z.read(info)
    if set(payload) != set(manifest['files']) or not SOURCE.issubset(payload) or INDEX not in payload:
        raise ValueError('Activity archive manifest differs')
    for name, value in payload.items():
        if digest(value) != manifest['files'][name]:
            raise ValueError('Activity payload hash differs')
        if name in SOURCE:
            compile(value, name, 'exec')
    return manifest, payload

def fetch(route):
    with urllib.request.urlopen('http://127.0.0.1:8585' + route, timeout=10) as response:
        return response.read(20_000_001)

def health_identity(repo, fetcher=fetch):
    h = json.loads(fetcher('/api/health'))
    actual = Path(h.get('db', '')).resolve()
    expected = (repo / 'var/cc.db').resolve(strict=True)
    if h.get('ok') is not True or os.path.normcase(str(actual)) != os.path.normcase(str(expected)):
        raise ValueError('Running API ledger does not match selected repository')

def evidence(repo):
    db = (repo / 'var/cc.db').resolve(strict=True)
    connection = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        bots = [dict(r) for r in connection.execute('SELECT id,mode FROM bots')]
        if not bots or any(b['mode'] != 'paper' for b in bots):
            raise ValueError('This update is validated for the paper fleet only')
        tables = ('positions', 'orders', 'fills', 'trades', 'limits', 'controls')
        counts = {t: connection.execute('SELECT COUNT(*) FROM ' + t).fetchone()[0] for t in tables}
        positions = [dict(r) for r in connection.execute('SELECT * FROM positions WHERE qty<>0')]
    finally:
        connection.close()
    controls = repo / 'var/control'
    if not controls.is_dir() or controls.is_symlink():
        raise ValueError('Control directory unavailable')
    flags = {p.name: digest(p.read_bytes()) for p in controls.iterdir() if p.is_file()}
    return {'observed_counts': counts, 'open_positions': positions, 'control_hashes': flags,
            'note': 'Read-only observations. Running paper bots may legitimately update their ledger while installation runs.'}

def validate_source(repo, manifest, payload):
    for name, expected in manifest['compatible'].items():
        target = safe_target(repo, name)
        actual = normalized(target.read_bytes()) if target.exists() else None
        accepted = {expected}
        if name in SOURCE:
            accepted.add(normalized(payload[name]))
        if actual not in accepted:
            raise ValueError('Installed source differs from reviewed version: ' + name)
    for name, value in payload.items():
        target = safe_target(repo, name)
        if name not in SOURCE and name != INDEX and target.exists() and target.read_bytes() != value:
            raise ValueError('Existing static asset collision: ' + name)
    if not safe_target(repo, INDEX).is_file():
        raise ValueError('Existing dashboard index required')

def prepare(repo, package, fetcher=fetch):
    repo = Path(repo).resolve(strict=True)
    manifest, payload = read_package(package)
    health_identity(repo, fetcher)
    validate_source(repo, manifest, payload)
    observed = evidence(repo)
    parent = repo / 'var/backups'
    if not parent.resolve(strict=False).is_relative_to(repo) or parent.is_symlink() or getattr(parent, 'is_junction', lambda: False)():
        raise ValueError('Backup directory is a symbolic link')
    parent.mkdir(exist_ok=True)
    receipt = parent / ('activity-dashboard-' + uuid.uuid4().hex)
    receipt.mkdir()
    originals = {}
    for name in sorted(SOURCE | {INDEX}):
        target = safe_target(repo, name)
        old = target.read_bytes() if target.exists() else None
        originals[name] = digest(old) if old is not None else None
        if old is not None:
            backup = receipt / name
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(old)
    saved = {'repo': str(repo), 'files': manifest['files'], 'originals': originals,
             'archive_sha256': manifest['archive_sha256'], 'state': 'prepared', 'scope': 'READ_ONLY_ACTIVITY_API_AND_DISPLAY', **observed}
    (receipt / 'receipt.json').write_text(json.dumps(saved, indent=2) + '\n')
    return {'ok': True, 'receipt': str(receipt)}

def receipt_data(repo, receipt, manifest):
    repo, receipt = Path(repo).resolve(strict=True), Path(receipt).resolve(strict=True)
    if receipt.parent != (repo / 'var/backups').resolve(strict=True) or not receipt.name.startswith('activity-dashboard-'):
        raise ValueError('Unexpected recovery receipt location')
    saved = json.loads((receipt / 'receipt.json').read_text())
    if saved['repo'] != str(repo) or saved['archive_sha256'] != manifest['archive_sha256'] or saved['files'] != manifest['files'] or set(saved['originals']) != SOURCE | {INDEX}:
        raise ValueError('Recovery receipt identity differs')
    return repo, receipt, saved

def rollback(repo, package, receipt):
    manifest, payload = read_package(package)
    repo, receipt, saved = receipt_data(repo, receipt, manifest)
    for name, old_hash in saved['originals'].items():
        target = safe_target(repo, name)
        actual = digest(target.read_bytes()) if target.exists() else None
        if actual not in {old_hash, manifest['files'][name]}:
            raise ValueError('Runtime source changed after receipt: ' + name)
        if old_hash is not None and digest((receipt / name).read_bytes()) != old_hash:
            raise ValueError('Backup checksum differs: ' + name)
    for name, old_hash in saved['originals'].items():
        target = safe_target(repo, name)
        if old_hash is None:
            target.unlink(missing_ok=True)
        else:
            atomic(target, (receipt / name).read_bytes())
    saved['state'] = 'rolled_back'
    atomic(receipt / 'receipt.json', (json.dumps(saved, indent=2) + '\n').encode())
    return {'ok': True, 'rolled_back': True, 'receipt': str(receipt)}

def apply(repo, package, receipt):
    manifest, payload = read_package(package)
    repo, receipt, saved = receipt_data(repo, receipt, manifest)
    validate_source(repo, manifest, payload)
    for name, old_hash in saved['originals'].items():
        target = safe_target(repo, name)
        if (digest(target.read_bytes()) if target.exists() else None) != old_hash:
            raise ValueError('Source changed since preflight: ' + name)
    try:
        for name, value in sorted(payload.items(), key=lambda item: item[0] == INDEX):
            target = safe_target(repo, name)
            target.parent.mkdir(exist_ok=True, parents=True)
            atomic(target, value)
        saved['state'] = 'applied'
        atomic(receipt / 'receipt.json', (json.dumps(saved, indent=2) + '\n').encode())
    except BaseException:
        rollback(repo, package, receipt)
        raise
    return {'ok': True, 'receipt': str(receipt), 'scope': saved['scope']}

def verify(repo, package, receipt, fetcher=fetch):
    manifest, payload = read_package(package)
    repo, receipt, saved = receipt_data(repo, receipt, manifest)
    health_identity(repo, fetcher)
    for name, value in payload.items():
        if safe_target(repo, name).read_bytes() != value:
            raise ValueError('Installed file differs: ' + name)
        if name.startswith('cc_web/dist/'):
            route = '/' if name == INDEX else '/' + name.removeprefix('cc_web/dist/')
            if fetcher(route) != value:
                raise ValueError('Served dashboard differs: ' + name)
    activity = json.loads(fetcher('/api/activity'))
    if activity.get('quote_max_age_seconds') != 60 or not isinstance(activity.get('bots'), list) or not isinstance(activity.get('summary'), dict):
        raise ValueError('Activity API verification failed')
    risk = json.loads(fetcher('/api/risk'))
    drawdown, exposure = risk.get('drawdown'), risk.get('exposure')
    if not isinstance(drawdown, dict) or not isinstance(exposure, dict):
        raise ValueError('Risk API verification failed')
    if drawdown.get('equity') is None and any(value is not None for value in
                                            (drawdown.get('dd'), exposure.get('ratio'), exposure.get('usd'))):
        raise ValueError('Unavailable valuation is still reported as measured risk')
    saved['state'] = 'verified'
    atomic(receipt / 'receipt.json', (json.dumps(saved, indent=2) + '\n').encode())
    return {'ok': True, 'scope': saved['scope'], 'receipt': str(receipt), 'activity': activity['summary'],
            'risk_reporting': {'drawdown': drawdown, 'exposure': exposure},
            'next_step': 'Press Ctrl+F5. Entry controls, positions and trading rules were not changed.'}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'apply', 'rollback', 'verify'))
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    package = Path(__file__).resolve().parent
    if args.action == 'prepare':
        result = prepare(args.repo, package)
    else:
        if args.receipt is None:
            parser.error('--receipt is required')
        result = globals()[args.action](args.repo, package, args.receipt)
    print(json.dumps(result))
