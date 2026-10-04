"""Evidence and coverage output; unknown or skipped behavior never becomes a PASS."""
from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


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
