"""Observe and deny supported Python writes outside an owned run; never log contents."""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

from scripts.closed_loop_guard import SandboxError


class WriteAudit:
    """Python audit hooks cover filesystem APIs and SQLite opens, not native OS calls."""
    def __init__(self, root: Path, live: Path, role: str = "worker"):
        self.root = root.resolve()
        self.read_only_db = (live / "cc.db").resolve().as_uri() + "?mode=ro"
        self.log = self.root / f"write-audit-{role}.jsonl"
        self.blocked = 0
        self.local = threading.local()
        self.lock = threading.Lock()

    def install(self) -> None:
        sys.dont_write_bytecode = True
        sys.addaudithook(self.callback)

    def resolve(self, path, dir_fd=None) -> Path:
        path = Path(os.fsdecode(path))
        if not path.is_absolute() and dir_fd is not None and dir_fd != -1:
            descriptor = Path(f"/proc/self/fd/{dir_fd}")
            if not descriptor.exists():
                descriptor = Path(f"/dev/fd/{dir_fd}")
            if not descriptor.exists():
                raise SandboxError("Cannot establish filesystem descriptor ownership")
            path = descriptor.resolve() / path
        return path.resolve()

    def callback(self, event, args) -> None:
        if getattr(self.local, "busy", False):
            return
        paths = []
        if event == "open":
            path, mode, flags = args
            if isinstance(path, int) or not flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                return
            paths = [self.resolve(path)]
        elif event == "sqlite3.connect":
            if args[0] == self.read_only_db:
                self.record(event, "LIVE_READ_ONLY", "allowed")
                return
            if args[0] == ":memory:":
                return
            paths = [self.resolve(args[0])]
        elif event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.utime"}:
            paths = [self.resolve(args[0], args[-1])]
        elif event in {"os.rename", "os.link"}:
            paths = [self.resolve(args[0], args[2]), self.resolve(args[1], args[3])]
        elif event == "os.symlink":
            paths = [self.resolve(args[0]), self.resolve(args[1], args[2])]
        else:
            return
        allowed = all(path.is_relative_to(self.root) for path in paths)
        label = ", ".join(path.relative_to(self.root).as_posix() for path in paths) if allowed else "OUTSIDE_RUN_ROOT"
        self.record(event, label, "allowed" if allowed else "blocked")
        if not allowed:
            raise SandboxError("Filesystem/SQLite write outside owned run was blocked")

    def record(self, event: str, path: str, outcome: str) -> None:
        self.local.busy = True
        try:
            with self.lock:
                self.blocked += outcome == "blocked"
                with self.log.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"event": event, "path": path, "outcome": outcome}) + "\n")
        finally:
            self.local.busy = False
