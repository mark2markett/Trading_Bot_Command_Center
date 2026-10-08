import importlib.util
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import httpx
import pytest

spec = importlib.util.spec_from_file_location('probe', Path(__file__).with_name('DIAGNOSE-SIP-OPENING.py'))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def bars(start, offsets):
    return {'candles': [{'datetime': int(start.timestamp()*1000) + offset*60000,
                         'open': 10, 'high': 11, 'low': 9, 'close': 10, 'volume': 100}
                        for offset in offsets]}


def test_narrow_window_gap_recovered_by_wider_request():
    start = probe.opening_start('2026-10-08')
    def read(symbol, begin, end):
        return bars(start, range(1, 5) if begin == start else range(-5, 10))
    result = probe.inspect_symbol('AMD', start, read)
    assert result['exact_window']['missing_minutes'] == ['09:30']
    assert result['wider_request_window']['complete']
    assert result['finding'] == 'REQUEST_BOUNDARY_DIFFERENCE'


def test_persistent_vendor_gap_is_not_filled_with_zero():
    start = probe.opening_start('2026-10-08')
    result = probe.inspect_symbol('AMD', start, lambda *args: bars(start, [0, 1, 3, 4]))
    assert result['finding'] == 'OPENING_DATA_STILL_INCOMPLETE'
    assert result['wider_request_window']['missing_minutes'] == ['09:32']


def test_duplicate_or_bad_bars_do_not_pass_as_complete():
    start = probe.opening_start('2026-10-08')
    assert not probe.window_summary(bars(start, [0, 0, 1, 2, 3, 4]), start)['complete']
    data = bars(start, range(5))
    data['candles'][0]['volume'] = -1
    assert not probe.window_summary(data, start)['complete']


def test_valid_exact_window_does_not_make_extra_provider_request():
    start = probe.opening_start('2026-10-08')
    calls = []
    def read(symbol, begin, end):
        calls.append(symbol)
        return bars(start, range(5))
    assert probe.inspect_symbol('AMD', start, read)['finding'] == 'COMPLETE_NOW'
    assert len(calls) == 1


def test_preparation_cache_selects_only_eligible_stocks_without_saved_opening_data():
    requests = []
    def handler(request):
        requests.append(request)
        if '/get/' in request.url.path:
            return httpx.Response(200, json={'result': json.dumps({
                'session_date': '2026-10-08', 'complete': True,
                'rows': [{'symbol': 'AMD'}, {'symbol': 'NVDA'}]})})
        return httpx.Response(200, json={'result': [json.dumps({'opening_volume': 200}), None]})
    values = {'UPSTASH_REDIS_REST_URL': 'https://example.upstash.io', 'UPSTASH_REDIS_REST_TOKEN': 'secret'}
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        symbols, evidence = probe.targets(values, client, '2026-10-08', ['AMD', 'NVDA', 'AAPL'])
    assert symbols == ['NVDA']
    assert evidence == {'source': 'preparation_cache', 'eligible': 2, 'missing_opening_cache': 1}
    assert all(request.method == 'GET' for request in requests)
    assert 'secret' not in json.dumps(evidence)


def test_provider_extra_fields_never_enter_diagnostic_report():
    start = probe.opening_start('2026-10-08')
    data = bars(start, range(5))
    data['error'] = 'secret-never-in-report'
    assert 'secret-never-in-report' not in json.dumps(probe.inspect_symbol('AMD', start, lambda *args: data))


def test_open_intraday_position_refuses_probe_without_writing_ledger(tmp_path):
    path = tmp_path/'cc.db'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE positions(bot_id TEXT,qty REAL)')
        connection.execute("INSERT INTO positions VALUES('nr7',-90)")
    before = path.read_bytes()
    assert not probe.positions_clear(path)
    assert path.read_bytes() == before


def test_overnight_daily_position_does_not_block_after_close_probe(tmp_path):
    path = tmp_path/'cc.db'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE positions(bot_id TEXT,qty REAL)')
        connection.execute("INSERT INTO positions VALUES('spy_mr',50)")
    assert probe.positions_clear(path)


def test_probe_uses_working_shared_sdk_auth_when_broker_is_disabled(tmp_path, monkeypatch):
    from cc_sdk import schwab_feed
    monkeypatch.setattr(schwab_feed, 'REPO_ROOT', tmp_path)
    for key, value in {
        'SCHWAB_CLIENT_ID': 'fixture-id', 'SCHWAB_CLIENT_SECRET': 'fixture-client-secret',
        'SUPABASE_URL': 'https://example.supabase.co', 'SUPABASE_SERVICE_ROLE_KEY': 'fixture-service-key',
        'CC_TOKEN_BROKER_URL': 'https://disabled.example/broker', 'CC_TOKEN_BROKER_SECRET': 'b'*32,
    }.items():
        monkeypatch.setenv(key, value)
    start = probe.opening_start('2026-10-08')
    def handler(request):
        if request.url.host == 'disabled.example':
            return httpx.Response(404)
        if request.url.host == 'example.supabase.co':
            return httpx.Response(200, json=[{'schwab_token_state': {'refresh_token': 'fixture-refresh'}}])
        if request.url.path == '/v1/oauth/token':
            return httpx.Response(200, json={'access_token': 'a'*40, 'expires_in': 1800})
        return httpx.Response(200, json=bars(start, range(5)))
    feed = probe.connect_feed(tmp_path, transport=httpx.MockTransport(handler))
    assert probe.window_summary(probe.read_market_bars(feed, 'AMD', start, start), start)['complete']


