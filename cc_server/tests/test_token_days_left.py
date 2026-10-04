"""riskd.token_days_left must work from the `.issued` sidecar alone (broker design, M6.8): no token file on disk."""
import json
import time

from cc_server import riskd


def test_sidecar_only_reports_present_and_days_left(tmp_path, monkeypatch):
    monkeypatch.setenv("CC_VAR", str(tmp_path))
    (tmp_path / "schwab_token.json.issued").write_text(json.dumps({"creation_timestamp": int(time.time()) - 86400}))
    out = riskd.token_days_left(bots_dir=tmp_path / "bots")
    assert out["present"] is True
    assert 5.9 <= out["days_left"] <= 6.0
    assert not (tmp_path / "schwab_token.json").exists()


def test_nothing_on_disk_is_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("CC_VAR", str(tmp_path))
    assert riskd.token_days_left(bots_dir=tmp_path / "bots") == {"present": False, "days_left": None}


def test_corrupt_sidecar_without_token_file_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv("CC_VAR", str(tmp_path))
    (tmp_path / "schwab_token.json.issued").write_text("not json")
    assert riskd.token_days_left(bots_dir=tmp_path / "bots")["present"] is False
