"""Read-only reporting deployment: preservation, rollback and failure guards."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import zipfile
import pytest

ROOT=Path(__file__).parent
spec=importlib.util.spec_from_file_location('activity_installer',ROOT/'INSTALL-ACTIVITY-DASHBOARD.py')
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)


def fixture(tmp_path):
    repo=tmp_path/'owner checkout';package=tmp_path/'package';repo.mkdir();package.mkdir()
    for folder in ('var/control','var/monitor','var/backups','cc_web/dist','cc_server/cc_server'):(repo/folder).mkdir(parents=True,exist_ok=True)
    (repo/'cc_server/cc_server/api.py').write_bytes(b'# original\r\n')
    (repo/installer.INDEX).write_bytes(b'old index')
    (repo/'var/control/sip_orb.pause').write_bytes(b'{"reason":"4 consecutive losses"}')
    c=sqlite3.connect(repo/'var/cc.db')
    c.executescript('CREATE TABLE bots(id TEXT, mode TEXT); INSERT INTO bots VALUES("spy_mr","paper"); CREATE TABLE positions(symbol TEXT,qty INTEGER); INSERT INTO positions VALUES("SPY",130),("QQQ call long",2),("QQQ call short",-2);'+''.join('CREATE TABLE '+name+'(id INTEGER); INSERT INTO '+name+' VALUES(1);' for name in ('orders','fills','trades','limits','controls')))
    c.commit();c.close()
    payload={'cc_server/cc_server/api.py':b'# new API\n','cc_server/cc_server/activity.py':b'# read only\n',installer.INDEX:b'new index','cc_web/dist/assets/activity.js':b'compiled activity'}
    manifest={'compatible':{'cc_server/cc_server/api.py':installer.normalized(b'# original\n'),'cc_server/cc_server/activity.py':None},'files':{k:installer.digest(v) for k,v in payload.items()}}
    write_package(package,manifest,payload)
    def fetcher(route):
        if route=='/api/health':return json.dumps({'ok':True,'db':str(repo/'var/cc.db')}).encode()
        if route=='/api/activity':return b'{"bots":[],"summary":{},"quote_max_age_seconds":60}'
        name=installer.INDEX if route=='/' else 'cc_web/dist'+route
        return (repo/name).read_bytes()
    return repo,package,payload,fetcher


def write_package(package,manifest,payload):
    with zipfile.ZipFile(package/'activity-dashboard.zip','w') as z:
        for k,v in payload.items():z.writestr(k,v)
    manifest['archive_sha256']=installer.digest((package/'activity-dashboard.zip').read_bytes())
    (package/'ACTIVITY-DASHBOARD.json').write_text(json.dumps(manifest))


def protected(repo):
    return {p.relative_to(repo).as_posix():p.read_bytes() for p in (repo/'var').rglob('*') if p.is_file() and 'backups' not in p.parts}


def test_installs_and_verifies_preserving_shares_options_and_flags(tmp_path):
    repo,package,payload,fetcher=fixture(tmp_path);before=protected(repo)
    result=installer.prepare(repo,package,fetcher)
    receipt=Path(result['receipt'])
    assert installer.apply(repo,package,receipt)['ok']
    assert installer.verify(repo,package,receipt,fetcher)['ok']
    assert protected(repo)==before
    assert all((repo/name).read_bytes()==value for name,value in payload.items())
    assert installer.rollback(repo,package,receipt)['ok']
    assert (repo/installer.INDEX).read_bytes()==b'old index'
    assert (repo/'cc_server/cc_server/api.py').read_bytes()==b'# original\r\n'
    assert not (repo/'cc_server/cc_server/activity.py').exists()
    assert protected(repo)==before


def test_refuses_unreviewed_source_before_runtime_changes(tmp_path):
    repo,package,payload,fetcher=fixture(tmp_path)
    (repo/'cc_server/cc_server/api.py').write_text('# owner edit\n')
    with pytest.raises(ValueError,match='source differs'):installer.prepare(repo,package,fetcher)
    assert (repo/installer.INDEX).read_bytes()==b'old index'


def test_wrong_server_identity_is_refused(tmp_path):
    repo,package,payload,fetcher=fixture(tmp_path)
    with pytest.raises(ValueError,match='ledger does not match'):installer.prepare(repo,package,lambda _:b'{"ok":true,"db":"/another/cc.db"}')


def test_partial_copy_failure_rolls_back_source_and_index(tmp_path,monkeypatch):
    repo,package,payload,fetcher=fixture(tmp_path);before=protected(repo)
    receipt=Path(installer.prepare(repo,package,fetcher)['receipt'])
    original=installer.atomic;failed=False
    def fail_once(path,value):
        nonlocal failed
        if path.name=='index.html' and not failed:
            failed=True;raise OSError('simulated disk error')
        return original(path,value)
    monkeypatch.setattr(installer,'atomic',fail_once)
    with pytest.raises(OSError,match='disk error'):installer.apply(repo,package,receipt)
    assert (repo/'cc_server/cc_server/api.py').read_bytes()==b'# original\r\n'
    assert (repo/installer.INDEX).read_bytes()==b'old index'
    assert protected(repo)==before


def test_stale_served_index_fails_verification_and_can_rollback(tmp_path):
    repo,package,payload,fetcher=fixture(tmp_path)
    receipt=Path(installer.prepare(repo,package,fetcher)['receipt']);installer.apply(repo,package,receipt)
    def stale(route):return b'old index' if route=='/' else fetcher(route)
    with pytest.raises(ValueError,match='Served dashboard differs'):installer.verify(repo,package,receipt,stale)
    installer.rollback(repo,package,receipt)
    assert (repo/installer.INDEX).read_bytes()==b'old index'


def test_corrupt_and_unsafe_package_refused(tmp_path):
    repo,package,payload,fetcher=fixture(tmp_path)
    manifest=json.loads((package/'ACTIVITY-DASHBOARD.json').read_text())
    payload['../escape']=b'bad';manifest['files']['../escape']=installer.digest(b'bad')
    write_package(package,manifest,payload)
    with pytest.raises(ValueError,match='Unsafe'):installer.prepare(repo,package,fetcher)


def test_local_change_after_preflight_is_not_overwritten(tmp_path):
    repo,package,payload,fetcher=fixture(tmp_path)
    receipt=Path(installer.prepare(repo,package,fetcher)['receipt'])
    (repo/installer.INDEX).write_text('owner changed index')
    with pytest.raises(ValueError,match='changed since preflight'):installer.apply(repo,package,receipt)
    assert (repo/installer.INDEX).read_text()=='owner changed index'


def test_rollback_refuses_altered_backup(tmp_path):
    repo,package,payload,fetcher=fixture(tmp_path)
    receipt=Path(installer.prepare(repo,package,fetcher)['receipt']);installer.apply(repo,package,receipt)
    (receipt/installer.INDEX).write_text('altered backup')
    with pytest.raises(ValueError,match='Backup checksum'):installer.rollback(repo,package,receipt)
    assert (repo/installer.INDEX).read_bytes()==payload[installer.INDEX]


def test_persistent_copy_and_rollback_failure_can_be_recovered_without_ledger_writes(tmp_path,monkeypatch):
    repo,package,payload,fetcher=fixture(tmp_path);before=protected(repo)
    receipt=Path(installer.prepare(repo,package,fetcher)['receipt'])
    original=installer.atomic
    def locked(path,value):
        if path.name=='index.html':raise OSError('persistent file lock')
        return original(path,value)
    monkeypatch.setattr(installer,'atomic',locked)
    with pytest.raises(OSError,match='persistent file lock'):installer.apply(repo,package,receipt)
    assert protected(repo)==before
    monkeypatch.setattr(installer,'atomic',original)
    assert installer.rollback(repo,package,receipt)['ok']
    assert (repo/installer.INDEX).read_bytes()==b'old index'
    assert (repo/'cc_server/cc_server/api.py').read_bytes()==b'# original\r\n'
