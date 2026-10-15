"""Rehearse the actual bundle and owner-file preservation in isolated Git repos."""
import importlib.util
import json
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location('oct14_release_gate', HERE / 'NATIVE-OCT14-PREFLIGHT.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
AFTER = datetime(2026, 10, 14, 17, tzinfo=ZoneInfo('America/New_York'))
NATIVE = Path('/workspace/scratch/cc-dashboard-wrap-20261007')


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, text=True, capture_output=True).stdout.strip()


@pytest.mark.parametrize('pending_order', [False, True])
@pytest.mark.parametrize('context_installed', [False, True])
def test_actual_bundle_preserves_owner_files_and_is_idempotent(tmp_path, monkeypatch, context_installed, pending_order):
    if not NATIVE.is_dir():
        pytest.skip('Cloud source checkout is required for this local bundle rehearsal')
    monkeypatch.delenv('CC_VAR', raising=False)
    root = tmp_path / 'repo'
    git(tmp_path, 'clone', '--no-hardlinks', '--no-checkout', str(NATIVE), str(root))
    git(root, 'config', 'user.email', 'release-test@example.invalid')
    git(root, 'config', 'user.name', 'Isolated release rehearsal')
    release = json.loads((HERE / 'OCT14-NATIVE-SOURCE.json').read_text())
    git(root, 'checkout', '-b', 'feat/options-m7', release['base'])
    if context_installed:
        git(root, 'cherry-pick', release['context'])
    owner = {
        'bots/spy_mr_bot/bot.log': b'owner log history\n',
        'scripts/dev.sh': b'#!/bin/bash\n# owner local launcher\n',
        'docs/handoffs/CODEX-CLOSED-LOOP-TEST-PROMPT-2026-10-04.md': b'owner handoff\n',
    }
    for path, value in owner.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(value)
    var = root / 'var'
    var.mkdir(exist_ok=True)
    with sqlite3.connect(var / 'cc.db') as db:
        db.executescript('CREATE TABLE bots(id TEXT, mode TEXT); CREATE TABLE positions(qty INTEGER); CREATE TABLE orders(id INTEGER PRIMARY KEY,bot_id TEXT,at TEXT,broker_order_id TEXT,side TEXT,qty INTEGER,type TEXT,status TEXT,symbol TEXT,ref_price REAL); CREATE TABLE fills(order_id INTEGER);')
        db.executemany('INSERT INTO bots VALUES (?,?)', [(bot, 'paper') for bot in gate.BOTS])
    daily_files = []
    if pending_order:
        from test_native_oct14_preflight import pending_daily
        folder = pending_daily(root)
        daily_files = [folder / 'state_paper.json', folder / 'paper_ledger.json']
    daily_before = [p.read_bytes() for p in daily_files]
    runtime_before = gate.check(root, AFTER)['runtime_fingerprint']
    ledger = (var / 'cc.db').read_bytes()
    assert gate.check_git(root)['ok']
    assert gate.check(root, AFTER)['source'] == ('context' if context_installed else 'original')
    git(root, 'bundle', 'verify', str(HERE / 'command-center-oct14-native.bundle'))
    git(root, 'fetch', str(HERE / 'command-center-oct14-native.bundle'), 'fix/atomic-paper-entry-20261014:refs/test/oct14')
    for _ in range(2):
        for commit in (release['context'], release['tip']):
            parent = git(root, 'rev-parse', commit + '^')
            if git(root, 'cherry', 'HEAD', commit, parent).startswith('+ '):
                git(root, 'cherry-pick', commit)
        assert gate.check(root, AFTER)['source'] == 'installed'
        assert git(root, 'branch', '--show-current') == 'feat/options-m7'
        assert not git(root, 'diff', '--cached', '--name-only')
        assert all((root / path).read_bytes() == value for path, value in owner.items())
        assert (var / 'cc.db').read_bytes() == ledger
        assert [p.read_bytes() for p in daily_files] == daily_before
        assert gate.check(root, AFTER)['runtime_fingerprint'] == runtime_before


def test_power_shell_guards_and_staging_precede_mutation():
    source = (HERE / 'APPLY-OCT14-NATIVE-FIXES.ps1').read_text()
    mutation = source.index('cherry-pick $fix')
    assert source.index('-m pytest -q') < source.index('Consistent ledger backup failed') < mutation
    assert source.index('Stop-ScheduledTask') < mutation < source.index('Assert-Preflight -RequireInstalled')
    assert source.count('Assert-Preflight\n') >= 3
    assert 'Stop-Process' not in source
    assert 'git reset' not in source


def test_windows_guards_pin_server_interpreter_and_block_every_bot_command():
    source = (HERE / 'APPLY-OCT14-NATIVE-FIXES.ps1').read_text()
    before_stop = source[:source.index('Stop-ScheduledTask')]
    assert 'Actions[0].Execute' in before_stop
    assert 'serverExecute -ne $python' in before_stop
    assert "'bot\\.py\\b'" in before_stop
    assert "'^CC bot\\b'" in before_stop
    assert 'session|decide|reconcile' not in before_stop


@pytest.mark.parametrize("manifest", ["OCT14-NATIVE-SHA256.txt", "SHA256.txt"])
def test_windows_autocrlf_checkout_preserves_checksummed_native_payload(tmp_path, manifest):
    import shutil
    source = tmp_path / 'transfer-source'
    source.mkdir()
    names = [line.split(None, 1)[1].lstrip('*') for line in (HERE / manifest).read_text().splitlines() if line.strip()]
    for name in [*names, '.gitattributes']:
        shutil.copyfile(HERE / name, source / name)
    git(source, 'init')
    git(source, 'config', 'core.autocrlf', 'false')
    git(source, 'config', 'user.name', 'Release rehearsal')
    git(source, 'config', 'user.email', 'release@example.invalid')
    git(source, 'add', '.')
    git(source, 'commit', '-m', 'Actual release payload')
    checkout = tmp_path / 'windows-checkout'
    git(tmp_path, '-c', 'core.autocrlf=true', 'clone', '--no-hardlinks', str(source), str(checkout))
    altered = [name for name in names if (checkout / name).read_bytes() != (HERE / name).read_bytes()]
    assert not altered, f'Windows checkout changes checksummed release bytes: {altered}'
