import importlib.util
from datetime import datetime,timezone
from pathlib import Path


def module():
    path=Path(__file__).with_name('CHECK-OPEN-READINESS.py')
    assert path.exists(),'No combined opening readiness report exists'
    spec=importlib.util.spec_from_file_location('open_readiness',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def test_healthy_server_does_not_mask_pauses_missing_quotes_or_missing_monitor():
    m=module();now=datetime(2026,10,19,13,15,tzinfo=timezone.utc)
    result=m.assess({'ok':True,'riskd_last':{'at':now.isoformat()}},
                    {'entries_paused':True,'killed':False,'paper_fleet':True,'bot_count':5,'bot_ids':list(m.BOTS),'paper_account':{'ready':False,'reason':'Stale SPY'}},
                    {},{},now)
    assert result['verdict']=='NOT_READY_FOR_NEW_ENTRIES'
    assert {'FLEET_ENTRY_PAUSE','VALUATION_UNAVAILABLE','INCIDENT_MONITOR_UNAVAILABLE','POSITION_MONITOR_UNAVAILABLE'}<=set(result['blockers'])


def test_recent_checks_without_current_quotes_never_certify_position_safety():
    m=module();now=datetime(2026,10,19,13,32,tzinfo=timezone.utc)
    result=m.assess({'ok':True,'riskd_last':{'at':now.isoformat()}},
                    {'entries_paused':False,'killed':False,'paper_fleet':True,'bot_count':5,'bot_ids':list(m.BOTS),'paper_account':{'ready':False}},
                    {'monitor':{'status':'checking','last_completed_at':now.isoformat()}},
                    {'spy_mr':{'checked_at':now.isoformat(),'issues':[],'positions':[{'quote_status':'market_closed','mark_at':now.isoformat()}]}},now)
    assert 'VALUATION_UNAVAILABLE' in result['blockers']
    assert 'OPEN_POSITION_QUOTE_UNVERIFIED' in result['blockers']
    assert result['scanner']=='Current-session publication and native selection still require verification before 09:40 ET'
