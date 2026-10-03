"""Alert delivery. 'page' goes out immediately on the configured channel; 'digest' is batched at 06:00 ET.
Config: var/alerts.toml  (see README). Default channel is console, which only logs."""
from __future__ import annotations

import logging
import os
import smtplib
import tomllib
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Protocol

from cc_sdk.ledger import Ledger, now_iso, var_dir

log = logging.getLogger("alerts")


class Channel(Protocol):
    name: str
    def send(self, subject: str, body: str) -> None: ...


class Console:
    name = "console"
    def send(self, subject: str, body: str) -> None:
        log.warning("ALERT %s — %s", subject, body)


class Sms:
    """Twilio SMS. Credentials come from environment variables named in alerts.toml, never from the file itself."""
    name = "sms"

    def __init__(self, cfg: dict[str, Any]):
        self.sid = os.getenv(cfg.get("account_sid_env", "TWILIO_ACCOUNT_SID"), "")
        self.token = os.getenv(cfg.get("auth_token_env", "TWILIO_AUTH_TOKEN"), "")
        self.from_ = cfg.get("from", ""); self.to = cfg.get("to", "")

    def send(self, subject: str, body: str) -> None:
        import httpx
        if not (self.sid and self.token and self.from_ and self.to):
            raise RuntimeError("sms channel not configured")
        httpx.post(f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Messages.json",
                   auth=(self.sid, self.token), data={"From": self.from_, "To": self.to, "Body": f"{subject}: {body}"[:1500]},
                   timeout=15).raise_for_status()


class Email:
    name = "email"

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.password = os.getenv(cfg.get("password_env", "CC_SMTP_PASSWORD"), "")

    def send(self, subject: str, body: str) -> None:
        c = self.cfg
        msg = EmailMessage(); msg["Subject"] = subject; msg["From"] = c["from"]; msg["To"] = c["to"]; msg.set_content(body)
        with smtplib.SMTP(c["host"], int(c.get("port", 587)), timeout=20) as s:
            s.starttls(); s.login(c["user"], self.password); s.send_message(msg)


def load_config() -> dict[str, Any]:
    p = var_dir() / "alerts.toml"
    if not p.exists():
        return {"page": {"channel": "console"}, "digest": {"channel": "console", "hour_et": 6}}
    return tomllib.loads(p.read_text())


def build(cfg: dict[str, Any]) -> Channel:
    kind = cfg.get("channel", "console")
    if kind == "sms":
        return Sms(cfg)
    if kind == "email":
        return Email(cfg)
    return Console()


class Alerter:
    def __init__(self, L: Ledger):
        self.L = L
        self.cfg = load_config()
        self.page = build(self.cfg.get("page", {}))
        self.digest = build(self.cfg.get("digest", {}))

    def deliver_pending_pages(self) -> int:
        n = 0
        for a in self.L.q("SELECT * FROM alerts WHERE severity='page' AND delivered_at IS NULL ORDER BY id"):
            try:
                self.page.send(f"[CC] {a['kind']}", a["message"])
                self.L.x("UPDATE alerts SET delivered_at=? WHERE id=?", (now_iso(), a["id"]))
                n += 1
            except Exception as e:  # noqa: BLE001
                log.error("page delivery failed: %s", e)
                Console().send(f"[CC] {a['kind']}", a["message"])
                self.L.x("UPDATE alerts SET delivered_at=? WHERE id=?", (now_iso(), a["id"]))
        return n

    def send_digest(self) -> int:
        rows = self.L.q("SELECT * FROM alerts WHERE severity='digest' AND delivered_at IS NULL ORDER BY id")
        if not rows:
            return 0
        body = "\n".join(f"{r['at'][:16]}  {r['kind']:<16} {r['message']}" for r in rows)
        try:
            self.digest.send(f"[CC] Daily digest — {len(rows)} items", body)
        except Exception as e:  # noqa: BLE001
            log.error("digest delivery failed: %s", e); Console().send("[CC] digest", body)
        ids = ",".join(str(r["id"]) for r in rows)
        self.L.x(f"UPDATE alerts SET delivered_at=? WHERE id IN ({ids})", (now_iso(),))
        return len(rows)

    def test(self) -> dict[str, Any]:
        out = {}
        for name, ch in (("page", self.page), ("digest", self.digest)):
            try:
                ch.send("[CC] test", f"{name} channel test at {now_iso()}"); out[name] = f"ok via {ch.name}"
            except Exception as e:  # noqa: BLE001
                out[name] = f"failed via {ch.name}: {e}"
        self.L.x("INSERT INTO kv(key,value_json,updated_at) VALUES('alert_test',?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                 (str(out).replace("'", '"'), now_iso()))
        return out


def write_default_config() -> Path:
    p = var_dir() / "alerts.toml"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('''# Command Center alert channels. Secrets are read from environment variables, never from this file.
[page]
channel = "console"        # console | sms | email
# from = "+15550001111"    # sms: your Twilio number
# to = "+15550002222"
# account_sid_env = "TWILIO_ACCOUNT_SID"
# auth_token_env = "TWILIO_AUTH_TOKEN"

[digest]
channel = "console"        # console | email
hour_et = 6
# host = "smtp.example.com"; port = 587; user = "you@example.com"; from = "you@example.com"; to = "you@example.com"
# password_env = "CC_SMTP_PASSWORD"
''')
    return p
