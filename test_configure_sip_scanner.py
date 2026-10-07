"""Native setup refusal and credential-preservation checks; no real network."""
import importlib.util
import subprocess
from pathlib import Path

import httpx
import pytest
from dotenv import dotenv_values

HELPER = Path(__file__).with_name("CONFIGURE-SIP-SCANNER.py")
SECRET = "synthetic-scanner-credential-for-tests-only"


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "feat/options-m7", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text(".env.local\n")
    folder = tmp_path / "bots" / "sip_orb"
    folder.mkdir(parents=True)
    (folder / "bot.py").write_text("# Existing paper bot; never executed by setup.\n")
    (folder / ".env.local").write_text("# Keep existing connection\nCC_TOKEN_BROKER_SECRET='existing-value'\nOTHER_SETTING=keep\n")
    return tmp_path


def helper():
    assert HELPER.exists(), "Scanner setup helper is not implemented"
    spec = importlib.util.spec_from_file_location("sip_setup", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_authenticated_pending_response_configures_only_scanner_keys(repo):
    setup = helper()

    def respond(request):
        assert request.headers["authorization"] == "Bearer " + SECRET
        assert str(request.url) == setup.URL
        return httpx.Response(202, json={"version": 1, "status": "pending", "session_date": setup.session_date()},
                              headers={"Cache-Control": "private, no-store"})

    setup.configure(repo, SECRET, transport=httpx.MockTransport(respond))
    path = repo / "bots/sip_orb/.env.local"
    values = dotenv_values(path)
    assert values["SCANNER_URL"] == setup.URL
    assert values["SCANNER_SECRET"] == SECRET
    assert values["SIP_SYMBOLS"] == ""
    assert values["CC_TOKEN_BROKER_SECRET"] == "existing-value"
    assert values["OTHER_SETTING"] == "keep"
    assert "# Keep existing connection" in path.read_text()
    result = subprocess.run(["git", "status", "--porcelain", "--", str(path)], cwd=repo, capture_output=True, text=True, check=True)
    assert not result.stdout


def test_current_session_ready_response_also_accepts_configuration(repo):
    setup = helper()
    reply = {"version": 1, "status": "ready", "session_date": setup.session_date(), "candidates": []}
    setup.configure(repo, SECRET, transport=httpx.MockTransport(lambda _: httpx.Response(200, json=reply, headers={"Cache-Control": "private, no-store"})))
    assert dotenv_values(repo / "bots/sip_orb/.env.local")["SCANNER_SECRET"] == SECRET


def test_short_secret_is_refused_before_network_or_write(repo):
    setup = helper()
    path = repo / "bots/sip_orb/.env.local"
    before = path.read_bytes()

    def no_network(_):
        pytest.fail("Invalid secret must be refused before network access")

    with pytest.raises(setup.SetupError):
        setup.configure(repo, "short", transport=httpx.MockTransport(no_network))
    assert path.read_bytes() == before


def test_dotenv_substitution_secret_is_refused_before_network_or_write(repo):
    setup = helper()
    path = repo / "bots/sip_orb/.env.local"
    before = path.read_bytes()

    def no_network(_):
        pytest.fail("Dotenv substitution must be refused before network access")

    with pytest.raises(setup.SetupError):
        setup.configure(repo, SECRET + "${CC_TEST_UNSET}", transport=httpx.MockTransport(no_network))
    assert path.read_bytes() == before


@pytest.mark.parametrize("cache_header", ["no-store", "public, no-store", "public, private, no-store"])
def test_response_must_be_private_as_well_as_no_store(repo, cache_header):
    setup = helper()
    path = repo / "bots/sip_orb/.env.local"
    before = path.read_bytes()
    reply = {"version": 1, "status": "pending", "session_date": setup.session_date()}
    with pytest.raises(setup.SetupError):
        setup.configure(repo, SECRET, transport=httpx.MockTransport(lambda _: httpx.Response(202, json=reply, headers={"Cache-Control": cache_header})))
    assert path.read_bytes() == before


def test_secret_loader_round_trip_is_checked_before_configuration_replace(repo, monkeypatch):
    setup = helper()
    path = repo / "bots/sip_orb/.env.local"
    before = path.read_bytes()
    reply = {"version": 1, "status": "pending", "session_date": setup.session_date()}
    original = setup.set_key

    def corrupt_secret_encoding(target, key, value):
        return original(target, key, "wrong-serialized-value" if key == "SCANNER_SECRET" else value)

    monkeypatch.setattr(setup, "set_key", corrupt_secret_encoding)
    with pytest.raises(setup.SetupError):
        setup.configure(repo, SECRET, transport=httpx.MockTransport(lambda _: httpx.Response(202, json=reply, headers={"Cache-Control": "private, no-store"})))
    assert path.read_bytes() == before


def test_backslashes_and_quotes_load_as_the_authenticated_secret(repo):
    setup = helper()
    secret = SECRET + "\\\\'"
    reply = {"version": 1, "status": "pending", "session_date": setup.session_date()}
    setup.configure(repo, secret, transport=httpx.MockTransport(lambda _: httpx.Response(202, json=reply, headers={"Cache-Control": "private, no-store"})))
    assert dotenv_values(repo / "bots/sip_orb/.env.local")["SCANNER_SECRET"] == secret


@pytest.mark.parametrize("status,payload,headers", [
    (401, {"error": "unauthorized"}, {"Cache-Control": "private, no-store"}),
    (404, {"error": "not_found"}, {"Cache-Control": "private, no-store"}),
    (503, {"error": "scanner_unavailable"}, {"Cache-Control": "private, no-store"}),
    (202, {"version": 1, "status": "pending", "session_date": "2020-01-01"}, {"Cache-Control": "private, no-store"}),
    (202, {"ok": True}, {"Cache-Control": "private, no-store"}),
    (202, {"version": 1, "status": "pending", "session_date": "today"}, {}),
])
def test_failed_or_wrong_endpoint_probe_preserves_configuration(repo, status, payload, headers):
    setup = helper()
    path = repo / "bots/sip_orb/.env.local"
    before = path.read_bytes()
    with pytest.raises(setup.SetupError) as failure:
        setup.configure(repo, SECRET, transport=httpx.MockTransport(lambda _: httpx.Response(status, json=payload, headers=headers)))
    assert path.read_bytes() == before
    assert SECRET not in str(failure.value)


def test_tracked_credential_file_is_refused_before_network(repo):
    setup = helper()
    path = repo / "bots/sip_orb/.env.local"
    subprocess.run(["git", "add", "-f", str(path)], cwd=repo, check=True)
    before = path.read_bytes()

    def no_network(_):
        pytest.fail("Tracked credential file must be refused before network access")

    with pytest.raises(setup.SetupError):
        setup.configure(repo, SECRET, transport=httpx.MockTransport(no_network))
    assert path.read_bytes() == before


def test_failed_atomic_write_keeps_original_credentials(repo, monkeypatch):
    setup = helper()
    path = repo / "bots/sip_orb/.env.local"
    before = path.read_bytes()
    count = 0

    def fail_second_write(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("Synthetic disk failure")
        return original(*args, **kwargs)

    original = setup.set_key
    monkeypatch.setattr(setup, "set_key", fail_second_write)
    reply = {"version": 1, "status": "pending", "session_date": setup.session_date()}
    with pytest.raises(OSError):
        setup.configure(repo, SECRET, transport=httpx.MockTransport(lambda _: httpx.Response(202, json=reply, headers={"Cache-Control": "private, no-store"})))
    assert path.read_bytes() == before
    assert not list(path.parent.glob(".sip-setup-*"))
