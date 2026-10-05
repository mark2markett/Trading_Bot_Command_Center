"""Launch the actual interpreter while retaining venv identity and safe startup evidence."""
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from scripts.closed_loop_guard import SandboxError
from scripts.closed_loop_server import OwnedServer


def test_windows_venv_uses_actual_interpreter_and_keeps_venv(monkeypatch):
    from scripts import closed_loop_launch
    monkeypatch.setattr(closed_loop_launch, "os", SimpleNamespace(name="nt", path=os.path))
    env = dict(os.environ)
    executable = closed_loop_launch.python_executable(env)
    assert executable == sys._base_executable
    assert env["__PYVENV_LAUNCHER__"] == sys.executable
    code = "import json,os,sys,httpx; print(json.dumps([os.getpid(),sys.prefix,sys.executable,httpx.__file__]))"
    process = subprocess.Popen([executable, "-c", code], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = process.communicate(timeout=10)
    assert process.returncode == 0, stderr
    pid, prefix, reported_executable, dependency = json.loads(stdout)
    assert pid == process.pid
    assert Path(prefix) == Path(sys.prefix)
    assert Path(reported_executable) == Path(sys.executable)
    assert Path(dependency).is_relative_to(Path(sys.prefix))


def test_normal_platform_keeps_selected_interpreter_and_clears_foreign_launcher(monkeypatch):
    from scripts import closed_loop_launch
    monkeypatch.setattr(closed_loop_launch, "os", SimpleNamespace(name="posix", path=os.path))
    env = {"__PYVENV_LAUNCHER__": "foreign", "PYTHONHOME": "foreign", "PYTHONEXECUTABLE": "foreign"}
    assert closed_loop_launch.python_executable(env) == sys.executable
    assert not env


def test_windows_venv_refuses_missing_base_interpreter(monkeypatch):
    from scripts import closed_loop_launch
    monkeypatch.setattr(closed_loop_launch, "os", SimpleNamespace(name="nt", path=os.path))
    monkeypatch.setattr(closed_loop_launch, "sys", SimpleNamespace(prefix="venv", base_prefix="base", executable="venv/python.exe", _base_executable="missing-base.exe"))
    with pytest.raises(SandboxError, match="interpreter"):
        closed_loop_launch.python_executable({})


def test_wrong_server_pid_is_still_refused_and_diagnostic_is_retained(tmp_path):
    runtime = tmp_path / "var"
    process = SimpleNamespace(pid=1234, poll=lambda: None)
    payload = {"nonce": "owned", "pid": 5678, "runtime": str(runtime)}
    client = httpx.Client(base_url="http://127.0.0.1:8586", transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)))
    server = OwnedServer(process, runtime, "owned", client, io.StringIO())
    try:
        with pytest.raises(SandboxError, match="identity"):
            server.verify()
        diagnostic = json.loads((tmp_path / "server-startup.json").read_text())
        assert diagnostic["failure_code"] == "IDENTITY_PID_MISMATCH"
        assert diagnostic["launcher_pid"] == 1234 and diagnostic["reported_pid"] == 5678
        assert diagnostic["nonce_matches"] and diagnostic["runtime_matches"]
    finally:
        client.close()


def test_invalid_identity_payload_never_exposes_raw_response(tmp_path):
    process = SimpleNamespace(pid=1234, poll=lambda: None)
    client = httpx.Client(base_url="http://127.0.0.1:8586", transport=httpx.MockTransport(lambda request: httpx.Response(200, text="fixture-secret-response")))
    server = OwnedServer(process, tmp_path / "var", "owned", client, io.StringIO())
    try:
        with pytest.raises(SandboxError):
            server.verify()
        text = (tmp_path / "server-startup.json").read_text()
        assert "fixture-secret-response" not in text
        assert json.loads(text)["failure_code"] == "IDENTITY_INVALID_JSON"
    finally:
        client.close()
