"""Own a sandbox server; validate identity before any operator request."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.closed_loop_guard import SandboxError, sandbox_env, validate_sandbox  # noqa: E402

BASE_URL = "http://127.0.0.1:8586"


@dataclass
class OwnedServer:
    process: subprocess.Popen
    runtime: Path
    nonce: str
    client: httpx.Client
    log: object

    def verify(self) -> None:
        if self.process.poll() is not None:
            raise SandboxError("Owned sandbox server exited")
        response = self.client.get("/__closed_loop_identity")
        expected = {"nonce": self.nonce, "pid": self.process.pid, "runtime": str(self.runtime)}
        if response.status_code != 200 or response.json() != expected:
            raise SandboxError("Server identity mismatch; controls refused")

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        if not path.startswith("/api/"):
            raise SandboxError("Only sandbox API routes are permitted")
        self.verify()
        return self.client.request(method, path, **kwargs)

    def stop(self) -> None:
        try:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
        finally:
            self.client.close()
            self.log.close()


def start_server(repo: Path, runtime: Path) -> OwnedServer:
    # Bind probe never sends a request to an existing listener.
    with socket.socket() as probe:
        if os.name == "nt":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", 8586))
        except OSError as exc:
            raise SandboxError("Port 8586 is occupied; refusing to reuse an existing server") from exc
    env = sandbox_env(repo, runtime)
    runtime = validate_sandbox(repo, env["CC_VAR"])
    nonce = uuid4().hex
    env["CC_CLOSED_LOOP_ID"] = nonce
    log = (runtime / "server-process.log").open("w", encoding="utf-8")
    try:
        process = subprocess.Popen([sys.executable, str(repo / "scripts" / "closed_loop_server.py"), "--serve"],
                                   cwd=repo, env=env, stdout=log, stderr=subprocess.STDOUT)
    except BaseException:
        log.close()
        raise
    server = OwnedServer(process, runtime, nonce, httpx.Client(base_url=BASE_URL, trust_env=False, timeout=3), log)
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise SandboxError("Sandbox server failed to start; no controls sent")
            try:
                server.verify()
                return server
            except httpx.TransportError:
                time.sleep(0.1)
        raise SandboxError("Sandbox server readiness timed out")
    except BaseException:
        server.stop()
        raise


def serve() -> None:
    runtime = validate_sandbox(ROOT, os.getenv("CC_VAR"))
    if os.getenv("MODE") != "paper" or not os.getenv("CC_CLOSED_LOOP_ID"):
        raise SandboxError("Sandbox server requires a paper worker identity")
    from cc_sdk.control import Control
    from cc_server.main import app

    from cc_server import api

    original = Control.write_flag

    def observed_flag(path, payload):
        if not path.resolve().is_relative_to(runtime / "control"):
            raise SandboxError("Server attempted a flag write outside sandbox control")
        row = api.L().one("SELECT id, action, target FROM controls ORDER BY id DESC LIMIT 1")
        name = path.name
        allowed = ({"kill_all"} if name == "KILL" else {"pause_entries"} if name == "PAUSE_ENTRIES" else
                   {"pause"} if name.endswith(".pause") else {"kill"} if name.endswith(".kill") else
                   {"flatten", "kill", "kill_all"})
        assert row and row["action"] in allowed, "Matching audit row absent before server flag write"
        evidence = {"flag": name, "audit_id": row["id"], "action": row["action"], "target": row["target"],
                    "audit_before_flag": True}
        with (runtime / "flag-audit.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(evidence) + "\n")
        original(path, payload)

    Control.write_flag = staticmethod(observed_flag)

    @app.get("/__closed_loop_identity", include_in_schema=False)
    def identity():
        return {"nonce": os.environ["CC_CLOSED_LOOP_ID"], "pid": os.getpid(), "runtime": str(runtime)}

    # The SPA catch-all is registered earlier; place the identity route before it.
    app.router.routes.insert(0, app.router.routes.pop())
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8586, log_level="warning")


if __name__ == "__main__":
    if sys.argv[1:] != ["--serve"]:
        raise SystemExit("This server is started only by the closed-loop harness")
    serve()
