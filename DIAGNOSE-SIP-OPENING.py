"""Bounded market-data diagnosis; no orders, controls, registration or source edits."""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo

import httpx
from dotenv import dotenv_values

ET = ZoneInfo('America/New_York')


def opening_start(day):
    return datetime.fromisoformat(day).replace(hour=9, minute=30, tzinfo=ET)


def window_summary(data, start):
    expected = [int((start + timedelta(minutes=i)).timestamp()*1000) for i in range(5)]
    candles = data.get('candles') if isinstance(data, dict) else None
    if not isinstance(candles, list):
        raise TypeError('Provider schema')
    window = [b for b in candles if isinstance(b, dict) and type(b.get('datetime')) in (int, float)
              and expected[0] <= b['datetime'] < expected[-1] + 60000]
    times = [b['datetime'] for b in window]
    invalid = 0
    for bar in window:
        fields = [bar.get(k) for k in ('open', 'high', 'low', 'close', 'volume')]
        if not all(type(v) in (int, float) and math.isfinite(v) for v in fields):
            invalid += 1
            continue
        o, h, low, c, v = fields
        if not (o > 0 and c > 0 and low > 0 and h >= max(o, c) and low <= min(o, c) and v >= 0):
            invalid += 1
    missing = [f'09:{30+i:02d}' for i, at in enumerate(expected) if at not in times]
    return {'bar_count': len(window), 'missing_minutes': missing, 'invalid_bars': invalid,
            'complete': len(window) == 5 and sorted(times) == expected and invalid == 0}


def inspect_symbol(symbol, start, read):
    exact = window_summary(read(symbol, start, start + timedelta(minutes=5)), start)
    result = {'symbol': symbol, 'exact_window': exact, 'finding': 'COMPLETE_NOW'}
    if not exact['complete']:
        wide = window_summary(read(symbol, start - timedelta(minutes=5), start + timedelta(minutes=10)), start)
        result.update(wider_request_window=wide, finding='REQUEST_BOUNDARY_DIFFERENCE' if wide['complete']
                      else 'OPENING_DATA_STILL_INCOMPLETE')
    return result


def configuration(root):
    values = dict(os.environ)
    for path, override in ((root/'bots/sip_orb/.env', False), (root/'bots/sip_orb/.env.local', True),
                           (root/'.env.local', False)):
        for key, value in dotenv_values(path).items():
            if value is not None and (override or key not in values):
                values[key] = value
    return values


def private_url(url, host_suffix=None):
    parsed = urlsplit(url)
    return (parsed.scheme == 'https' and bool(parsed.hostname) and not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment
            and (host_suffix is None or parsed.hostname.endswith(host_suffix)))


def positions_clear(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)) as connection:
        return connection.execute("SELECT 1 FROM positions WHERE bot_id IN ('gap_go','gap_go_spread','nr7','sip_orb') AND qty<>0 LIMIT 1").fetchone() is None


