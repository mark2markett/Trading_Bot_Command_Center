# Fleet paper-entry release — October 19, 2026

Owner approval: release the fleet paper-entry pause after fresh risk checks; retain SIP's separate four-consecutive-loss pause and the existing SPY holding.

`RESUME-FLEET-PAPER.ps1 -Repo <checkout> -ApproveFleetPaperEntries` performs this one explicit operator action. It checks the reviewed installed maintenance source, five paper bots, coherent holding/stop state, current valuation and observers, the exact historical fleet pause, unchanged limits, drawdown below 6%, gross exposure below 1.5x and daily P&L above -2%. All checks must pass; exceptions are not bypassed.

It temporarily disables the owned monitor schedule and allows any current check to finish. It pauses only the owned server task, preserving bot tasks. With the server stopped and a SQLite write transaction, it verifies that financial records and controls still match the receipt. It appends the control audit and resets only the drawdown pause latch before removing the global pause. SIP's pause and higher drawdown latches are retained. This prevents the existing generic Resume action's failure to re-arm the drawdown pause step.

The server is restarted and read-only risk/readiness checks repeated. Failure after attempting release retains or recreates the global pause. The monitor is enabled again. A local receipt in `var/backups/fleet-resume-*.json` records the observed state. No source, credentials, positions, stops, orders, fills, trades, history, starting capital, limits or bot schedules are rewritten. The helper does not import a strategy or call a provider. The SDK's normal price and exposure guards remain in force.

SIP remains paused. Its current-session authenticated scanner publication and native selection still require independent opening verification; this operation does not certify scanner readiness or replay a missed opening. Existing SPY stops are simulated daily-bar stops, not live broker orders. External incident notifications remain unconfigured.

Run once. A repeated attempt after success refuses because the historical fleet pause is no longer present. Preserve the receipt if any check refuses. Do not use the broad Re-arm action as a replacement: that also releases kill controls.

Health-check correction: the previous checker could label a failed health request as a ledger mismatch because it compared an empty fallback path. It now reports transport failures separately and retries a health timeout once, with the same five-second request limit. Ledger identity requires the same canonical resolved path and actual file identity; alternate hard-link filenames are refused because SQLite WAL paths differ. All observer-age, financial, control and risk gates remain in force. This corrects a reproduced checker defect; the original Windows failure cause still requires current-state evidence.
