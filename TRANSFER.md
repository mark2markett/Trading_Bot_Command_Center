# Current delivery — runtime repair, 2026-10-06

Use [RUNTIME-FIXES.md](RUNTIME-FIXES.md) and APPLY-RUNTIME-FIXES.ps1. This is the consolidated update; previous standalone installers are retained for history.

Command Center source: fix/runtime-log-review-20261006, commit 3e8b5888cb474038cc3f8240e855cc84e12392d5, based on the latest feat/options-m7 base 2783f2e. The incremental bundle requires that base, already present on Windows. It includes the entire closed-loop and runtime repair history so native imports do not depend on testing code having been merged earlier. Existing equivalent patches are skipped; the production checkout remains feat/options-m7.

Platform source: feat/cc-sip-scanner, commit e8146e881f41959218baf6bc4442a40a1e30cd15, published successfully by the native publisher. Publishing the review branch did not merge it, deploy it, configure Redis/secrets, or enable its morning scheduler. See CC-SIP-SCANNER.md for that contract.

Native account: operator-approved one shared $100,000 paper account; never five duplicate balances. Installer checksums cover the source bundle and the production dashboard ZIP. No live database, logs or credential files are included.

Cloud validation: 234 Python tests, 11 web tests, web production build; closed loop 34 PASS, 0 FAIL, 7 NOT COVERED. Import rehearsal preserved the intentional log, dev.sh and untracked handoff file, stayed on feat/options-m7, recognized all patches on rerun, and configured the shared account idempotently against a copy of the uploaded ledger. Native PowerShell execution/live scanner deployment remain to be verified.
