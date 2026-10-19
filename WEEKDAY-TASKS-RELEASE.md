# Weekday bot task repair

The operator's October 18 capture confirms six daily Task Scheduler triggers, interval one day.
Sunday SPY reconciliation failed its 90-second quote freshness limit (alert 34); Sunday SIP ended
without a scanner universe (alert 35). Both original alert kinds are run_failed. The incident classifier
currently labels that kind unknown_alert; this repair preserves the alerts and their review state.

REPAIR-WEEKDAY-TASKS.ps1 -Apply changes only the triggers of the six known CC bot tasks to Monday-Friday,
at the same Eastern clock times (09:25 sessions, 09:45 reconciliation, 15:50 decision). Each changed trigger
gets its next strictly future occurrence, rather than retaining an obsolete start date that could make
StartWhenAvailable run a missed session immediately. Future boundaries use Eastern local time without a fixed UTC offset, so recurring tasks follow the Windows Eastern clock through DST.
The server and health monitor are neither stopped nor re-registered. Bot actions, principals, settings,
enabled state, source, financial records and controls are preserved and checked. No task is launched.
This does not add exchange-holiday or early-close scheduling; those remain separate calendar work.

Run before 09:20 ET or after 16:15 ET, with bot commands idle, on the existing verified paper maintenance
source. The reused holding gate verifies the coherent paper holding/recorded stop, retained fleet pause,
source compatibility, protected financial records and equity history. An unknown task, customized cadence,
extra action, changed ownership evidence, unreadable Python command or running bot refuses repair.
Task definitions with custom repetition/end dates or nonzero random delay also require separate review.

Without -Apply the helper reports the schedule and makes no task change. With -Apply it exports six
original XML files and a receipt below var/backups/weekday-tasks-*. It changes triggers with Set-ScheduledTask,
then checks schedule, actions, principals, settings and the financial fingerprint. Re-running it is idempotent.
Windows default trigger values (zero random delay and a 72-hour trigger limit) are normalized for comparison.
The whole task's existing execution-time setting remains untouched. Keep the receipt if a readback fails;
some triggers may already be corrected, and no automatic financial rollback is attempted.

For an explicit trigger-only rollback use the same release:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\REPAIR-WEEKDAY-TASKS.ps1 `
    -Repo 'C:\Users\Administrator\trading_bots\command-center' -Apply -Rollback -Receipt '<printed directory>'
```

Rollback verifies task identity, original XML hashes and current readback before restoring each prior
frequency at its next future clock occurrence. It does not backdate triggers or restore a financial database.
A rollback progress journal permits retry with the same receipt after a partial update and makes a completed rollback idempotent. It reinstates the prior daily cadence when that was the original setting, so weekends are again eligible.

## Verification and remaining readiness

PowerShell 7.5.4 on Linux tests the real XML parsing/repair flow through an isolated Windows Task Scheduler
adapter: ownership, weekday days, times, future boundaries, DST, serialized defaults, settings preservation,
read-only mode, all-six apply, idempotence, rollback, and refusal for running commands, unknown ownership or
wrong timezone. Actual Windows ScheduledTasks/CIM execution still needs the operator's application result.
The underlying holding-preservation tests run in the existing Python release suite.

This repair prevents the confirmed weekend bot launches. It does not make a Sunday quote current, clear
fleet/SIP pauses, change the daily SPY simulated stop into broker protection, configure external notification
channels, acknowledge old incidents, merge platform PR 1309 or certify live scanner publication. Fresh actual
prices and the Monday 09:35-09:39 authenticated publication/native selection remain required. The old broad
scripts/install_tasks.ps1 recreates daily triggers; re-check schedules if that legacy installer is run again.

## Execution-limit readback correction and resuming a partial update

A Windows application stopped at ExecutionTimeLimit readback after updating the first task. The actual
Windows before/after duration strings remain to be collected. Independently, a regression reproduced a
false mismatch between PT72H and P3D, which are equal durations. Readback now compares fixed day/time ISO
durations by value; it still rejects genuine changes such as 72 hours becoming one hour. Calendar months
and years are not approximated. Default limits and every existing task setting remain protected.

CHECK-WEEKDAY-TASKS.ps1 -Receipt '<original receipt directory>' publishes the small read-only comparison
of the first two original/current trigger and task limits, actions, principals and settings. It prints no
credentials and makes no task, source, trade or control changes.

Use REPAIR-WEEKDAY-TASKS.ps1 -Apply -ResumeReceipt '<original receipt directory>' to continue a partial apply.
Before any additional update, it verifies all six current definitions against the original receipt, including
the task already on weekdays. Equivalent duration formatting is accepted; a real difference stops with the
expected and observed property values. The remaining five tasks are updated only if those checks pass.
Unknown command-line switches are rejected. Additional tests cover canonical Windows-style duration
serialization, refusal of genuine limit changes and receipt-verified partial-apply recovery.
