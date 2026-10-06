import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "readiness_subject", Path(__file__).resolve().parents[2] / "scripts/native_readiness.py"
)


def subject():
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_scanner_and_capital_are_failures_not_coverage_gaps():
    m = subject()
    problems = m.configuration_problems({"paper_account": {"ready": False}}, {"SCANNER_URL": "", "SCANNER_SECRET": ""})
    assert "paper_account" in problems and "scanner" in problems


@pytest.mark.parametrize(
    "url,secret",
    [("https://scanner.test/api", ""), ("http://outside.test/api", "s" * 40), ("https://user:pass@scanner.test/api", "s" * 40)],
)
def test_insecure_or_incomplete_scanner_configuration_fails(url, secret):
    m = subject()
    assert "scanner" in m.configuration_problems(
        {"paper_account": {"ready": True}}, {"SCANNER_URL": url, "SCANNER_SECRET": secret}
    )


def test_configured_account_and_authenticated_scanner_pass_configuration_only():
    m = subject()
    assert (
        m.configuration_problems(
            {"paper_account": {"ready": True}}, {"SCANNER_URL": "https://scanner.test/api", "SCANNER_SECRET": "s" * 40}
        )
        == []
    )


def test_readiness_requires_the_actual_windows_sessions_to_be_running():
    m = subject()
    tasks = [{"TaskName": name, "State": "Running", "Enabled": True} for name in m.SESSION_TASKS]
    assert m.scheduler_ready(tasks)
    tasks[0]["State"] = "Ready"
    assert not m.scheduler_ready(tasks)
    assert not m.scheduler_ready([])
