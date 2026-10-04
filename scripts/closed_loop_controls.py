"""Actual dashboard API controls followed by actual paper-runner behavior."""
from __future__ import annotations

import json

from cc_sdk.intraday import SessionRunner

from cc_sdk import Order
from scripts.closed_loop_report import Report
from scripts.closed_loop_scenarios import DAY, ScriptedFeed, step
from scripts.closed_loop_sources import FOLDERS


def get(server, path):
    response = server.request("GET", "/api/" + path)
    assert response.status_code == 200, f"GET {path} failed with HTTP {response.status_code}"
    return response.json()


def control(server, action, *, confirm=None):
    body = {"actor": "closed-loop", "note": "SYNTHETIC isolated test"}
    if confirm:
        response = server.request("POST", "/api/controls/confirm/" + confirm)
        assert response.status_code == 200, "Confirmation request failed"
        body["word"] = response.json()["word"]
    response = server.request("POST", "/api/controls/" + action, json=body)
    assert response.status_code == 200, f"Control {action} failed with HTTP {response.status_code}"
    return response.json()


def check_dashboard(context, server, report: Report) -> None:
    def fleet():
        data = get(server, "fleet")
        assert {bot["id"] for bot in data["bots"]} == set(FOLDERS), "Dashboard does not list the five actual bots"
        assert data["fills"], "Recent fills empty"
        for bot_id in ("gap_go", "nr7", "sip_orb"):
            assert get(server, f"bots/{bot_id}")["trades"], f"Trades absent for {bot_id}"
        return f"5 actual bot IDs; {len(data['fills'])} recent fills; equity trades visible on each detail API"

    def greeks():
        data = get(server, "bots/gap_go_spread")
        assert data["options"], "Spread detail has no live Greeks"
        option = data["options"][0]
        assert all(isinstance(option[key], int | float) for key in ("delta_shares", "theta_usd_day", "dte")), "Greeks shape invalid"
        fleet_bot = next(bot for bot in get(server, "fleet")["bots"] if bot["id"] == "gap_go_spread")
        assert fleet_bot["options"] == data["options"], "Fleet/detail Greeks disagree"
        return f"Fleet/detail delta={option['delta_shares']:.2f} shares; theta={option['theta_usd_day']:.2f}/day; DTE={option['dte']}"

    report.check("Dashboard fleet/trades/fills", fleet, synthetic=True)
    report.check("Dashboard open-spread Greeks", greeks, synthetic=True)
    for route in ("bots", "risk", "alerts", "research", "health"):
        def check(route=route):
            data = get(server, route)
            assert isinstance(data, dict | list), f"Invalid {route} payload"
            if route == "health":
                assert data["ok"], "Sandbox health reports failure"
            return "Actual API returned a valid JSON payload"
        report.check("Dashboard " + route, check, synthetic=True)


