# Isolated SPY session guard

All four intraday session tasks can legitimately run from 09:25 through the
close, so the full shared-runtime installer must continue to refuse during those
commands. Do not stop them or weaken TRADE-REVIEW-GUARDS.ps1.

INSTALL-SPY-SESSION-GUARD.ps1 is a separate one-file installation route. It reads
the exact reviewed bot.py from the existing checked activity archive. It accepts
only its reviewed compatible original or the same new content, records original
bytes in a recovery receipt, and atomically replaces only
bots/spy_mr_bot/bot.py. Shared SDK/server/display code and runtime JSON files are
never replaced. No task is started, stopped, rescheduled or disabled; no fill,
order, holding or control is written. SQLite connections are read-only.

Both owned SPY scheduled actions must be idle, enabled and more than five minutes
from their next run. Uninspectable Python processes, SPY paths, or daily
reconcile/decide commands refuse. Other session commands may keep running because
none of their imported source files are changed. The shared maintenance lock
still serializes installers. Read-only SPY financial snapshots, saved state and
controls are rechecked before source replacement and at verification. Another
bot's legitimate fills/orders do not block this isolated update.

The installed behavior is the existing exact-session guard: a pending local
paper order settles only if exactly one daily bar matches its saved date. This
installer never runs reconciliation or creates a fill. Its output includes the
current saved SPY state so any completed/failed scheduled reconciliation can be
reviewed without assuming a stale holding remains open.

The full runtime/display update and separately audited stale-stop metadata repair
remain outstanding until all bot commands are idle and current exit evidence is
rechecked. If SPY state advances during verification, source is retained and the
receipt identifies it; do not restore code while a bot may be using it. A new
prepare may safely verify the already-installed source while SPY is idle.

Schwab-side paper execution is still unestablished. Nothing enables live trading.

Validation: 265 transfer-package Python tests pass, including seven SPY-only
source/state-preservation cases. Actual PowerShell on Linux passes ten SPY idle,
action-ownership and scheduling cases plus five wrapper/failure cases. Independent
review found no Critical/Important issues. The existing native session-date
behavior has already passed the full 456-test native suite; this release changes
only the deployment route. Owner Windows activation remains to be verified.
