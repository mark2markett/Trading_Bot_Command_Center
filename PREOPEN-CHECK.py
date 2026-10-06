"""Inspect configuration presence and API readiness; never print credentials or call a broker."""
import json
import os
import sys
import urllib.request
from pathlib import Path

from dotenv import dotenv_values

root = Path(sys.argv[1]).resolve()
keys = ("SCHWAB_CLIENT_ID", "SCHWAB_CLIENT_SECRET", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")
broker_keys = ("CC_TOKEN_BROKER_URL", "CC_TOKEN_BROKER_SECRET")
ready = True
for folder in ("gap_go_bot", "gap_go_spread_bot", "nr7_bot", "sip_orb", "spy_mr_bot"):
    values = dict(os.environ)
    for path, override in ((root / "bots" / folder / ".env", False),
                           (root / "bots" / folder / ".env.local", True), (root / ".env.local", False)):
        if path.exists():
            for key, value in dotenv_values(path).items():
                if value is not None and (override or key not in values):
                    values[key] = value
    shared = all(values.get(k, "").strip() for k in keys)
    broker = all(values.get(k, "").strip() for k in broker_keys)
    row = {"bot": folder, "shared_state_configured": shared, "token_broker_configured": broker}
    data_ready = bool(shared or broker)
    if folder == "spy_mr_bot":
        row["paper_schwab_enabled"] = values.get("PAPER_USE_SCHWAB_DATA", "true").lower() == "true"
        data_ready = data_ready and row["paper_schwab_enabled"]
    if folder == "sip_orb":
        row["scanner_url_present"] = bool(values.get("SCANNER_URL", "").strip())
        row["fallback_symbol_count"] = len([s for s in values.get("SIP_SYMBOLS", "").split(",") if s.strip()])
        data_ready = data_ready and (row["scanner_url_present"] or row["fallback_symbol_count"] > 0)
    row["configuration_ready"] = bool(data_ready)
    ready = ready and bool(data_ready)
    print(json.dumps(row))
for endpoint in ("health", "bots", "risk", "alerts", "research"):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:8585/api/{endpoint}", timeout=10) as response:
            data = json.load(response)
        print(json.dumps({"endpoint": endpoint, "responding": True}))
        if endpoint == "risk":
            print(json.dumps({"killed": data["killed"], "entries_paused": data["entries_paused"],
                              "portfolio_equity": data["drawdown"]["equity"]}))
    except Exception as error:
        print(json.dumps({"endpoint": endpoint, "responding": False, "error_type": type(error).__name__}))
        ready = False
print("CONFIGURATION/API CHECK ONLY: live data freshness and scanner responses still need native validation.")
sys.exit(0 if ready else 1)
