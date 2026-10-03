"""
Local status dashboard for the SPY Daily Mean Reversion bot.

    python dashboard.py            -> http://127.0.0.1:8585

Read-only view of state, ledger and log, plus buttons that run `bot.py check` / `bot.py reconcile`
(the same commands the scheduler runs). Binds to localhost only; nothing is exposed to the network.
No order can be placed from this page.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template_string

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")
MODE = os.getenv("MODE", "paper").lower()
PY = sys.executable
app = Flask(__name__)


def _json(p: Path, default):
    try:
        return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return default


def _run(cmd: str) -> str:
    r = subprocess.run([PY, str(HERE / "bot.py"), cmd], cwd=HERE, capture_output=True, text=True, timeout=120)
    return (r.stdout + r.stderr).strip()


def snapshot() -> dict:
    state = _json(HERE / f"state_{MODE}.json", {})
    ledger = _json(HERE / "paper_ledger.json", {}) if MODE == "paper" else {}
    log_lines = []
    lp = HERE / "bot.log"
    if lp.exists():
        log_lines = lp.read_text(errors="ignore").splitlines()[-40:]
    check_raw = _run("check")
    try:
        check = json.loads(check_raw[check_raw.index("{"):])
    except Exception:  # noqa: BLE001
        check = {"error": check_raw[-600:]}
    schwab = bool(os.getenv("SCHWAB_API_KEY")) and (HERE / os.getenv("TOKEN_PATH", "schwab_token.json")).exists()
    return {"mode": MODE, "schwab_connected": schwab, "state": state, "ledger": ledger,
            "check": check, "log": log_lines, "symbol": os.getenv("SYMBOL", "SPY")}


PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>SPY MR Bot</title>
<meta http-equiv="refresh" content="300">
<style>
:root{--bg:#0f1115;--card:#171a21;--fg:#e6e6e6;--mut:#8a93a3;--ok:#2ecc71;--warn:#f1c40f;--bad:#e74c3c;--acc:#4ea1ff}
body{margin:0;font:14px/1.45 system-ui,Segoe UI,Arial;background:var(--bg);color:var(--fg)}
header{display:flex;align-items:center;gap:16px;padding:14px 20px;border-bottom:1px solid #262a33}
h1{font-size:18px;margin:0}.pill{padding:3px 10px;border-radius:999px;font-weight:600;font-size:12px}
.paper{background:#2b3a55;color:#9cc4ff}.live{background:#5a1f1f;color:#ffb3b3}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}
main{padding:16px 20px;display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
.card{background:var(--card);border:1px solid #262a33;border-radius:10px;padding:14px 16px}
.card h2{font-size:13px;letter-spacing:.04em;text-transform:uppercase;color:var(--mut);margin:0 0 10px}
.kv{display:grid;grid-template-columns:1fr auto;gap:6px 12px}.kv b{font-weight:500;color:var(--mut)}
.big{font-size:26px;font-weight:700}
table{width:100%;border-collapse:collapse;font-size:13px}td,th{padding:5px 6px;border-bottom:1px solid #262a33;text-align:left}
th{color:var(--mut);font-weight:500}pre{margin:0;font:12px/1.4 Consolas,monospace;white-space:pre-wrap;max-height:360px;overflow:auto;color:#c7ccd6}
.btn{display:inline-block;padding:7px 14px;border-radius:6px;background:var(--acc);color:#fff;text-decoration:none;font-weight:600;margin-right:8px}
.btn.sec{background:#2b2f3a}.wide{grid-column:1/-1}.mut{color:var(--mut)}
</style></head><body>
<header><h1>{{d.symbol}} Daily Mean Reversion</h1>
<span class="pill {{d.mode}}">{{d.mode|upper}}</span>
<span class="{{'ok' if d.schwab_connected else 'warn'}}">● {{'Schwab connected' if d.schwab_connected else 'Schwab not connected (free EOD data)'}}</span>
<span class="mut" style="margin-left:auto">auto-refresh 5 min</span></header>
<main>
{% set s=d.state %}{% set c=d.check %}
<div class="card"><h2>Position</h2>
{% if s.in_position %}<div class="big ok">LONG {{s.qty}} {{d.symbol}}</div>
<div class="kv"><b>Entry</b><span>{{s.entry_date}} @ {{'%.2f'|format(s.entry_price)}}</span>
<b>Bars held</b><span>{{s.bars_held}} / 10</span>
<b>Crash stop</b><span>{{'%.2f'|format(s.entry_price*0.95)}}</span>
<b>Unrealized</b><span class="{{'ok' if c.price>=s.entry_price else 'bad'}}">{{'%+.2f%%'|format((c.price/s.entry_price-1)*100)}}</span></div>
{% else %}<div class="big mut">FLAT</div>{% endif %}
{% if s.pending %}<p class="warn">Pending {{s.pending.side}} {{s.pending.qty}} MOC ({{s.pending.reason}}) for {{s.pending.date}}</p>{% endif %}
</div>
<div class="card"><h2>Signal now</h2>
{% if c.error %}<pre class="bad">{{c.error}}</pre>{% else %}
<div class="kv"><b>Price</b><span>{{'%.2f'|format(c.price)}}</span>
<b>RSI(2)</b><span class="{{'ok' if c.rsi2<10 else ''}}">{{'%.1f'|format(c.rsi2)}} <span class="mut">(buy &lt; 10)</span></span>
<b>SMA 200</b><span class="{{'ok' if c.price>c.sma200 else 'bad'}}">{{'%.2f'|format(c.sma200)}} <span class="mut">({{'above' if c.price>c.sma200 else 'BELOW'}})</span></span>
<b>SMA 5</b><span>{{'%.2f'|format(c.sma5)}}</span>
<b>Entry signal</b><span class="{{'ok' if c.entry_signal else 'mut'}}">{{'YES' if c.entry_signal else 'no'}}</span>
<b>Exit signal</b><span>{{c.exit_signal or '—'}}</span>
<b>Last bar</b><span>{{c.last_bar}}</span></div>{% endif %}
</div>
<div class="card"><h2>Account ({{d.mode}})</h2>
{% if d.ledger %}<div class="big">${{'{:,.0f}'.format(d.ledger.cash + (s.qty or 0)*(c.price or 0))}}</div>
<div class="kv"><b>Cash</b><span>${{'{:,.2f}'.format(d.ledger.cash)}}</span>
<b>Fills</b><span>{{d.ledger.fills|length}}</span>
<b>Last reconcile</b><span>{{(s.last_reconcile or '—')[:16]}}</span>
<b>Last decide</b><span>{{s.last_decide or '—'}}</span></div>
{% else %}<p class="mut">Live account: run <code>python bot.py status</code> for balances.</p>{% endif %}
<p style="margin-top:12px"><a class="btn" href="/run/check">Re-check signal</a><a class="btn sec" href="/run/reconcile">Run reconcile</a></p>
</div>
<div class="card wide"><h2>Trades (paper ledger)</h2>
{% if d.ledger.fills %}<table><tr><th>Date</th><th>Type</th><th>Qty</th><th>Fill</th></tr>
{% for f in d.ledger.fills|reverse %}<tr><td>{{f.date}}</td><td>{{f.kind}}</td><td>{{f.qty}}</td><td>{{'%.2f'|format(f.fill)}}</td></tr>{% endfor %}</table>
{% else %}<p class="mut">No trades yet. The strategy fires about 5 times a year; a quiet ledger is normal.</p>{% endif %}</div>
<div class="card wide"><h2>Log (last 40 lines)</h2><pre>{{d.log|join('\n') or 'empty'}}</pre></div>
</main></body></html>"""


@app.route("/")
def index():
    return render_template_string(PAGE, d=snapshot())


@app.route("/run/<cmd>")
def run(cmd):
    if cmd in ("check", "reconcile"):
        _run(cmd)
    return redirect("/")


@app.route("/api")
def api():
    return jsonify(snapshot())


if __name__ == "__main__":
    print("Dashboard: http://127.0.0.1:8585  (Ctrl+C to stop)")
    app.run(host="127.0.0.1", port=8585, debug=False)
