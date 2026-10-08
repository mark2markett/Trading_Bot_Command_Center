import importlib.util
import json
import sqlite3
from pathlib import Path

import httpx

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
