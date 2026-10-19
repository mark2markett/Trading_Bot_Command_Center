"""Read-only readiness summary. No bot imports, vendor probes, orders or control writes."""
from __future__ import annotations
import argparse
import json
import os
import sqlite3
import urllib.request
import urllib.error
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BOTS={'spy_mr','sip_orb','gap_go','gap_go_spread','nr7'}
ET=ZoneInfo('America/New_York')


def fresh(value,now,maximum):
    try:
        stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
        return stamp.tzinfo is not None and 0<=(now-stamp).total_seconds()<=maximum
    except (TypeError,ValueError,AttributeError):return False


def assess(health,readiness,incidents,reports,now):
    blockers=[]
    if health.get('ok') is not True or not fresh(health.get('riskd_last',{}).get('at'),now,90): blockers.append('SERVER_OR_RISK_MONITOR_UNAVAILABLE')
    if readiness.get('entries_paused') is not False: blockers.append('FLEET_ENTRY_PAUSE')
    if readiness.get('killed') is not False: blockers.append('FLEET_KILL_OR_CONTROL_UNVERIFIED')
    if readiness.get('paper_fleet') is not True or readiness.get('bot_count')!=5 or set(readiness.get('bot_ids',[]))!=BOTS: blockers.append('FIVE_PAPER_BOTS_UNVERIFIED')
    account=readiness.get('paper_account') or {}
    if account.get('ready') is not True: blockers.append('VALUATION_UNAVAILABLE')
    monitor=incidents.get('monitor') or {}
    if monitor.get('status')!='checking' or not fresh(monitor.get('last_completed_at'),now,90): blockers.append('INCIDENT_MONITOR_UNAVAILABLE')
    spy=reports.get('spy_mr') or {}
    if not fresh(spy.get('checked_at'),now,60): blockers.append('POSITION_MONITOR_UNAVAILABLE')
    local=now.astimezone(ET)
    in_hours=local.weekday()<5 and (9,30)<=(local.hour,local.minute)<(16,0)
    if in_hours and any(p.get('quote_status')!='current' or not fresh(p.get('mark_at'),now,60) for report in reports.values() for p in report.get('positions',[])):
        blockers.append('OPEN_POSITION_QUOTE_UNVERIFIED')
    if any(report.get('issues') for report in reports.values()):blockers.append('POSITION_MONITOR_REQUIRES_REVIEW')
    return {'verdict':'NOT_READY_FOR_NEW_ENTRIES' if blockers else 'STORED_CHECKS_PASSED_LIVE_SCANNER_STILL_REQUIRED',
            'at_et':local.isoformat(),'blockers':blockers,'valuation_reason':account.get('reason'),
            'monitor':monitor.get('status','unavailable'),'position_checked_at':spy.get('checked_at'),
            'scanner':'Current-session publication and native selection still require verification before 09:40 ET',
            'scope':'Stored observations only; no continuous broker protection or scanner readiness certification'}


def verify_ledger_identity(health,expected):
    reported=health.get('db')
    if not isinstance(reported,str) or not reported.strip():
        raise ValueError('API health response is missing its ledger path')
    try:
        # Resolve Windows case/junction/short-path spellings AND check the file.
        # A hard link with a different canonical basename is unsafe for SQLite
        # WAL because it can read a different -wal/-shm alongside the same db.
        canonical=Path(reported).resolve(strict=True)
        selected=Path(expected).resolve(strict=True)
        matches=canonical==selected and os.path.samefile(canonical,selected)
    except OSError as error:
        raise ValueError('API ledger identity could not be verified: reported='+repr(reported)+
                         ' expected='+str(expected)+' error='+type(error).__name__) from error
    if not matches:
        raise ValueError('API ledger does not match the selected repository: reported='+repr(reported)+' expected='+str(expected))


def capture(root):
    root=Path(root).resolve(strict=True);payloads={};errors=[]
    for route in ('health','readiness','incidents'):
        try:
            request=urllib.request.Request('http://127.0.0.1:8585/api/'+route,headers={'Accept':'application/json'})
            for attempt in range(2 if route=='health' else 1):
                try:
                    with urllib.request.urlopen(request,timeout=5) as response:
                        if response.status!=200:raise ValueError('Unexpected response')
                        value=json.loads(response.read(262144))
                        if not isinstance(value,dict):raise ValueError('Unexpected payload')
                        payloads[route]=value
                    break
                except (TimeoutError,urllib.error.URLError) as error:
                    timed_out=isinstance(error,TimeoutError) or isinstance(getattr(error,'reason',None),TimeoutError)
                    if route!='health' or attempt or not timed_out:raise
        except Exception as error:
            payloads[route]={};errors.append(route+':'+type(error).__name__)
    health=payloads['health']
    if not health:
        raise ValueError('API health could not be read; '+('; '.join(errors) or 'empty health response'))
    verify_ledger_identity(health,root/'var/cc.db')
    with sqlite3.connect((root/'var/cc.db').resolve(strict=True).as_uri()+'?mode=ro',uri=True,timeout=3) as db:
        db.execute('PRAGMA query_only=ON')
        row=db.execute("SELECT value_json FROM kv WHERE key='position_monitor'").fetchone()
        try:reports=json.loads(row[0]) if row else {}
        except (TypeError,ValueError):reports={}
        if not isinstance(reports,dict):reports={}
    result=assess(health,payloads['readiness'],payloads['incidents'],reports,datetime.now(timezone.utc))
    flags=[]
    for path in sorted((root/'var/control').glob('*')):
        if path.is_file() and (path.name=='PAUSE_ENTRIES' or path.name=='KILL' or path.name.endswith('.pause')):
            try:value=json.loads(path.read_text(encoding='utf-8-sig'))
            except Exception:value={}
            flags.append({'flag':path.name,**{key:value.get(key) for key in ('at','actor','reason')}})
    result['preserved_controls']=flags;result['read_errors']=errors
    if errors:result['verdict']='NOT_READY_FOR_NEW_ENTRIES'
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--repo',type=Path,required=True);args=parser.parse_args()
    try:
        result=capture(args.repo);print(json.dumps(result,indent=2));raise SystemExit(2 if result['verdict']=='NOT_READY_FOR_NEW_ENTRIES' else 0)
    except (OSError,ValueError,sqlite3.Error) as error:
        print(json.dumps({'verdict':'NOT_READY_FOR_NEW_ENTRIES','error':type(error).__name__}));raise SystemExit(1)
