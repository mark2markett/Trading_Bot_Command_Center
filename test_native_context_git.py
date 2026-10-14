"""Git installation boundaries exercised against real disposable repositories."""
import importlib.util
import subprocess
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('git_preflight', Path(__file__).with_name('NATIVE-CONTEXT-PREFLIGHT.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, 'init', '-b', 'feat/options-m7')
    git(tmp_path, 'config', 'user.name', 'Installer fixture')
    git(tmp_path, 'config', 'user.email', 'fixture@example.invalid')
    git(tmp_path, 'config', 'commit.gpgSign', 'false')
    git(tmp_path, 'config', 'core.autocrlf', 'false')
    for name in ['README.md', 'cc_sdk/cc_sdk/intraday.py', 'bots/spy_mr_bot/bot.log', 'scripts/dev.sh']:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('synthetic original\n')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-m', 'synthetic baseline')
    return tmp_path


def test_clean_git_checkout_is_ready(repo):
    assert module.check_git(repo)['ok'] is True


@pytest.mark.parametrize('target', ['README.md', 'cc_sdk/cc_sdk/intraday.py', 'cc_sdk/tests/test_daily_context_health.py'])
def test_changed_repair_target_is_refused_and_preserved(repo, target):
    path = repo / target
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'local edit must survive\n')
    before = git(repo, 'status', '--porcelain', '-z').stdout
    with pytest.raises(ValueError):
        module.check_git(repo)
    assert path.read_bytes() == b'local edit must survive\n'
    assert git(repo, 'status', '--porcelain', '-z').stdout == before


def reported_local_changes(repo):
    files = {
        'bots/spy_mr_bot/bot.log': b'new native runtime log\n',
        'scripts/dev.sh': b'local dev change\n',
        'docs/handoffs/CODEX-CLOSED-LOOP-TEST-PROMPT-2026-10-04.md': b'owner handoff\n',
    }
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return files


def test_owner_reported_unrelated_changes_are_allowed_without_modification(repo):
    files = reported_local_changes(repo)
    before = git(repo, 'status', '--porcelain', '-z').stdout
    assert module.check_git(repo)['ok'] is True
    assert git(repo, 'status', '--porcelain', '-z').stdout == before
    assert all((repo / name).read_bytes() == data for name, data in files.items())


def test_real_cherry_pick_preserves_reported_unrelated_edits(repo):
    git(repo, 'switch', '-c', 'fixture/context-repair')
    (repo / 'README.md').write_text('reviewed repair description\n')
    (repo / 'cc_sdk/cc_sdk/intraday.py').write_text('reviewed synthetic context repair\n')
    test = repo / 'cc_sdk/tests/test_daily_context_health.py'
    test.parent.mkdir(parents=True)
    test.write_text('synthetic regression file\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'reviewed synthetic three-file repair')
    repair = git(repo, 'rev-parse', 'HEAD').stdout.decode().strip()
    git(repo, 'switch', 'feat/options-m7')
    files = reported_local_changes(repo)
    assert module.check_git(repo)['ok'] is True
    git(repo, 'cherry-pick', repair)
    assert git(repo, 'branch', '--show-current').stdout.strip() == b'feat/options-m7'
    assert all((repo / name).read_bytes() == data for name, data in files.items())
    assert git(repo, 'diff', '--cached', '--name-only').stdout == b''
    committed = set(git(repo, 'diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD').stdout.decode().splitlines())
    assert committed == {'README.md', 'cc_sdk/cc_sdk/intraday.py', 'cc_sdk/tests/test_daily_context_health.py'}


def test_staged_unrelated_edits_are_refused_and_preserved(repo):
    reported_local_changes(repo)
    git(repo, 'add', 'scripts/dev.sh')
    before = git(repo, 'diff', '--cached', '--binary').stdout
    with pytest.raises(ValueError):
        module.check_git(repo)
    assert git(repo, 'diff', '--cached', '--binary').stdout == before


def test_git_only_cli_accepts_unrelated_edits_without_a_trading_ledger(repo):
    import json
    import sys
    files = reported_local_changes(repo)
    result = subprocess.run([sys.executable, str(Path(module.__file__)), str(repo), '--git-only'],
                            check=True, capture_output=True)
    assert json.loads(result.stdout)['ok'] is True
    assert not (repo / 'var').exists()
    assert all((repo / name).read_bytes() == data for name, data in files.items())


def test_git_inspection_failure_is_not_healthy(tmp_path):
    with pytest.raises(ValueError, match='Could not inspect'):
        module.check_git(tmp_path)


def test_ignored_untracked_repair_target_is_refused_and_preserved(repo):
    target = repo / 'cc_sdk/tests/test_daily_context_health.py'
    target.parent.mkdir(parents=True)
    target.write_bytes(b'ignored owner regression work must survive\n')
    (repo / '.git/info/exclude').write_text('cc_sdk/tests/test_daily_context_health.py\n')
    assert git(repo, 'status', '--porcelain', '--', str(target)).stdout == b''
    with pytest.raises(ValueError, match='repair target'):
        module.check_git(repo)
    assert target.read_bytes() == b'ignored owner regression work must survive\n'
