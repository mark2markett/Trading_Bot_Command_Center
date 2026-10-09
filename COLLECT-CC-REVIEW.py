"""Read-only native evidence: online ledger backup, API state, scanner probe.

Writes only to the supplied review directory. Never instantiate a bot, register a
manifest, place an order, change controls, or export environment/credential files.
"""
import importlib.util
import json
import math
import os
import re
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

sys.dont_write_bytecode = True


def save(path, data):
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def backup(source, target):
    started = time.monotonic()

    def progress(status, remaining, total):
        if time.monotonic() - started > 20:
            raise TimeoutError("online backup deadline")

    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=5) as src:
        with sqlite3.connect(target) as dst:
            src.backup(dst, pages=256, progress=progress)
            if dst.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("backup integrity check failed")


def opening_context(details):
    """Export only bounded, typed public-symbol/minute diagnostics."""
    count, failures = details.get('opening_failure_count'), details.get('opening_failures')
    if type(count) is not int or count < 0 or not isinstance(failures, list):
        return {}
    clean = []
    for row in failures[:10]:
        if not isinstance(row, dict):
            continue
        symbol, date = row.get('symbol'), row.get('session_date')
        if not isinstance(symbol, str) or not re.fullmatch(r'[A-Z][A-Z0-9.]{0,9}', symbol):
            continue
        if not isinstance(date, str) or not re.fullmatch(r'202[5-7]-\d{2}-\d{2}', date):
            continue
        if row.get('reason') not in ('OPENING_WINDOW_INCOMPLETE', 'OPENING_WINDOW_INVALID'):
            continue
        try:
            from datetime import timedelta, timezone
            start = datetime.fromisoformat(date).replace(hour=9, minute=30, tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc)
            end = start + timedelta(minutes=5)
            def minute(value):
                if not isinstance(value, str) or len(value) > 40:
                    return None
                try:
                    at = datetime.fromisoformat(value.replace('Z', '+00:00'))
                    return at.astimezone(timezone.utc).isoformat() if at.tzinfo and start <= at < end else None
                except (ValueError, TypeError, OverflowError):
                    return None
            returned = row.get('returned_minutes')
            missing = row.get('missing_minutes')
            amount = row.get('returned_window_count')
            if (type(amount) is not int or amount < 0 or not isinstance(returned, list)
                    or not isinstance(missing, list) or type(row.get('returned_minutes_truncated')) is not bool):
                continue
            clean.append({'symbol': symbol, 'session_date': date, 'reason': row['reason'],
                          'window_start': start.isoformat(), 'window_end': end.isoformat(),
                          'returned_window_count': amount,
                          'returned_minutes': [at for value in returned[:10] if (at := minute(value))],
                          'returned_minutes_truncated': row['returned_minutes_truncated'],
                          'missing_minutes': [at for value in missing[:5] if (at := minute(value))]})
        except (ValueError, TypeError, OverflowError):
            continue
    return {'opening_failure_count': count, 'opening_failures': clean}