def test_failed_http_stage_is_recorded_without_url_or_credentials(tmp_path, monkeypatch):
    class AfterClose(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 8, 17, 0, tzinfo=probe.ET)
    monkeypatch.setattr(probe, 'datetime', AfterClose)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(sys, 'argv', ['probe', '--repo', str(tmp_path), '--date', '2026-10-08'])
    (tmp_path/'Desktop').mkdir()
    (tmp_path/'.env.local').write_text('CC_TOKEN_BROKER_URL=https://disabled.example/broker\nCC_TOKEN_BROKER_SECRET=' + 'b'*32)
    for key in ('CC_TOKEN_BROKER_URL','CC_TOKEN_BROKER_SECRET'):
        monkeypatch.delenv(key, raising=False)
    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(
        lambda request: httpx.Response(404, json={'error': 'secret-never-in-report'})), **kwargs))
    assert probe.main() == 1
    report = json.loads(next((tmp_path/'Desktop').glob('CC-sip-opening-*.json')).read_text())
    assert report['failed_stage'] == 'server_health'
    assert report['http_status'] == 404
    assert 'secret-never-in-report' not in json.dumps(report)


@pytest.mark.parametrize('provider_status', [200, 404])
def test_full_probe_uses_shared_auth_and_identifies_market_errors(tmp_path, monkeypatch, provider_status):
    from cc_sdk import schwab_feed
    class AfterClose(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 8, 17, 0, tzinfo=probe.ET)
    monkeypatch.setattr(probe, 'datetime', AfterClose)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(sys, 'argv', ['probe', '--repo', str(tmp_path), '--date', '2026-10-08'])
    monkeypatch.setattr(schwab_feed, 'REPO_ROOT', tmp_path)
    for key, value in {
        'SCHWAB_CLIENT_ID': 'fixture-id', 'SCHWAB_CLIENT_SECRET': 'fixture-client-secret',
        'SUPABASE_URL': 'https://example.supabase.co', 'SUPABASE_SERVICE_ROLE_KEY': 'fixture-service-key',
        'CC_TOKEN_BROKER_URL': 'https://disabled.example/broker', 'CC_TOKEN_BROKER_SECRET': 'b'*32,
        'UPSTASH_REDIS_REST_URL': 'https://example.upstash.io', 'UPSTASH_REDIS_REST_TOKEN': 'fixture-redis-secret',
    }.items():
        monkeypatch.setenv(key, value)
    (tmp_path/'Desktop').mkdir()
    ledger = tmp_path/'cc.db'
    with sqlite3.connect(ledger) as connection:
        connection.execute('CREATE TABLE positions(bot_id TEXT,qty REAL)')
    before = ledger.read_bytes()
    start = probe.opening_start('2026-10-08')
    def handler(request):
        if request.url.host == '127.0.0.1':
            return httpx.Response(200, json={'db': str(ledger)})
        if request.url.host == 'disabled.example':
            return httpx.Response(404)
        if request.url.host == 'example.supabase.co':
            return httpx.Response(200, json=[{'schwab_token_state': {'refresh_token': 'fixture-refresh'}}])
        if request.url.host == 'example.upstash.io':
            if '/get/' in request.url.path:
                return httpx.Response(200, json={'result': json.dumps({
                    'session_date': '2026-10-08', 'complete': True, 'rows': [{'symbol': 'NVDA'}]})})
            return httpx.Response(200, json={'result': [None]})
        if request.url.path == '/v1/oauth/token':
            return httpx.Response(200, json={'access_token': 'a'*40, 'expires_in': 1800})
        return httpx.Response(provider_status, json=bars(start, range(5)))
    original = httpx.Client
    def client(**kwargs):
        if kwargs.get('transport') is None:
            kwargs['transport'] = httpx.MockTransport(handler)
        return original(**kwargs)
    monkeypatch.setattr(httpx, 'Client', client)
    assert probe.main() == (0 if provider_status == 200 else 1)
    report = json.loads(next((tmp_path/'Desktop').glob('CC-sip-opening-*.json')).read_text())
    assert report['authentication'] == 'shared_state'
    if provider_status == 200:
        assert report['scan_complete'] and report['results'][0]['finding'] == 'COMPLETE_NOW'
    else:
        assert not report['scan_complete'] and report['failed_stage'] == 'market_data'
        assert report['http_status'] == 404 and report['failed_symbol'] == 'NVDA'
    assert ledger.read_bytes() == before
    assert 'fixture-client-secret' not in json.dumps(report)
