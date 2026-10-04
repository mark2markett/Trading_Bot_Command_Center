"""Evidence and coverage output; unknown or skipped behavior never becomes a PASS."""
from __future__ import annotations

import ast
import json
import sys
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


class FunctionInventory:
    """Trace reachability, not test adequacy, for actual source functions."""
    def __init__(self, repo: Path, mirror: Path | None = None):
        self.repo, self.mirror = repo.resolve(), mirror.resolve() if mirror else None
        self.seen: dict[tuple[str, int, str], set[str]] = {}
        self.stage = "Sandbox API/riskd"
        self._paths: dict[str, str | None] = {}
        for folder in ("cc_sdk/cc_sdk", "cc_server/cc_server", "bots"):
            for path in sorted((repo / folder).rglob("*.py")):
                if "tests" in path.parts or "_template_bot" in path.parts:
                    continue
                relative = path.relative_to(repo).as_posix()

                def walk(node, parents=(), relative=relative):
                    for child in ast.iter_child_nodes(node):
                        if isinstance(child, ast.ClassDef):
                            walk(child, (*parents, child.name))
                        elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                            line = min([child.lineno] + [d.lineno for d in child.decorator_list])
                            self.seen[(relative, line, ".".join((*parents, child.name)))] = set()
                            walk(child, (*parents, child.name))
                        else:
                            walk(child, parents)
                walk(ast.parse(path.read_text(encoding="utf-8-sig")))

    def callback(self, frame, event, arg):
        if event != "call":
            return
        filename = frame.f_code.co_filename
        if filename not in self._paths:
            path = Path(filename).resolve()
            relative = None
            if path.is_relative_to(self.repo):
                relative = path.relative_to(self.repo).as_posix()
            elif self.mirror and path.is_relative_to(self.mirror):
                relative = path.relative_to(self.mirror).as_posix()
            self._paths[filename] = relative
        name = frame.f_code.co_qualname.replace("<locals>.", "")
        key = (self._paths[filename], frame.f_code.co_firstlineno, name)
        if key in self.seen:
            self.seen[key].add(self.stage)

    @contextmanager
    def observe(self, stage: str):
        previous, old_stage = sys.getprofile(), self.stage
        self.stage = stage
        sys.setprofile(self.callback)
        try:
            yield
        finally:
            sys.setprofile(previous)
            self.stage = old_stage

    def rows(self) -> list[dict]:
        return [{"name": f"{path}:{line} {name}", "scenarios": sorted(stages)}
                for (path, line, name), stages in sorted(self.seen.items())]


class NotCovered(RuntimeError):
    """A known unavailable prerequisite, with a safe human-readable explanation."""


class Report:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.before: dict = {}
        self.after: dict = {}
        self.functions: list[dict] = []
        self.started = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S %Z")

    def add(self, name: str, outcome: str, evidence: str, synthetic: bool = False) -> None:
        if outcome not in {"PASS", "FAIL", "NOT COVERED"}:
            raise ValueError("Unknown result outcome")
        self.rows.append({"name": name, "outcome": outcome, "evidence": evidence, "synthetic": synthetic})

    def check(self, name: str, fn: Callable[[], str], *, synthetic: bool = False) -> bool:
        try:
            evidence = fn()
        except NotCovered as exc:
            self.add(name, "NOT COVERED", str(exc), synthetic)
        except AssertionError as exc:
            self.add(name, "FAIL", str(exc) or "Assertion failed", synthetic)
        except Exception as exc:
            # SDK/network exceptions can include secrets; never serialize their messages.
            self.add(name, "FAIL", f"Unexpected {type(exc).__name__}; inspect the named check", synthetic)
        else:
            self.add(name, "PASS", evidence, synthetic)
            return True
        return False

    @property
    def exit_code(self) -> int:
        return int(any(r["outcome"] == "FAIL" for r in self.rows))

    @property
    def summary(self) -> str:
        counts = {k: sum(r["outcome"] == k for r in self.rows) for k in ("PASS", "FAIL", "NOT COVERED")}
        return f"{counts['FAIL']} FAIL / {counts['NOT COVERED']} NOT COVERED / {counts['PASS']} PASS"

    def table(self) -> str:
        def cell(value: str) -> str:
            return str(value).replace("|", "\\|").replace("\n", " ")
        lines = ["| Check | Result | Evidence |", "|---|---|---|"]
        for row in self.rows:
            label = row["name"] + (" (SYNTHETIC)" if row["synthetic"] else "")
            lines.append(f"| {cell(label)} | {row['outcome']} | {cell(row['evidence'])} |")
        return "\n".join(lines)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"started": self.started, "summary": self.summary, "rows": self.rows,
                "before": self.before, "after": self.after, "functions": self.functions}
        path.with_suffix(".json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        text = f"# Closed-loop report\n\n{self.started}\n\n**{self.summary}**\n\n{self.table()}\n"
        text += "\n## Live fingerprint\n\nHeartbeats and kv excluded. Missing cloud state does not verify the Windows record.\n"
        for name, value in (("Before", self.before), ("After", self.after)):
            text += f"\n### {name}\n\n```json\n{json.dumps(value, indent=2)}\n```\n"
        text += "\n## Function reachability\n\nObserved calls are not proof of every behavior; scenario assertions are reported above.\n"
        if self.functions:
            text += "\n| Function | Observed call | Scenarios |\n|---|---|---|\n"
            for f in self.functions:
                text += f"| {f['name']} | {'yes' if f['scenarios'] else 'NOT COVERED'} | {', '.join(f['scenarios'])} |\n"
        path.write_text(text, encoding="utf-8")