def check_controls(context, server, report: Report) -> None:
    def invalid():
        before = context.bots["gap_go"].L.one("SELECT COUNT(*) n FROM controls")["n"]
        response = server.request("POST", "/api/controls/kill_all", json={"word": "invalid"})
        assert response.status_code == 400, "Incorrect confirmation accepted"
        assert not (context.runtime / "control" / "KILL").exists(), "Incorrect confirmation killed the fleet"
        assert context.bots["gap_go"].L.one("SELECT COUNT(*) n FROM controls")["n"] == before, "Invalid control wrote an audit action"
        return "Wrong word -> HTTP 400; no flag or action audit"

    def pause():
        bot_id = "sip_orb"
        bot = context.bots[bot_id]
        feed = ScriptedFeed()
        runner = SessionRunner(bot, feed, context.modules[bot_id].SipOrbRules(), ["QQQ"], adopt_positions=False)
        context.feeds[bot_id], context.runners[bot_id] = feed, runner
        runner.prepare(DAY)
        step(context, bot_id, 10, 1)
        assert "QQQ" in runner.open, "Pause test could not open its paper position"
        runner.symbols.append("IWM")
        runner.prepare(DAY)
        control(server, "bot/sip_orb/pause")
        step(context, bot_id, 10, 3)
        assert "IWM" not in runner.open, "Paused runner entered a new symbol"
        refusal = bot.risk.pre_trade(Order("BUY", 1, "MKT", "IWM", 572))
        assert not refusal.ok and "pause" in refusal.reason, "Paused SDK entry not refused"
        feed.spot = 571
        step(context, bot_id, 10, 4)
        assert not runner.open and not bot.positions(), "Pause blocked a risk-reducing stop exit"
        control(server, "bot/sip_orb/resume")
        assert not bot.control.entries_paused(), "Resume did not clear pause"
        assert bot.risk.pre_trade(Order("BUY", 1, "MKT", "IWM", 571)).ok, "Resume did not restore entry eligibility"
        return "Runner suppressed entry; SDK recorded pause rejection; actual stop exit filled while paused; resume restored eligibility"

    def flatten_spread():
        bot = context.bots["gap_go_spread"]
        assert context.runners["gap_go_spread"].open, "Open spread prerequisite unavailable"
        control(server, "bot/gap_go_spread/flatten", confirm="flatten:gap_go_spread")
        step(context, "gap_go_spread", 10, 5)
        assert not bot.positions(), "Spread flatten left positions open"
        assert bot.L.one("SELECT 1 FROM option_trades WHERE bot_id='gap_go_spread'"), "Spread close not recorded"
        assert not bot.L.one("SELECT 1 FROM kv WHERE key='optlive:gap_go_spread:SPY'"), "Flatten left stale live Greeks"
        return "Confirmed API flatten -> real spread close; option_trades persisted; legs and optlive removed"

    def bot_kill():
        bot = context.bots["gap_go"]
        control(server, "bot/gap_go/kill", confirm="kill:gap_go")
        assert bot.control.killed(), "Bot kill flag absent"
        result = bot.risk.pre_trade(Order("BUY", 1, "MKT", "KILL_PROBE", 572))
        assert not result.ok and "kill" in result.reason, "Killed bot accepted entry"
        step(context, "gap_go", 10, 6)
        control(server, "bot/gap_go/resume")
        assert not bot.control.killed(), "Bot resume left kill flag"
        return "Confirmed bot kill blocked SDK entry; resume removed bot kill"

    def fleet_pause():
        bot = context.bots["sip_orb"]
        control(server, "pause_entries")
        result = bot.risk.pre_trade(Order("BUY", 1, "MKT", "PAUSE_PROBE", 572))
        assert not result.ok and "pause" in result.reason, "Fleet pause accepted entry"
        assert bot.risk.pre_trade(Order("SELL", 1, "MKT", "QQQ", 572, reduces_risk=True)).ok, "Fleet pause blocked exit"
        control(server, "resume_entries")
        assert not bot.control.entries_paused(), "Fleet resume did not clear flag"
        return "Fleet pause refused new entry and permitted exit; resume cleared flag"

    def flatten_all():
        bot_id = "nr7"
        feed = ScriptedFeed()
        runner = SessionRunner(context.bots[bot_id], feed, context.modules[bot_id].NR7Rules(), ["QQQ"], adopt_positions=False)
        context.feeds[bot_id], context.runners[bot_id] = feed, runner
        runner.prepare(DAY)
        step(context, bot_id, 10, 1)
        assert runner.open, "Flatten-all paper position prerequisite failed"
        control(server, "flatten_all", confirm="flatten_all")
        for key in list(context.runners):
            step(context, key, 10, 7)
        assert all(not bot.positions() for bot in context.bots.values()), "Fleet flatten left a paper position"
        return "Confirmed flatten_all -> next actual runner polls closed all intraday positions"

    def kill_all():
        runner = context.runners["gap_go_spread"]
        runner.symbols = ["QQQ"]
        runner.prepare(DAY)
        step(context, "gap_go_spread", 10, 8)
        assert runner.open, "Kill test could not open a second paper spread"
        control(server, "kill_all", confirm="kill_all")
        assert get(server, "fleet")["killed"], "Fleet API does not show killed"
        assert all(bot["flags"]["killed"] and bot["status"] == "killed" for bot in get(server, "fleet")["bots"]), "Not all bots show killed"
        for key in list(context.runners):
            step(context, key, 10, 9)
        assert all(not bot.positions() for bot in context.bots.values()), "Kill did not flatten on next poll"
        bot = context.bots["sip_orb"]
        result = bot.risk.pre_trade(Order("BUY", 1, "MKT", "REARM_PROBE", 572))
        assert not result.ok and "kill" in result.reason, "Killed fleet accepted new entry"
        control(server, "rearm", confirm="rearm")
        assert not (context.runtime / "control" / "KILL").exists(), "Re-arm left KILL flag"
        assert bot.risk.pre_trade(Order("BUY", 1, "MKT", "REARM_PROBE", 572)).ok, "Re-arm did not restore eligible entry"
        assert not get(server, "fleet")["killed"], "Fleet remains killed after re-arm"
        return "Audit before KILL; all five killed; next polls flattened spread; SDK blocked entry; re-arm restored eligibility"

    for label, fn in (("Invalid confirmation", invalid), ("Bot pause/exit/resume", pause),
                      ("Bot spread flatten", flatten_spread), ("Bot kill/resume", bot_kill),
                      ("Fleet pause/resume", fleet_pause), ("Fleet flatten", flatten_all), ("Fleet kill/re-arm", kill_all)):
        report.check(label, fn, synthetic=True)

    def audit():
        path = context.runtime / "flag-audit.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        assert rows and all(row["audit_before_flag"] for row in rows), "Audit-before-flag evidence incomplete"
        assert any(row["flag"] == "KILL" and row["action"] == "kill_all" for row in rows), "KILL audit evidence missing"
        return f"Observed {len(rows)} actual server flag writes with matching audits already persisted"
    report.check("Audit before server flags", audit, synthetic=True)
