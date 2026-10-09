import importlib.util
import json
from pathlib import Path

import httpx

spec = importlib.util.spec_from_file_location("collector", Path(__file__).with_name("COLLECT-CC-REVIEW.py"))
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


def test_probe_exports_counts_and_status_without_credentials_or_raw_error_details(tmp_path, monkeypatch):
    secret = "secret-never-in-the-report"
    (tmp_path / '.env.local').write_text(f'SUPABASE_URL=https://example.supabase.co\nSUPABASE_SERVICE_ROLE_KEY={secret}\n')
    monkeypatch.delenv('SUPABASE_URL', raising=False)
    monkeypatch.delenv('SUPABASE_SERVICE_ROLE_KEY', raising=False)
    original = httpx.Client

    def handler(request):
        if request.url.path.endswith('/cron_runs'):
            return httpx.Response(200, json=[{'status': 'success', 'started_at': '2026-10-08T13:50:00Z',
                                            'finished_at': '2026-10-08T13:50:05Z',
                                            'details': {'trades': 0, 'enriched': 0, 'upsertErrors': 0,
                                                        'error': secret, 'message': secret, 'arbitrary': secret}}])
        return httpx.Response(200, json=[])

    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    result = collector.platform_enrich_probe(tmp_path)
    assert result['cron_runs'][0]['counts']['trades'] == 0
    assert result['latest_enriched_at'] is None
    assert all(r['eligible_row_seen'] is False for r in result['eligibility_reads'].values())
    assert secret not in json.dumps(result)


def test_probe_refuses_redirects_and_reports_http_status_instead_of_following(tmp_path, monkeypatch):
    (tmp_path / '.env.local').write_text('SUPABASE_URL=https://example.supabase.co\nSUPABASE_SERVICE_ROLE_KEY=secret\n')
    monkeypatch.delenv('SUPABASE_URL', raising=False)
    monkeypatch.delenv('SUPABASE_SERVICE_ROLE_KEY', raising=False)
    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(
        lambda request: httpx.Response(302, headers={'Location': 'https://untrusted.example/'})), **kwargs))
    result = collector.platform_enrich_probe(tmp_path)
    assert result['probe_status']['cron_runs'] == 302
    assert result['cron_runs'] == []
    assert result['eligibility_reads']['scanner_picks']['http_status'] == 302


def test_sip_probe_preserves_producer_failure_code_without_raw_details(tmp_path, monkeypatch):
    secret = 'secret-never-in-the-report'
    (tmp_path / '.env.local').write_text(f'SUPABASE_URL=https://example.supabase.co\nSUPABASE_SERVICE_ROLE_KEY={secret}\n')
    monkeypatch.delenv('SUPABASE_URL', raising=False)
    monkeypatch.delenv('SUPABASE_SERVICE_ROLE_KEY', raising=False)
    original = httpx.Client

    def handler(request):
        assert request.method == 'GET'
        assert request.url.path.endswith('/cron_runs')
        assert request.url.params['cron_name'] == 'eq.cc-sip-scanner'
        assert request.url.params['started_at'].startswith('gte.')
        return httpx.Response(200, json=[{
            'status': 'failure', 'started_at': '2026-10-08T13:35:00Z',
            'finished_at': '2026-10-08T13:35:04Z',
            'details': {'phase': 'publish', 'error': 'PREPARATION_INCOMPLETE',
                        'universe': 500, 'failures': 4, 'message': secret},
        }, {'status': 'failure', 'details': {'error': secret, 'phase': secret}},
          {'status': 'failure', 'details': {'error': 'SCHWAB_HTTP_500'}}])

    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    result = collector.platform_enrich_probe(tmp_path, cron_name='cc-sip-scanner')
    row = result['cron_runs'][0]
    assert row['error_code'] == 'PREPARATION_INCOMPLETE'
    assert row['phase'] == 'publish'
    assert row['counts'] == {'universe': 500, 'failures': 4}
    assert result['cron_runs'][1]['error_code'] is None
    assert result['cron_runs'][2]['error_code'] == 'SCHWAB_HTTP_500'
    assert secret not in json.dumps(result)


