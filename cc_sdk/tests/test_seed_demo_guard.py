"""Guard tests never permit writes to a real repository's var tree."""
from pathlib import Path

import pytest

from scripts import seed_demo
from scripts.closed_loop_guard import SandboxError


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "var").mkdir(parents=True)
    monkeypatch.setattr(seed_demo, "ROOT", root)
    return root


@pytest.mark.parametrize("reset", [False, True])
def test_seed_refuses_unset_cc_var_before_any_database_write(fake_repo, monkeypatch, reset):
    monkeypatch.delenv("CC_VAR", raising=False)
    sentinel = fake_repo / "var/cc.db"
    sentinel.write_bytes(b"existing live record")
    # Pin the legacy default to a disposable fixture, even while testing the unsafe old behavior.
    monkeypatch.setattr(seed_demo, "db_path", lambda: sentinel)
    with pytest.raises(SandboxError):
        seed_demo.main(reset)
    assert sentinel.read_bytes() == b"existing live record"


def test_seed_reset_cannot_bypass_checkout_guard(fake_repo, monkeypatch):
    runtime = fake_repo / "var"
    monkeypatch.setenv("CC_VAR", str(runtime))
    sentinel = runtime / "cc.db"
    sentinel.write_bytes(b"existing live record")
    with pytest.raises(SandboxError):
        seed_demo.main(True)
    assert sentinel.read_bytes() == b"existing live record"


def test_external_demo_sandbox_is_allowed(fake_repo, tmp_path, monkeypatch):
    runtime = tmp_path / "demo" / "var"
    monkeypatch.setenv("CC_VAR", str(runtime))
    seed_demo.main(False)
    assert (runtime / "cc.db").is_file()
    assert not (fake_repo / "var/cc.db").exists()


def test_explicit_live_override_is_tested_only_on_a_disposable_fixture(fake_repo, monkeypatch):
    monkeypatch.setenv("CC_VAR", str(fake_repo / "var"))
    seed_demo.main(False, live_ledger=True)
    assert (fake_repo / "var/cc.db").is_file()


def test_seed_refuses_alias_into_checkout(fake_repo, tmp_path, monkeypatch):
    alias = tmp_path / "alias"
    alias.symlink_to(fake_repo / "var", target_is_directory=True)
    monkeypatch.setenv("CC_VAR", str(alias))
    with pytest.raises(SandboxError):
        seed_demo.main(True)
