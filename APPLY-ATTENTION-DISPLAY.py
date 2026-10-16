"""Atomic display-only update. No bot source, database, task or control writes.

Old assets stay available to already-open browser tabs. A failed served-content
check restores the previous index. This does not install the incident worker.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import urllib.request
import uuid
import zipfile
from pathlib import Path, PurePosixPath


def fetch_local(path):
    with urllib.request.urlopen('http://127.0.0.1:8585' + path, timeout=10) as response:
        return response.read(20_000_001)


def atomic_write(path, value):
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.display-', delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(value)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def install(repo, package, *, fetch=fetch_local):
    repo, package = Path(repo).resolve(strict=True), Path(package).resolve(strict=True)
    health = json.loads(fetch('/api/health'))
    expected_db = repo / 'var' / 'cc.db'
    if health.get('ok') is not True or os.path.normcase(str(Path(health.get('db', '')).resolve())) != os.path.normcase(str(expected_db)):
        raise ValueError('Running server does not match this repository')
    archive = package / 'attention-dashboard.zip'
    rows = [line.split() for line in (package / 'ATTENTION-SHA256.txt').read_text().splitlines() if line.strip()]
    hashes = [r[0] for r in rows if len(r) == 2 and r[1].lstrip('*') == archive.name]
    if len(hashes) != 1 or hashlib.sha256(archive.read_bytes()).hexdigest() != hashes[0]:
        raise ValueError('Dashboard checksum mismatch')
    with zipfile.ZipFile(archive) as z:
        if len(z.infolist()) > 1000 or sum(i.file_size for i in z.infolist()) > 20_000_000:
            raise ValueError('Dashboard archive exceeds limit')
        payload = {}
        for info in z.infolist():
            p = PurePosixPath(info.filename)
            if (info.is_dir() or p.is_absolute() or '..' in p.parts or '\\' in info.filename or ':' in info.filename
                    or info.filename in payload or str(p) != info.filename
                    or not (info.filename in ('index.html', 'favicon.svg', 'icons.svg') or p.parts[0] == 'assets')):
                raise ValueError('Unsafe dashboard archive path')
            payload[info.filename] = z.read(info)
    if 'index.html' not in payload:
        raise ValueError('Dashboard index missing')
    dist = repo / 'cc_web' / 'dist'
    index = dist / 'index.html'
    if not index.is_file() or dist.is_symlink() or (repo / 'cc_web').is_symlink():
        raise ValueError('Existing dashboard directory required')
    for name, value in payload.items():
        target = dist / name
        if target.is_symlink() or any(p.is_symlink() for p in target.parents if p != dist and dist in p.parents):
            raise ValueError('Dashboard target is a symbolic link')
        if name != 'index.html' and target.exists() and target.read_bytes() != value:
            raise ValueError('Existing asset collision; no file replaced')
    backups = repo / 'var' / 'backups'
    backups.mkdir(exist_ok=True)
    lock = backups / '.attention-display.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    previous, changed = None, False
    try:
        previous = index.read_bytes()
        receipt = backups / ('attention-display-' + uuid.uuid4().hex)
        receipt.mkdir()
        (receipt / 'index.html').write_bytes(previous)
        (receipt / 'receipt.json').write_text(json.dumps({'scope': 'DISPLAY_ONLY', 'old_sha256': hashlib.sha256(previous).hexdigest(),
                                                        'new_sha256': hashlib.sha256(payload['index.html']).hexdigest()}) + '\n')
        for name, value in payload.items():
            if name == 'index.html':
                continue
            target = dist / name
            target.parent.mkdir(exist_ok=True, parents=True)
            if not target.exists():
                atomic_write(target, value)
            elif target.read_bytes() != value:
                raise ValueError('Existing asset collision; no file replaced')
        atomic_write(index, payload['index.html'])
        changed = True
        for name, value in payload.items():
            if fetch('/' if name == 'index.html' else '/' + name) != value:
                raise ValueError('Server has not served the expected display assets')
        return {'ok': True, 'scope': 'DISPLAY_ONLY', 'already_installed': previous == payload['index.html'],
                'receipt': str(receipt), 'incident_worker_installed': False,
                'next_step': 'Refresh with Ctrl+F5. Monitor unavailable means the full runtime repair is not installed.'}
    except BaseException:
        if changed and index.read_bytes() == payload['index.html']:
            atomic_write(index, previous)
        raise
    finally:
        lock.unlink()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(install(args.repo, Path(__file__).parent)))
