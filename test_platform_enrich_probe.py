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
        }, {'status': 'failure', 'details': {'error': secret, 'phase': secret}}])

    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    result = collector.platform_enrich_probe(tmp_path, cron_name='cc-sip-scanner')
    row = result['cron_runs'][0]
    assert row['error_code'] == 'PREPARATION_INCOMPLETE'
    assert row['phase'] == 'publish'
    assert row['counts'] == {'universe': 500, 'failures': 4}
    assert result['cron_runs'][1]['error_code'] is None
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
