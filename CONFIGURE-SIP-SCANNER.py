"""Configure only the native scanner connection after its production release.

Secret input stays in the interactive console. A successful authenticated,
no-store current-session response is required before any configuration write.
This proves connection/configuration only; the morning snapshot is a separate gate.
"""
from __future__ import annotations

import argparse
import getpass
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from dotenv import dotenv_values, set_key

URL = "https://www.mark2markets.com/api/internal/cc/sip-scanner"


class SetupError(RuntimeError):
    """Operator-facing setup refusal; never includes credentials or response bodies."""


def session_date():
    return datetime.now(ZoneInfo("America/New_York")).date().isoformat()


def configure(repo: Path, secret: str, *, transport=None):
    if len(secret) < 32 or not secret.isascii() or "${" in secret or any(c.isspace() or ord(c) < 32 for c in secret):
        raise SetupError("Use the dedicated production scanner secret: at least 32 characters, without whitespace or dotenv substitution syntax.")
    repo = repo.resolve()
    folder = repo / "bots" / "sip_orb"
    path = folder / ".env.local"
    if not (folder / "bot.py").is_file() or path.is_symlink():
        raise SetupError("Expected the existing SIP bot and a regular configuration file.")
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=repo, capture_output=True, text=True, check=True)
    if branch.stdout.strip() != "feat/options-m7":
        raise SetupError("Expected feat/options-m7; no branch was switched.")
    ignored = subprocess.run(["git", "check-ignore", "--quiet", "--", "bots/sip_orb/.env.local"], cwd=repo, capture_output=True)
    if ignored.returncode != 0:
        raise SetupError("Refusing to write credentials: bots/sip_orb/.env.local must be untracked and Git-ignored.")
    before = path.read_bytes() if path.exists() else None
    with httpx.Client(timeout=12, follow_redirects=False, transport=transport) as client:
        try:
            response = client.get(URL, headers={"Authorization": "Bearer " + secret, "Accept": "application/json"})
        except httpx.HTTPError:
            raise SetupError("Could not reach the production scanner; no configuration was changed.") from None
    failures = {
        401: "Scanner authentication failed. Use the same dedicated secret configured in production.",
        404: "Scanner is disabled or not deployed. Complete its release and enabled flag first.",
        503: "Scanner configuration/storage is unavailable. Check its production settings and logs.",
    }
    if response.status_code not in (200, 202):
        raise SetupError(failures.get(response.status_code, "Unexpected scanner response; no configuration was changed."))
    try:
        body = response.json()
    except ValueError:
        raise SetupError("Scanner returned invalid JSON; no configuration was changed.") from None
    cache_directives = {part.strip().split("=", 1)[0].lower() for part in response.headers.get("Cache-Control", "").split(",")}
    if not (
        isinstance(body, dict)
        and type(body.get("version")) is int and body["version"] == 1
        and body.get("session_date") == session_date()
        and {"private", "no-store"} <= cache_directives and "public" not in cache_directives
        and (body.get("status") == "pending" if response.status_code == 202
             else body.get("status") == "ready" and isinstance(body.get("candidates"), list))
    ):
        raise SetupError("Response does not match the deployed current-session scanner contract; no configuration was changed.")
    # Stage all edits together; a failure cannot leave a partly replaced credential file.
    with tempfile.TemporaryDirectory(prefix=".sip-setup-", dir=folder) as stagedir:
        staged = Path(stagedir) / ".env.local"
        staged.write_bytes(before if before is not None else b"")
        staged.chmod(0o600)
        for key, value in (("SCANNER_URL", URL), ("SCANNER_SECRET", secret), ("SIP_SYMBOLS", "")):
            set_key(staged, key, value)
        if dotenv_values(staged).get("SCANNER_SECRET") != secret:
            raise SetupError("This secret cannot round-trip through the bot's dotenv loader. Use a dedicated generated secret; no configuration was changed.")
        if (path.read_bytes() if path.exists() else None) != before:
            raise SetupError("Configuration changed during setup; preserve it and rerun when edits are finished.")
        os.replace(staged, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(r"C:\Users\Administrator\trading_bots\command-center"))
    args = parser.parse_args()
    if not sys.stdin.isatty():
        print("Run this helper in an interactive console; secret input must not be piped or echoed.", file=sys.stderr)
        return 1
    try:
        secret = getpass.getpass("Dedicated production scanner secret (hidden): ")
        configure(args.repo, secret)
    except SetupError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception as error:
        print("Setup failed (" + type(error).__name__ + "); inspect local file permissions/configuration without sharing secrets.", file=sys.stderr)
        return 1
    print("Scanner connection verified; saved SCANNER_URL, SCANNER_SECRET and blank SIP_SYMBOLS.")
    print("Existing feed settings preserved. Bot sessions, controls and paper capital were not changed.")
    print("Configuration applies at the next scheduled SIP start. Verify the fresh scan at 09:35-09:39 Eastern.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
