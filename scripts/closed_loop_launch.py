"""Own the actual Python process, including Windows venv redirector installations."""
from __future__ import annotations

import os
import sys

from scripts.closed_loop_guard import SandboxError

STARTUP_FAILURES = {
    "CHILD_EXITED": "Owned sandbox server exited",
    "READINESS_TIMEOUT": "Sandbox server readiness timed out",
    "IDENTITY_HTTP_STATUS": "Server identity request failed; controls refused",
    "IDENTITY_INVALID_JSON": "Server identity response is invalid JSON; controls refused",
    "IDENTITY_INVALID_SHAPE": "Server identity response has an invalid shape; controls refused",
    "IDENTITY_NONCE_MISMATCH": "Server identity mismatch (run nonce); controls refused",
    "IDENTITY_RUNTIME_MISMATCH": "Server identity mismatch (runtime); controls refused",
    "IDENTITY_PID_MISMATCH": "Server identity mismatch (PID); controls refused",
}


class ServerStartupError(SandboxError):
    """Only fixed public diagnostics; never serialize a raw authenticated response."""
    def __init__(self, code: str):
        self.code = code
        super().__init__(STARTUP_FAILURES[code])


def python_executable(env: dict[str, str]) -> str:
    """CPython's own venv-launcher protocol retains prefix/packages without an extra PID."""
    for key in ("__PYVENV_LAUNCHER__", "PYTHONEXECUTABLE", "PYTHONHOME"):
        env.pop(key, None)
    if os.name == "nt" and sys.prefix != sys.base_prefix:
        base = getattr(sys, "_base_executable", None)
        if not base or not os.path.isfile(base):
            raise SandboxError("Virtual-environment base interpreter unavailable; refusing launch")
        # Windows PC/launcher.c sets this before launching the same base interpreter.
        # CPython getpath uses it to locate pyvenv.cfg and select this venv's packages.
        env["__PYVENV_LAUNCHER__"] = sys.executable
        return base
    return sys.executable
