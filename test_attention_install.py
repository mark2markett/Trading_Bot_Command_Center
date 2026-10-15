"""Installer contract checks; Windows mutation is exercised separately with fake tasks."""
import importlib.util
import json
from pathlib import Path
import subprocess
import pytest
ROOT=Path(__file__).parent

def load():
    p=ROOT/'ATTENTION-PREFLIGHT.py'
    if not p.exists(): pytest.fail('Attention installation preflight is not implemented')
    spec=importlib.util.spec_from_file_location('attention_preflight',p)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

def test_preflight_refuses_wrong_source_without_creating_ledger(tmp_path):
    m=load()
    with pytest.raises(ValueError): m.check(tmp_path)
    assert not (tmp_path/'var'/'cc.db').exists()

def test_installer_has_observation_and_guarded_activation_and_rollback():
    p=ROOT/'INSTALL-ATTENTION-HANDLING.ps1'
    assert p.exists(), 'Guarded attention installer is not implemented'
    text=p.read_text()
    assert 'Assert-Preflight' in text and 'Invoke-StagedNativeTests' in text
    assert 'Rollback' in text and 'Export-ScheduledTask' in text
    assert 'Stop-Process' not in text and 'git reset' not in text

def test_monitor_no_longer_starts_server_outside_durable_worker():
    text=(ROOT/'CC-MONITOR.ps1').read_text()
    assert 'Start-ScheduledTask' not in text
    assert 'CC-MONITOR.py' in text

def test_installer_one_minute_cadence_and_preserves_interactive_notice():
    text=(ROOT/'INSTALL-CC-MONITOR.ps1').read_text()
    assert '-Minutes 1' in text and "'Interactive'" in text
    assert 'Observation' in text

def package():
    p=ROOT/'ATTENTION-PACKAGE.py'
    if not p.exists(): pytest.fail('Package integrity helper is not implemented')
    spec=importlib.util.spec_from_file_location('attention_package',p)
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def test_dashboard_extract_rejects_path_escape_before_writing(tmp_path):
    import zipfile
    m=package(); archive=tmp_path/'ui.zip'
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('index.html','ok'); z.writestr('../escape','bad')
    with pytest.raises(ValueError): m.extract(archive,tmp_path/'dist')
    assert not (tmp_path/'dist').exists() and not (tmp_path/'escape').exists()

def test_consistent_backup_preserves_source_and_copies_operations(tmp_path):
    import sqlite3
    m=package(); runtime=tmp_path/'var'; runtime.mkdir(); (runtime/'monitor').mkdir()
    for p in (runtime/'cc.db',runtime/'monitor'/'incidents.db'):
        with sqlite3.connect(p) as db: db.execute('CREATE TABLE proof(value)'); db.execute("INSERT INTO proof VALUES('kept')")
    m.backup(runtime,tmp_path/'backup')
    for name in ('cc.db','incidents.db'):
        with sqlite3.connect(tmp_path/'backup'/name) as db: assert db.execute('SELECT value FROM proof').fetchone()[0]=='kept'

def test_rollback_metadata_is_written_before_any_source_change():
    text=(ROOT/'INSTALL-ATTENTION-HANDLING.ps1').read_text()
    before=text.index('git -c gc.auto=0 cherry-pick $commit')
    assert 'Save-AttentionReceipt' in text[:before], 'A valid receipt must exist before cherry-pick'
    assert 'pending_commit' in (ROOT/'ATTENTION-RECEIPT.ps1').read_text(), 'Crash recovery must identify the in-flight commit'

def test_rollback_allows_owned_stopped_server_and_partial_source():
    text=(ROOT/'INSTALL-ATTENTION-HANDLING.ps1').read_text()
    rollback=text.index('    if ($Rollback) {')
    assert "$server.State -ne 'Running'" not in text[:rollback], 'Rollback cannot depend on a working installed server'
    assert "@('installed','step_" in text or "-notlike 'step_*'" in text, 'Known partial source stages must allow rollback'
