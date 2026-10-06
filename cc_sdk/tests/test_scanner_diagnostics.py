"""Scanner failures and missing configuration must leave durable, safe evidence."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("scanner_subject", Path(__file__).resolve().parents[2] / "bots/sip_orb/sip_scanner.py")
sip_scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sip_scanner)


def test_unconfigured_scanner_is_not_a_healthy_empty_universe(monkeypatch):
    monkeypatch.delenv("SCANNER_URL", raising=False)
    monkeypatch.delenv("SIP_SYMBOLS", raising=False)
    with pytest.raises(RuntimeError, match="SCANNER_URL.*SIP_SYMBOLS"):
        sip_scanner.universe(None)


def test_scanner_failure_without_fallback_is_not_silenced(monkeypatch):
    monkeypatch.setenv("SCANNER_URL", "https://scanner.test/?key=must-not-log")
    monkeypatch.delenv("SIP_SYMBOLS", raising=False)
    monkeypatch.setattr(sip_scanner, "fetch", lambda url: (_ for _ in ()).throw(RuntimeError("must-not-log")))
    with pytest.raises(RuntimeError, match="scanner request failed") as error:
        sip_scanner.universe(None)
    assert "must-not-log" not in str(error.value)


def test_valid_empty_scanner_result_is_reported_as_no_qualifiers(monkeypatch, caplog):
    monkeypatch.setenv("SCANNER_URL", "https://scanner.test")
    monkeypatch.delenv("SIP_SYMBOLS", raising=False)
    monkeypatch.setattr(sip_scanner, "fetch", lambda url: [{"symbol": "XYZ", "price": 2}])
    with caplog.at_level("INFO"):
        assert sip_scanner.universe(None) == []
    assert "candidates=1" in caplog.text and "selected=0" in caplog.text
