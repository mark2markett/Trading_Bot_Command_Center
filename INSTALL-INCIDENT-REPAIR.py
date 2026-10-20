"""Guarded operations-only source repair; never writes the trading or incident ledger."""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import sys
import tempfile
import uuid
import zipfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('reviewed_activity_helpers', ROOT / 'INSTALL-ACTIVITY-DASHBOARD.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
SOURCE = {f'cc_server/cc_server/incidents/{name}.py' for name in
          ('__init__', 'models', 'store', 'observe', 'classify', 'readback')}
SCOPE = 'INCIDENT_MONITOR_ONLY'


def read_package(package):
    manifest = json.loads((package / 'INCIDENT-REPAIR.json').read_text())
    archive = package / 'incident-repair.zip'
    if base.digest(archive.read_bytes()) != manifest['archive_sha256']:
        raise ValueError('Incident archive checksum mismatch')
    payload = {}
    with zipfile.ZipFile(archive) as zipped:
        if len(zipped.infolist()) != len(SOURCE) or sum(i.file_size for i in zipped.infolist()) > 200_000:
            raise ValueError('Unsafe incident archive size')
        for item in zipped.infolist():
            if item.filename not in SOURCE or item.is_dir() or item.filename in payload:
                raise ValueError('Unsafe incident archive path')
            value = zipped.read(item)
            if base.digest(value) != manifest['files'].get(item.filename):
                raise ValueError('Incident source checksum differs')
            compile(value, item.filename, 'exec')
            payload[item.filename] = value
    if set(payload) != SOURCE or set(manifest['compatible']) != SOURCE or set(manifest['files']) != SOURCE:
        raise ValueError('Incident manifest files differ')
    return manifest, payload


def recovery_probe(payload):
    """Exercise the actual candidate modules against a disposable operations database."""
    prefix = 'incident_probe_' + uuid.uuid4().hex
    try:
        with tempfile.TemporaryDirectory(prefix='cc-incident-probe-') as directory:
            root = Path(directory)
            package = root / prefix
            package.mkdir()
            for name, value in payload.items():
                (package / Path(name).name).write_bytes(value)
            sys.path.insert(0, str(root))
            store_module = importlib.import_module(prefix + '.store')
            models = importlib.import_module(prefix + '.models')
            classify = importlib.import_module(prefix + '.classify')
            at = datetime(2026, 10, 15, 14, tzinfo=UTC)
            failure = models.Observation('valuation', 'fleet', '2026-10-15', 'page', 'failing', at.isoformat())
            with store_module.IncidentStore(root / 'probe.db') as store:
                incident = store.observe(failure, 'failed')
                for n, verdict in enumerate(('healthy', 'failing', 'healthy', 'healthy')):
                    store.observe(replace(failure, session_date='2026-10-19', verdict=verdict,
                                          at=(at + timedelta(days=4, seconds=n + 1)).isoformat()), str(n))
                    expected = 'resolved' if n == 3 else 'checking'
                    if store.get(incident)['state'] != expected:
                        raise ValueError('Incident recovery probe failed')
            alert = classify.classify_alert({'id': 34, 'at': at.isoformat(), 'kind': 'run_failed',
                                             'bot_id': 'spy_mr', 'severity': 'digest'}, historical=True)
            if alert.condition != 'run_failed':
                raise ValueError('Incident classification probe failed')
    finally:
        if 'root' in locals() and str(root) in sys.path:
            sys.path.remove(str(root))
        for name in list(sys.modules):
            if name == prefix or name.startswith(prefix + '.'):
                del sys.modules[name]


def prepare(repo, package, fetcher=base.fetch):
    repo = Path(repo).resolve(strict=True)
    manifest, payload = read_package(package)
    base.health_identity(repo, fetcher)
    observed = base.evidence(repo)
    originals = {}
    for name in SOURCE:
        value = base.safe_target(repo, name).read_bytes()
        if base.normalized(value) not in {manifest['compatible'][name], base.normalized(payload[name])}:
            raise ValueError('Installed source differs from reviewed version: ' + name)
        originals[name] = base.digest(value)
    recovery_probe(payload)
    parent = base.safe_target(repo, 'var/backups/.incident-path-check').parent
    parent.mkdir(exist_ok=True)
    receipt = parent / ('incident-repair-' + uuid.uuid4().hex)
    receipt.mkdir()
    for name in SOURCE:
        value = base.safe_target(repo, name).read_bytes()
        if base.digest(value) != originals[name]:
            raise ValueError('Source changed since preflight: ' + name)
        target = receipt / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(value)
    saved = {'repo': str(repo), 'scope': SCOPE, 'originals': originals,
             'archive_sha256': manifest['archive_sha256'], 'files': manifest['files'],
             'state': 'prepared', **observed}
    base.atomic(receipt / 'receipt.json', (json.dumps(saved, indent=2) + '\n').encode())
    return {'ok': True, 'receipt': str(receipt), 'scope': SCOPE}


def receipt_data(repo, receipt, manifest):
    repo, receipt = Path(repo).resolve(strict=True), Path(receipt).resolve(strict=True)
    if receipt.parent != (repo / 'var/backups').resolve(strict=True) or not receipt.name.startswith('incident-repair-'):
        raise ValueError('Unexpected recovery receipt location')
    saved = json.loads(base.safe_target(repo, (receipt / 'receipt.json').relative_to(repo).as_posix()).read_text())
    if (saved['repo'] != str(repo) or saved['archive_sha256'] != manifest['archive_sha256']
            or saved['files'] != manifest['files'] or set(saved['originals']) != SOURCE):
        raise ValueError('Recovery receipt identity differs')
    return repo, receipt, saved


def rollback(repo, package, receipt):
    manifest, _payload = read_package(package)
    repo, receipt, saved = receipt_data(repo, receipt, manifest)
    originals = {}
    for name in SOURCE:
        target = base.safe_target(repo, name)
        if base.digest(target.read_bytes()) not in {saved['originals'][name], manifest['files'][name]}:
            raise ValueError('Runtime source changed after receipt: ' + name)
        backup = base.safe_target(repo, (receipt / name).relative_to(repo).as_posix()).read_bytes()
        if base.digest(backup) != saved['originals'][name]:
            raise ValueError('Backup checksum differs: ' + name)
        originals[name] = backup
    for name, value in originals.items():
        base.atomic(base.safe_target(repo, name), value)
    saved['state'] = 'rolled_back'
    base.atomic(receipt / 'receipt.json', (json.dumps(saved, indent=2) + '\n').encode())
    return {'ok': True, 'rolled_back': True, 'receipt': str(receipt)}


def apply(repo, package, receipt):
    manifest, payload = read_package(package)
    repo, receipt, saved = receipt_data(repo, receipt, manifest)
    for name in SOURCE:
        if base.digest(base.safe_target(repo, name).read_bytes()) != saved['originals'][name]:
            raise ValueError('Source changed since preflight: ' + name)
    try:
        for name, value in payload.items():
            base.atomic(base.safe_target(repo, name), value)
        saved['state'] = 'applied'
        base.atomic(receipt / 'receipt.json', (json.dumps(saved, indent=2) + '\n').encode())
    except BaseException:
        rollback(repo, package, receipt)
        raise
    return {'ok': True, 'scope': SCOPE, 'receipt': str(receipt)}


def verify(repo, package, receipt, fetcher=base.fetch):
    manifest, payload = read_package(package)
    repo, receipt, saved = receipt_data(repo, receipt, manifest)
    base.health_identity(repo, fetcher)
    for name, value in payload.items():
        if base.safe_target(repo, name).read_bytes() != value:
            raise ValueError('Installed incident source differs: ' + name)
    report = json.loads(fetcher('/api/incidents?limit=1'))
    monitor = report.get('monitor')
    count = report.get('open_count')
    if monitor is None or count is None:
        raise ValueError('Incident API verification failed')
    if not isinstance(monitor, dict) or type(count) is not int:
        raise TypeError('Incident API returned invalid types')
    saved['state'] = 'verified'
    base.atomic(receipt / 'receipt.json', (json.dumps(saved, indent=2) + '\n').encode())
    return {'ok': True, 'scope': SCOPE, 'receipt': str(receipt), 'monitor': report['monitor'],
            'open_count': report['open_count'], 'next_step': 'The next two healthy minute checks resolve recovered valuation alerts; historical failed runs remain for review.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'apply', 'rollback', 'verify'))
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    if args.action == 'prepare':
        result = prepare(args.repo, ROOT)
    elif args.receipt is None:
        parser.error('--receipt is required')
    else:
        result = globals()[args.action](args.repo, ROOT, args.receipt)
    print(json.dumps(result))