def platform_enrich_probe(root, *, cron_name="enrich"):
    """Bounded GET-only telemetry using existing shared credentials, kept in memory."""
    import httpx
    from dotenv import dotenv_values

    if cron_name not in ("enrich", "cc-sip-scanner"):
        raise ValueError("Unsupported telemetry job")
    values = dotenv_values(Path(root) / '.env.local')
    url = (os.getenv('SUPABASE_URL') or values.get('SUPABASE_URL') or '').strip()
    key = (os.getenv('SUPABASE_SERVICE_ROLE_KEY') or values.get('SUPABASE_SERVICE_ROLE_KEY') or '').strip()
    parsed = urlparse(url)
    if (not key or parsed.scheme != 'https' or not (parsed.hostname or '').endswith('.supabase.co')
            or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        return {'probe_performed': False, 'reason': 'Existing shared database configuration absent or unsupported'}
    output = {'probe_performed': True, 'probe_status': {}, 'cron_runs': [], 'latest_enriched_at': None, 'eligibility_reads': {}}

    def timestamp(value):
        try:
            at = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return at.isoformat() if at.tzinfo else None
        except (AttributeError, ValueError, TypeError):
            return None

    with httpx.Client(timeout=8, follow_redirects=False) as client:
        def read(table, query):
            try:
                response = client.get(url.rstrip('/') + '/rest/v1/' + table,
                                      params=query, headers={'apikey': key, 'Authorization': 'Bearer ' + key})
                output['probe_status'][table] = response.status_code
                data = response.json() if response.status_code == 200 else []
                if not isinstance(data, list):
                    output['probe_status'][table] = 'INVALID_RESPONSE'
                    return []
                return data
            except (httpx.RequestError, ValueError) as error:
                output['probe_status'][table] = type(error).__name__
                return []

        query = {'cron_name': 'eq.' + cron_name, 'order': 'started_at.desc', 'limit': '8',
                 'select': 'status,started_at,finished_at,details'}
        if cron_name == 'cc-sip-scanner':
            today = datetime.now(ZoneInfo('America/New_York')).replace(hour=0, minute=0, second=0, microsecond=0)
            query.update({'started_at': 'gte.' + today.isoformat(), 'limit': '40'})
        rows = read('cron_runs', query)
        fields = ('trades', 'enriched', 'upsertErrors', 'chartNewsFetched', 'aiPlansGenerated', 'durationMs', 'skippedFresh')
        if cron_name == 'cc-sip-scanner':
            fields = ('universe', 'classificationExcluded', 'failures')
        safe_codes = {'SIP_SCANNER_CONFIGURATION', 'SIP_SCANNER_FAILED', 'SIP_TELEMETRY_FAILED',
                      'SIP_LOCK_LOST', 'SIP_LOCK_RELEASE_FAILED', 'SIP_STORAGE_FAILED', 'SIP_STORAGE_UNCONFIGURED',
                      'SIP_SNAPSHOT_INVALID', 'PREPARATION_INCOMPLETE', 'PREPARATION_BUDGET', 'PREPARATION_FAILED',
                      'PUBLICATION_BUDGET', 'PUBLICATION_TOO_LATE', 'OUTSIDE_PUBLISH_WINDOW', 'CALENDAR_UNSUPPORTED',
                      'SCHWAB_AUTH_FAILED', 'SCHWAB_REQUEST_FAILED', 'SCHWAB_SCHEMA', 'SCHWAB_QUOTE_STALE',
                      'OPENING_WINDOW_INCOMPLETE', 'OPENING_WINDOW_INVALID',
                      'SIP_TESTING_BYPASS_INVALID_PREPARATION', 'SIP_TESTING_BYPASS_INVALID_SYMBOL',
                      'SIP_TESTING_BYPASS_NOT_ACTIVE', 'SIP_TESTING_BYPASS_EXPIRED'}
        for row in rows:
            if not isinstance(row, dict):
                continue
            details = row.get('details')
            details = details if isinstance(details, dict) else {}
            counts = {name: details[name] for name in fields if type(details.get(name)) in (int, float) and math.isfinite(details[name])}
            output['cron_runs'].append({'status': row.get('status') if row.get('status') in ('started', 'success', 'failure', 'degraded') else None,
                                       'started_at': timestamp(row.get('started_at')), 'finished_at': timestamp(row.get('finished_at')),
                                       'counts': counts, 'error_present': bool(details.get('error'))})
            if cron_name == 'cc-sip-scanner':
                output['cron_runs'][-1].update({
                    'phase': details.get('phase') if details.get('phase') in ('prepare', 'publish') else None,
                    'producer_status': details.get('status') if details.get('status') in ('busy', 'pending', 'prepared', 'publish_ready') else None,
                    'error_code': details.get('error') if isinstance(details.get('error'), str) and
                    (details['error'] in safe_codes or re.fullmatch(r'SCHWAB_HTTP_[1-5]\d{2}', details['error'])) else None,
                })
                output['cron_runs'][-1].update(opening_context(details))
        if cron_name == 'cc-sip-scanner':
            return output
        rows = read('trade_enrichments', {'order': 'enriched_at.desc', 'limit': '1', 'select': 'enriched_at'})
        if rows and isinstance(rows[0], dict):
            output['latest_enriched_at'] = timestamp(rows[0].get('enriched_at'))
        from datetime import timedelta, timezone
        since = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
        # Match the enrich route's published score/status/date predicates.
        queries = {
            'scanner_picks': {'status': 'in.(new,active)', 'quality_score': 'gte.80', 'signal_date': 'gte.' + since},
            'flow_alerts': {'outcome': 'eq.open', 'squeeze_score': 'gte.80', 'trigger_time': 'gte.' + since + 'T00:00:00Z'},
            'setups': {'status': 'eq.open', 'quality_score_total': 'gte.80', 'date_published': 'gte.' + since},
        }
        for table, query in queries.items():
            rows = read(table, {**query, 'select': 'id', 'limit': '1'})
            status = output['probe_status'][table]
            output['eligibility_reads'][table] = {'http_status': status, 'eligible_row_seen': bool(rows) if status == 200 else None}
    return output


def main(root, review):
    root, review = Path(root).resolve(), Path(review).resolve()
    # /bots and /fleet recompute parity and WRITE kv/alerts. Never request
    # those endpoints from an evidence collector; bot state comes from backup.
    for endpoint in ("health", "risk", "alerts", "research", "readiness"):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8585/api/" + endpoint, timeout=10) as response:
                data = json.load(response)
            save(review / (endpoint + ".json"), data)
        except Exception as error:
            save(review / (endpoint + "-status.json"), {"responding": False, "error_type": type(error).__name__})
    runtime = Path(os.environ.get("CC_VAR", str(root / "var"))).resolve()
    backup(runtime / "cc.db", review / "ledger.db")
    with sqlite3.connect((review / "ledger.db").as_uri() + "?mode=ro", uri=True) as ledger:
        ledger.row_factory = sqlite3.Row
        bots = []
        for bot in ledger.execute("SELECT id,name,mode,status FROM bots ORDER BY id").fetchall():
            row = dict(bot)
            heartbeat = ledger.execute("SELECT run,at,ok,detail FROM heartbeats WHERE bot_id=? ORDER BY id DESC LIMIT 1", (row["id"],)).fetchone()
            row["heartbeat"] = dict(heartbeat) if heartbeat else None
            row["positions"] = [dict(p) for p in ledger.execute("SELECT symbol,qty,avg_price FROM positions WHERE bot_id=?", (row["id"],))]
            bots.append(row)
        save(review / "bots.json", {"source": "read-only backup; stored status, no watchdog/parity recomputation", "bots": bots})
        configured = ledger.execute("SELECT 1 FROM kv WHERE key='paper_account'").fetchone()
        if configured:
            from contextlib import nullcontext
            sys.path.insert(0,str(root/'cc_sdk'))
            from cc_sdk.paper_account import snapshot
            class ReadOnlyLedger:
                def one(self,sql,params=()): return ledger.execute(sql,params).fetchone()
                def q(self,sql,params=()): return ledger.execute(sql,params).fetchall()
                def transaction(self,**kwargs): return nullcontext()  # immutable completed backup, no concurrent writer
            state=snapshot(ReadOnlyLedger())
            last=ledger.execute('SELECT at,equity FROM paper_equity ORDER BY id DESC LIMIT 1').fetchone()
            save(review/'fleet-readiness.json',{'account_equity_present':True,'account_equity_valid':state['ready'],
                 'source':'paper','account':state,'last_valid_valuation':dict(last) if last else None,
                 'warning':None if state['ready'] else state['reason']})
        else:
            equity = ledger.execute("SELECT at,equity FROM equity WHERE source='broker' ORDER BY at DESC,id DESC LIMIT 1").fetchone()
            value = equity[1] if equity else None
            save(review / "fleet-readiness.json", {
                "account_equity_present": equity is not None,
                "account_equity_valid": isinstance(value, (int, float)) and math.isfinite(value) and value > 0,
                "account_equity": value,
                "account_equity_at": equity[0] if equity else None,
                "warning": None if equity else "Fleet gross-exposure/drawdown protection has no account equity basis.",
            })
    # Match the SIP command's env order: existing process, .env defaults,
    # then .env.local overrides. Values remain in-process only.
    from dotenv import load_dotenv
    bot_dir = root / "bots" / "sip_orb"
    load_dotenv(bot_dir / ".env")
    load_dotenv(bot_dir / ".env.local", override=True)
    url = os.getenv("SCANNER_URL", "").strip()
    result = {
        "scanner_url_present": bool(url),
        "scanner_secret_configured": len(os.getenv("SCANNER_SECRET", "")) >= 32,
        "fallback_configured": bool(os.getenv("SIP_SYMBOLS", "").strip()),
    }
    client = bot_dir / "sip_scanner.py"
    if url and result["scanner_secret_configured"] and client.is_file():
        sys.path.insert(0, str(root / "cc_sdk"))
        try:
            spec = importlib.util.spec_from_file_location("native_review_sip", client)
            scanner = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(scanner)
            payload = scanner.fetch(url, timeout=10)
            now = datetime.now(ZoneInfo("America/New_York"))
            result.update({"endpoint_ready": True, "checked_at": now.isoformat(),
                           "version": payload.get("version"), "session_date": payload.get("session_date"),
                           "generated_at": payload.get("generated_at"), "coverage": payload.get("coverage")})
            try:
                result["fresh_selected_symbols"] = scanner.parse_snapshot(payload, now)
                result["valid_and_fresh_now"] = True
            except Exception:
                result["valid_and_fresh_now"] = False
                result["note"] = "Snapshot is stale or invalid at collection time; late-day staleness is expected. Review morning SCANNER decisions separately."
        except Exception as error:
            result.update({"endpoint_ready": False, "error_type": type(error).__name__})
    else:
        result["probe_performed"] = False
    save(review / "scanner-status.json", result)
    save(review / "platform-enrich.json", platform_enrich_probe(root))
    save(review / "platform-sip.json", platform_enrich_probe(root, cron_name='cc-sip-scanner'))
    monitor_report = root / 'var' / 'monitor' / 'latest.json'
    if monitor_report.is_file():
        save(review / 'native-monitor.json', json.loads(monitor_report.read_text(encoding='utf-8')))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
