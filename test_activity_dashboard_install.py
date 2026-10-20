"""Read-only reporting deployment: preservation, rollback and failure guards."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import zipfile
import pytest

ROOT=Path(__file__).parent
spec=importlib.util.spec_from_file_location('activity_installer',ROOT/'INSTALL-ACTIVITY-DASHBOARD.py')
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)


def fixture(tmp_path):
    repo=tmp_path/'owner checkout';package=tmp_path/'package';repo.mkdir();package.mkdir()
    for folder in ('var/control','var/monitor','var/backups','cc_web/dist','cc_server/cc_server','cc_sdk/cc_sdk'):(repo/folder).mkdir(parents=True,exist_ok=True)
    (repo/'cc_server/cc_server/api.py').write_bytes(b'# original\r\n')
    (repo/'cc_server/cc_server/riskd.py').write_bytes(b'# prior account monitor\n')
    (repo/'cc_sdk/cc_sdk/polygon_options.py').write_bytes(b'# prior Polygon parser\n')
    (repo/installer.INDEX).write_bytes(b'old index')
    (repo/'var/control/sip_orb.pause').write_bytes(b'{"reason":"4 consecutive losses"}')
    c=sqlite3.connect(repo/'var/cc.db')
    c.executescript('CREATE TABLE bots(id TEXT, mode TEXT); INSERT INTO bots VALUES("spy_mr","paper"); CREATE TABLE positions(symbol TEXT,qty INTEGER); INSERT INTO positions VALUES("SPY",130),("QQQ call long",2),("QQQ call short",-2);'+''.join('CREATE TABLE '+name+'(id INTEGER); INSERT INTO '+name+' VALUES(1);' for name in ('orders','fills','trades','limits','controls')))
    c.commit();c.close()
    payload={'cc_server/cc_server/api.py':b'# new API\n','cc_server/cc_server/activity.py':b'# read only\n','cc_server/cc_server/risk_reporting.py':b'# unknown valuation is not zero risk\n',installer.INDEX:b'new index','cc_web/dist/assets/activity.js':b'compiled activity'}
    payload.update({'cc_server/cc_server/riskd.py':b'# account provider routing\n',
                    'cc_server/cc_server/account_quotes.py':b'# strict Polygon account books\n',
                    'cc_sdk/cc_sdk/intraday.py':b'# honor exit refusal\n', 'cc_sdk/cc_sdk/options_runner.py':b'# honor spread exit refusal\n',
                    'cc_sdk/cc_sdk/control.py':b'# options only control\n', 'cc_sdk/cc_sdk/risk.py':b'# options only risk guard\n',
                    'cc_sdk/cc_sdk/polygon_options.py':b'# no manufactured bid\n'})
    manifest={'entry_asset_policy':'options_only','compatible':{'cc_server/cc_server/api.py':installer.normalized(b'# original\n'),'cc_server/cc_server/activity.py':None,'cc_server/cc_server/risk_reporting.py':None},'files':{k:installer.digest(v) for k,v in payload.items()}}
    manifest['compatible'].update({'cc_server/cc_server/riskd.py':installer.normalized(b'# prior account monitor\n'),
                                   'cc_server/cc_server/account_quotes.py':None, 'cc_sdk/cc_sdk/control.py':None, 'cc_sdk/cc_sdk/risk.py':None,
                                   'cc_sdk/cc_sdk/intraday.py':None, 'cc_sdk/cc_sdk/options_runner.py':None,
                                   'cc_sdk/cc_sdk/polygon_options.py':installer.normalized(b'# prior Polygon parser\n')})
    write_package(package,manifest,payload)
    def fetcher(route):
        if route=='/api/health':return json.dumps({'ok':True,'db':str(repo/'var/cc.db')}).encode()
        if route=='/api/activity':return b'{"bots":[],"summary":{},"quote_max_age_seconds":60}'
        if route=='/api/risk':return b'{"drawdown":{"equity":null,"dd":null},"exposure":{"usd":null,"ratio":null}}'
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
    assert not (repo/'cc_server/cc_server/risk_reporting.py').exists()
    assert not (repo/'cc_server/cc_server/account_quotes.py').exists()
    assert (repo/'cc_server/cc_server/riskd.py').read_bytes()==b'# prior account monitor\n'
    assert (repo/'cc_sdk/cc_sdk/polygon_options.py').read_bytes()==b'# prior Polygon parser\n'
    assert protected(repo)==before


@pytest.mark.parametrize('name',['cc_server/cc_server/riskd.py','cc_sdk/cc_sdk/polygon_options.py'])
def test_quote_source_update_preserves_owner_dependency_changes(tmp_path,name):
    repo,package,payload,fetcher=fixture(tmp_path)
    owner=b'# owner data source change\n';(repo/name).write_bytes(owner)
    with pytest.raises(ValueError,match='source differs'):
        installer.prepare(repo,package,fetcher)
    assert (repo/name).read_bytes()==owner
    assert (repo/installer.INDEX).read_bytes()==b'old index'


def test_actual_quote_source_package_installs_and_rolls_back_on_previous_release(tmp_path):
    repo,_,_,fetcher=fixture(tmp_path)
    manifest,payload=installer.read_package(ROOT)
    source=tmp_path/'reviewed source'
    subprocess.run(['git','clone','--no-checkout',str(ROOT/'activity-dashboard-source.bundle'),str(source)],
                   check=True,capture_output=True)
    for name in manifest['compatible']:
        result=subprocess.run(['git','show',manifest['compatible_base']+':'+name],cwd=source,capture_output=True)
        target=repo/name
        if result.returncode==0:
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(result.stdout)
        else:
            assert manifest['compatible'][name] is None
            target.unlink(missing_ok=True)
    originals={name:(repo/name).read_bytes() if (repo/name).exists() else None for name in installer.SOURCE}
    before=protected(repo)
    receipt=Path(installer.prepare(repo,ROOT,fetcher)['receipt'])
    assert installer.apply(repo,ROOT,receipt)['ok']
    assert installer.verify(repo,ROOT,receipt,fetcher)['ok']
    assert all((repo/name).read_bytes()==value for name,value in payload.items())
    assert protected(repo)==before
    assert installer.rollback(repo,ROOT,receipt)['ok']
    assert all(((repo/name).read_bytes() if (repo/name).exists() else None)==value for name,value in originals.items())
    assert protected(repo)==before


def test_refuses_unreviewed_source_before_runtime_changes(tmp_path):
    repo,package,payload,fetcher=fixture(tmp_path)
    (repo/'cc_server/cc_server/api.py').write_text('# owner edit\n')
    with pytest.raises(ValueError,match='source differs'):installer.prepare(repo,package,fetcher)
    assert (repo/installer.INDEX).read_bytes()==b'old index'


def test_new_reporting_module_never_overwrites_owner_content(tmp_path):
    repo,package,payload,fetcher=fixture(tmp_path)
    module=repo/'cc_server/cc_server/risk_reporting.py'
    module.write_text('# owner module\n')
    with pytest.raises(ValueError,match='source differs'):installer.prepare(repo,package,fetcher)
    assert module.read_text()=='# owner module\n'


def test_missing_source_compatibility_entry_is_refused(tmp_path):
    repo,package,payload,fetcher=fixture(tmp_path)
    manifest=json.loads((package/'ACTIVITY-DASHBOARD.json').read_text())
    del manifest['compatible']['cc_server/cc_server/risk_reporting.py']
    write_package(package,manifest,payload)
    with pytest.raises(ValueError,match='compatibility'):installer.prepare(repo,package,fetcher)


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


def test_unavailable_risk_cannot_be_verified_as_a_measured_zero(tmp_path):
    repo,package,payload,fetcher=fixture(tmp_path)
    receipt=Path(installer.prepare(repo,package,fetcher)['receipt']);installer.apply(repo,package,receipt)
    def misleading(route):
        return b'{"drawdown":{"equity":null,"dd":0},"exposure":{"usd":100048,"ratio":0}}' if route=='/api/risk' else fetcher(route)
    with pytest.raises(ValueError,match='Unavailable valuation'):installer.verify(repo,package,receipt,misleading)


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