def test_sip_probe_does_not_claim_absent_jobs_when_telemetry_is_denied(tmp_path, monkeypatch):
    (tmp_path / '.env.local').write_text('SUPABASE_URL=https://example.supabase.co\nSUPABASE_SERVICE_ROLE_KEY=secret\n')
    monkeypatch.delenv('SUPABASE_URL', raising=False)
    monkeypatch.delenv('SUPABASE_SERVICE_ROLE_KEY', raising=False)
    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(
        lambda request: httpx.Response(403)), **kwargs))
    result = collector.platform_enrich_probe(tmp_path, cron_name='cc-sip-scanner')
    assert result['probe_status']['cron_runs'] == 403
    assert result['cron_runs'] == []


def test_sip_probe_exports_bounded_opening_context_without_arbitrary_details(tmp_path, monkeypatch):
    (tmp_path / '.env.local').write_text('SUPABASE_URL=https://example.supabase.co\nSUPABASE_SERVICE_ROLE_KEY=secret\n')
    monkeypatch.delenv('SUPABASE_URL', raising=False)
    monkeypatch.delenv('SUPABASE_SERVICE_ROLE_KEY', raising=False)
    original = httpx.Client
    opening = {'symbol': 'AAPL', 'session_date': '2026-10-09', 'reason': 'OPENING_WINDOW_INCOMPLETE',
               'window_start': '2026-10-09T13:30:00.000Z', 'window_end': '2026-10-09T13:35:00.000Z',
               'returned_window_count': 4, 'returned_minutes': ['2026-10-09T13:30:00.000Z'],
               'returned_minutes_truncated': False, 'missing_minutes': ['2026-10-09T13:34:00.000Z'],
               'provider_body': 'private-secret'}
    details = {'phase': 'publish', 'status': 'publish_ready', 'opening_failure_count': 12,
               'opening_failures': [opening] * 12, 'secret': 'private-secret'}
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=[{'status': 'success', 'details': details}])), **kwargs))
    row = collector.platform_enrich_probe(tmp_path, cron_name='cc-sip-scanner')['cron_runs'][0]
    assert row['opening_failure_count'] == 12
    assert len(row['opening_failures']) == 10
    assert row['opening_failures'][0]['symbol'] == 'AAPL'
    assert row['opening_failures'][0]['missing_minutes'] == ['2026-10-09T13:34:00+00:00']
    assert 'private-secret' not in json.dumps(row)


def test_probe_non_array_response_does_not_prove_zero_eligible_work(tmp_path, monkeypatch):
    (tmp_path / '.env.local').write_text('SUPABASE_URL=https://example.supabase.co\nSUPABASE_SERVICE_ROLE_KEY=secret\n')
    monkeypatch.delenv('SUPABASE_URL', raising=False)
    monkeypatch.delenv('SUPABASE_SERVICE_ROLE_KEY', raising=False)
    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={'message': 'private-secret'})), **kwargs))
    result = collector.platform_enrich_probe(tmp_path)
    assert result['probe_status']['cron_runs'] == 'INVALID_RESPONSE'
    assert all(row['eligible_row_seen'] is None for row in result['eligibility_reads'].values())
    assert 'private-secret' not in json.dumps(result)


def test_opening_context_rejects_unknown_or_unbounded_diagnostics():
    valid = {'symbol': 'NVDA', 'session_date': '2026-10-09', 'reason': 'OPENING_WINDOW_INCOMPLETE',
             'returned_window_count': 1, 'returned_minutes_truncated': False,
             'returned_minutes': ['https://provider.example/?token=private-secret',
                                  '2026-10-09T13:30:00Z', '2026-10-09T14:30:00Z'],
             'missing_minutes': ['2026-10-09T13:31:00Z'], 'error': 'private-secret'}
    bad = [{**valid, 'symbol': 'https://secret'}, {**valid, 'reason': 'private-secret'},
           {**valid, 'session_date': '2026-99-99'}, {**valid, 'returned_window_count': True}]
    result = collector.opening_context({'opening_failure_count': 5, 'opening_failures': bad + [valid]})
    assert len(result['opening_failures']) == 1
    assert result['opening_failures'][0]['returned_minutes'] == ['2026-10-09T13:30:00+00:00']
    assert 'private-secret' not in json.dumps(result)
    assert collector.opening_context({'opening_failure_count': True, 'opening_failures': [valid]}) == {}
