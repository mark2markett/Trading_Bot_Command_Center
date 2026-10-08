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