def targets(values, client, day, fallback):
    """Prefer eligible symbols with missing publication cache, using only Redis GET/MGET."""
    url, token = values.get('UPSTASH_REDIS_REST_URL', ''), values.get('UPSTASH_REDIS_REST_TOKEN', '')
    if not token or not private_url(url, '.upstash.io'):
        return fallback, {'source': 'classified_universe', 'note': 'Preparation-cache configuration unavailable; eligibility is not asserted.'}
    prefix = 'cc:sip:v1:' + day + ':'
    headers = {'Authorization': 'Bearer ' + token}
    def read(command, keys):
        response = client.get(url.rstrip('/') + '/' + command + '/' + '/'.join(quote(k, safe='') for k in keys), headers=headers)
        response.raise_for_status()
        result = response.json()['result']
        return json.loads(result) if isinstance(result, str) else result
    prep = read('get', [prefix + 'preparation'])
    if not isinstance(prep, dict) or prep.get('session_date') != day or prep.get('complete') is not True:
        return fallback, {'source': 'classified_universe', 'note': 'No complete current-session preparation read; eligibility is not asserted.'}
    symbols = [row['symbol'] for row in prep['rows'] if isinstance(row, dict) and row.get('symbol') in fallback]
    if len(symbols) != len(prep['rows']) or len(set(symbols)) != len(symbols):
        raise ValueError('Preparation schema')
    missing = []
    for offset in range(0, len(symbols), 30):
        chunk = symbols[offset:offset+30]
        cached = read('mget', [prefix + 'symbol:opening:' + symbol for symbol in chunk])
        if not isinstance(cached, list) or len(cached) != len(chunk):
            raise ValueError('Opening cache schema')
        for symbol, value in zip(chunk, cached):
            value = json.loads(value) if isinstance(value, str) else value
            volume = value.get('opening_volume') if isinstance(value, dict) else None
            if not (type(volume) in (int, float) and math.isfinite(volume) and volume >= 0):
                missing.append(symbol)
    return missing, {'source': 'preparation_cache', 'eligible': len(symbols), 'missing_opening_cache': len(missing)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    parser.add_argument('--date', default=datetime.now(ET).date().isoformat())
    args = parser.parse_args()
    start = opening_start(args.date)
    now = datetime.now(ET)
    if now < start + timedelta(minutes=10) or (now.weekday() < 5 and 540 <= now.hour*60 + now.minute < 970):
        parser.error('Run after 16:10 ET; this diagnostic does not add provider load during the trading session.')
    root = args.repo.resolve()
    values = configuration(root)
    url, secret = values.get('CC_TOKEN_BROKER_URL', ''), values.get('CC_TOKEN_BROKER_SECRET', '')
    output = {'collected_at': datetime.now(ET).isoformat(), 'session_date': args.date, 'results': [],
              'note': 'Later data cannot prove what the provider returned at 09:35. No watchlist is published or bot restarted.'}
    code = 0
    try:
        if not private_url(url) or len(secret) < 32:
            raise ValueError('Existing token broker configuration required')
        fallback = json.loads(Path(__file__).with_name('SIP-DIAGNOSTIC-UNIVERSE.json').read_text())['symbols']
        with httpx.Client(timeout=12, follow_redirects=False) as client:
            health = client.get('http://127.0.0.1:8585/api/health')
            health.raise_for_status()
            if not positions_clear(Path(health.json()['db'])):
                output['blocked_reason'] = 'OPEN_INTRADAY_POSITION'
                raise ValueError('Open position; defer market-data diagnosis')
            response = client.get(url, headers={'Authorization': 'Bearer ' + secret, 'X-CC-Bot': 'sip_orb'})
            response.raise_for_status()
            body = response.json()
            token = body.get('access_token') if isinstance(body, dict) else None
            if not isinstance(token, str) or len(token) < 20:
                raise ValueError('Broker response schema')
            try:
                symbols, evidence = targets(values, client, args.date, fallback)
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
                symbols, evidence = fallback, {'source': 'classified_universe', 'cache_error_type': type(error).__name__}
            output['selection'] = evidence
            output['target_count'] = len(symbols)
            deadline = time.monotonic() + 600
            last_request = 0.0
            def read(symbol, begin, end):
                nonlocal last_request
                if time.monotonic() >= deadline:
                    raise TimeoutError('Diagnostic deadline')
                time.sleep(max(0, 1.0 - (time.monotonic() - last_request)))
                last_request = time.monotonic()
                response = client.get('https://api.schwabapi.com/marketdata/v1/pricehistory',
                    headers={'Authorization': 'Bearer ' + token}, params={
                        'symbol': symbol, 'periodType': 'day', 'frequencyType': 'minute', 'frequency': '1',
                        'startDate': str(int(begin.timestamp()*1000)), 'endDate': str(int(end.timestamp()*1000)),
                        'needExtendedHoursData': 'false'})
                response.raise_for_status()  # Stop on throttling; never loop past a 429.
                return response.json()
            for symbol in symbols:
                result = inspect_symbol(symbol, start, read)
                output['results'].append(result)
                if result['finding'] != 'COMPLETE_NOW':
                    print(json.dumps(result), flush=True)
                if len(output['results']) % 25 == 0:
                    print(f"Checked {len(output['results'])}/{len(symbols)} stocks", flush=True)
            output['scan_complete'] = True
    except (httpx.HTTPError, sqlite3.Error, OSError, ValueError, KeyError, TypeError) as error:
        output.update(scan_complete=False, error_type=type(error).__name__)
        if isinstance(error, httpx.HTTPStatusError):
            output['http_status'] = error.response.status_code
        code = 1
    desktop = Path.home()/'Desktop'
    path = (desktop if desktop.is_dir() else root/'var')/('CC-sip-opening-' + datetime.now(ET).strftime('%Y%m%d-%H%M%S') + '.json')
    path.write_text(json.dumps(output, indent=2)+'\n', encoding='utf-8')
    print('Upload this diagnostic file: ' + str(path), flush=True)
    if code:
        print('Diagnostic stopped: ' + output['error_type'] + '; partial results retained.', flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
