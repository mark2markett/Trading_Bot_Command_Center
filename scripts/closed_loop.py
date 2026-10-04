"""One-command, paper-only closed-loop harness. Runtime is disposable; evidence is retained."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
from scripts.closed_loop_guard import SandboxError, claim_run, fingerprint, owned_run, sandbox_env, validate_sandbox  # noqa: E402
from scripts.closed_loop_report import FunctionInventory, NotCovered, Report  # noqa: E402


def check_controls(*args):
    from scripts.closed_loop_controls import check_controls as real_checks
    return real_checks(*args)


def remove_runtime(runtime: Path) -> None:
    shutil.rmtree(runtime)


def capture_web(context, server, report: Report) -> None:
    if not (context.repo / "cc_web/dist/index.html").is_file():
        report.add("Dashboard screenshots", "NOT COVERED", "Built web app missing; run npm run build in cc_web", True)
        return
    if not shutil.which("node") or not (context.repo / "cc_web/node_modules/@playwright/test").exists():
        report.add("Dashboard screenshots", "NOT COVERED", "Node/Playwright dependency unavailable", True)
        return
    server.verify()
    env = sandbox_env(context.repo, context.runtime)
    if not env.get("CC_PLAYWRIGHT_EXECUTABLE") and shutil.which("chromium"):
        env["CC_PLAYWRIGHT_EXECUTABLE"] = shutil.which("chromium")
    output = context.runtime.parent / "screenshots"
    result = subprocess.run(["node", str(context.repo / "scripts/closed_loop_web.mjs"),
                             "http://127.0.0.1:8586", str(output), server.nonce, str(server.process.pid)],
                            cwd=context.repo / "cc_web", env=env, capture_output=True, timeout=60)
    path = output / "web-results.json"
    if not path.is_file():
        report.add("Dashboard screenshots", "FAIL", f"Browser helper produced no results (exit {result.returncode})", True)
        return
    rows = json.loads(path.read_text())
    assert rows, "Browser helper returned no checks"
    for row in rows:
        report.add(row["name"], row["outcome"], row["evidence"], True)
    assert result.returncode == int(any(row["outcome"] == "FAIL" for row in rows)), "Browser exit code disagrees with results"


def risk_refusals(context, server, report: Report) -> None:
    from cc_sdk.options import occ_symbol

    from cc_sdk import Order

    def oversized():
        bot = context.bots["gap_go"]
        qty = int(bot.m.limits["max_order_qty"]) * 3
        result = bot.risk.pre_trade(Order("BUY", qty, "MKT", "FAT_FINGER", 572))
        assert not result.ok and "max_order_qty" in result.reason, "Oversized share order accepted"
        row = bot.L.one("SELECT id FROM orders WHERE bot_id='gap_go' AND status='rejected' AND symbol='FAT_FINGER'")
        assert row, "Oversize rejection absent from ledger"
        data = server.request("GET", "/api/fleet").json()
        assert any(a["kind"] == "order_rejected" and "max_order_qty" in a["message"] for a in data["attention"]), "Size rejection absent from Needs attention"
        return f"qty={qty} rejected by max_order_qty; order id={row['id']}; Needs attention populated"

    def premium():
        from scripts.closed_loop_scenarios import DAY
        bot = context.bots["gap_go_spread"]
        expiry = DAY.date()
        legs = [Order("BUY_TO_OPEN", 100, "LMT", occ_symbol("SPY", expiry, "C", 570), 100),
                Order("SELL_TO_OPEN", 100, "LMT", occ_symbol("SPY", expiry, "C", 575), 99)]
        result = bot.risk.pre_trade_spread(legs, net_debit=100)
        assert not result.ok and "max_premium_usd" in result.reason, "Excessive spread premium accepted"
        count = bot.L.one("SELECT COUNT(*) n FROM orders WHERE bot_id='gap_go_spread' AND status='rejected' AND reason LIKE 'max_premium_usd:%'")["n"]
        assert count >= 2, "Whole-spread premium refusals not recorded"
        return f"$1,000,000 requested premium exceeds ${bot.m.limits['max_premium_usd']:,} cap; both legs recorded rejected"
    report.check("Oversized share order refused", oversized, synthetic=True)
    report.check("Excessive spread premium refused", premium, synthetic=True)


def run_worker(repo: Path, runtime: Path) -> int:
    expected = runtime.resolve()
    runtime = validate_sandbox(repo, os.getenv("CC_VAR"))
    if runtime != expected or os.getenv("MODE") != "paper":
        raise SandboxError("Worker requires an explicit matching paper sandbox")
    owned_run(repo, runtime)
    report = Report()
    context, server = None, None
    inventory = FunctionInventory(repo, runtime.parent / "imports")

    def checked(name, fn, synthetic=False):
        with inventory.observe(name):
            return report.check(name, fn, synthetic=synthetic)

    def before():
        report.before = fingerprint(repo / "var")
        if not report.before["available"]:
            raise NotCovered("Windows live ledger not supplied; no live-record claim can be made from the cloud bundle")
        return "Read-only counts/max IDs/digests and control listing captured; heartbeats/kv excluded"

    checked("Live fingerprint before", before)
    try:
        from scripts.closed_loop_controls import check_dashboard
        from scripts.closed_loop_scenarios import make_scenarios, run_daily_lifecycle, run_equity, run_spread
        from scripts.closed_loop_server import start_server
        from scripts.closed_loop_sources import check_data, replay_history

        with inventory.observe("Register five actual manifests"):
            context = make_scenarios(repo, runtime)
        checked("Actual fleet registration", lambda: f"{len(context.bots)} paper manifests registered in external sandbox", True)
        with inventory.observe("Real data checks"):
            check_data(context, report)
        with inventory.observe("Historical replay"):
            replay_history(context, report)
        for bot_id in ("gap_go", "nr7", "sip_orb"):
            checked(f"Actual {bot_id} signal/risk/fill/exit", lambda bot_id=bot_id: run_equity(context, bot_id), True)
        checked("Daily SPY decide/reconcile", lambda: run_daily_lifecycle(context), True)
        checked("Daily SPY protective stop", lambda: run_daily_lifecycle(context, crash=True), True)
        checked("Stale options chain refused", lambda: run_spread(context, stale=True), True)
        checked("Actual gap-go debit spread", lambda: run_spread(context), True)
        with inventory.observe("Start sandbox dashboard"):
            server = start_server(repo, runtime)
        with inventory.observe("Dashboard readback"):
            check_dashboard(context, server, report)
        checked("Browser checks executed", lambda: (capture_web(context, server, report) or "Rendered checks reported individually"), True)
        with inventory.observe("SDK risk refusals"):
            risk_refusals(context, server, report)
        with inventory.observe("API controls and bot response"):
            check_controls(context, server, report)
        report.add("Scheduled/live/scanner integrations", "NOT COVERED", "Windows scheduler, live order path and external SIP scanner excluded; synthetic bot lifecycles are separately asserted")
    except BaseException as exc:
        report.add("Harness execution", "FAIL", f"Unexpected {type(exc).__name__}; subsequent checks were not executed")
    finally:
        if server:
            checked("Owned sandbox server stopped", lambda: (server.stop() or "Owned server exited; no live process was stopped"))
        handles_closed = context is None
        if context:
            handles_closed = checked("Bot ledger handles closed", lambda: (context.close() or "All owned bot SQLite handles closed"))
        def after():
            report.after = fingerprint(repo / "var")
            assert report.before == report.after, "Live logical fingerprint changed; concurrent live activity is a possible cause, not an accepted exception"
            if not report.after["available"]:
                raise NotCovered("No Windows live ledger in cloud; absent source state remained absent")
            return "Before/after counts, max IDs, digests and control metadata are identical"
        checked("Live fingerprint after / isolation", after)
        report.functions = inventory.rows()
        server_functions = runtime.parent / "server-functions.json"
        if server_functions.is_file():
            extra = {row["name"]: row["scenarios"] for row in json.loads(server_functions.read_text())}
            for row in report.functions:
                row["scenarios"] = sorted(set(row["scenarios"]) | set(extra.get(row["name"], [])))
        def cleanup():
            owned_run(repo, runtime)
            if not handles_closed or (runtime.parent / "owned-server.json").exists():
                raise SandboxError("Process/handle closure unverified; runtime retained")
            remove_runtime(runtime)
            return "Sandbox ledger/control/logs removed; report/screenshots retained"
        checked("Runtime cleanup", cleanup)
        # Daily source copies contain state/logs; delete them after closing their handlers too.
        imports = runtime.parent / "imports"
        if imports.exists():
            def clean_imports():
                owned_run(repo, runtime)
                if not handles_closed or (runtime.parent / "owned-server.json").exists():
                    raise SandboxError("Process/handle closure unverified; source copy retained")
                shutil.rmtree(imports)
                return "Copied source and daily-bot state/logs removed"
            checked("Isolated source cleanup", clean_imports)
        audit_paths = list(runtime.parent.glob("write-audit-*.jsonl"))
        if audit_paths:
            rows = [json.loads(line) for path in audit_paths for line in path.read_text().splitlines()]
            def write_isolation():
                assert not any(row["outcome"] == "blocked" for row in rows), "Outside-run write attempted and blocked; see write audit"
                return f"{len(rows)} supported Python filesystem/SQLite operations observed in worker/server; native-library writes are not an OS-wide trace"
            checked("Filesystem write isolation", write_isolation)
        report.write(runtime.parent / "report.md")
        print(report.summary)
        print(report.table())
        print(f"Report: {runtime.parent / 'report.md'}")
    return report.exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.worker:
            runtime = validate_sandbox(ROOT, os.getenv("CC_VAR"))
            root = owned_run(ROOT, runtime)
            from scripts.closed_loop_audit import WriteAudit
            WriteAudit(root, ROOT / "var").install()
            def interrupted(signum, frame):
                raise KeyboardInterrupt
            previous = signal.signal(signal.SIGTERM, interrupted)
            try:
                return run_worker(ROOT, runtime)
            finally:
                signal.signal(signal.SIGTERM, previous)
        if os.getenv("CC_VAR"):
            validate_sandbox(ROOT, os.environ["CC_VAR"])
        # Validate even the temp-directory location before creating any directories.
        probe = Path(tempfile.gettempdir()) / "cc-closed-loop-location-check" / "var"
        sandbox_env(ROOT, probe)
        root = Path(tempfile.mkdtemp(prefix="cc-closed-loop-"))
        runtime = root / "var"
        env = sandbox_env(ROOT, runtime)
        env["CC_CLOSED_LOOP_OWNER"] = claim_run(ROOT, root)
        os.environ["CC_CLOSED_LOOP_OWNER"] = env["CC_CLOSED_LOOP_OWNER"]
        process = subprocess.Popen([sys.executable, str(ROOT / "scripts/closed_loop.py"), "--worker"], cwd=ROOT, env=env)
        try:
            result = process.wait()
        except KeyboardInterrupt:
            process.terminate()
            process.wait(timeout=10)
            result = 1
        from scripts.closed_loop_server import stop_orphaned_server
        try:
            stop_orphaned_server(runtime)
        except (SandboxError, OSError):
            report = Report()
            report.add("Interrupted server cleanup", "FAIL", f"Owned server cleanup could not be verified; sandbox retained at {root}")
            report.write(root / "supervisor-failure.md")
            print(report.summary)
            print(f"Report: {root / 'supervisor-failure.md'}")
            return 1
        # The worker finalizes ordinary failures. A crashed/interrupted worker needs a retained failure report.
        if not (root / "report.md").exists():
            report = Report()
            report.add("Worker exit", "FAIL", f"Worker exited before final report (exit {result}); sandbox preserved at {root}")
            if runtime.exists():
                try:
                    owned_run(ROOT, runtime)
                    remove_runtime(runtime)
                except (OSError, SandboxError):
                    report.add("Runtime cleanup", "FAIL", "Interrupted runtime could not be removed; external sandbox retained")
            imports = root / "imports"
            if imports.exists():
                try:
                    owned_run(ROOT, runtime)
                    shutil.rmtree(imports)
                except (OSError, SandboxError):
                    report.add("Isolated source cleanup", "FAIL", "Interrupted source copy could not be removed; external sandbox retained")
            report.write(root / "report.md")
            print(report.summary)
            print(f"Report: {root / 'report.md'}")
            return 1
        return result
    except SandboxError as exc:
        print(f"Safety refusal: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
