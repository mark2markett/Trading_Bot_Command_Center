"""Owner-approved fleet paper resume; retain per-bot pauses and re-arm only DD pause.

The Windows wrapper quiesces only the owned server and monitor. No bot, provider,
strategy, schema or financial history is imported or changed by this helper.
"""
from __future__ import annotations
import argparse
from contextlib import closing
from datetime import datetime, timezone
import importlib.util
import json
import math
import os
from pathlib import Path
import socket
import sqlite3
import urllib.request
from zoneinfo import ZoneInfo

ROOT=Path(__file__).parent

def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/filename)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

holding=load('resume_holding','HOLDING-MAINTENANCE.py')
readiness=load('resume_readiness','CHECK-OPEN-READINESS.py')


def finite(value):
    return type(value) in (int,float) and math.isfinite(value)


def validate(r,now,*,paused=True):
    if not readiness.fresh(r.get('at'),now,90):raise ValueError('Resume evidence is stale; run the wrapper again')
    if r['readiness']['blockers']!=(['FLEET_ENTRY_PAUSE'] if paused else []) or r['readiness'].get('read_errors'):
        raise ValueError('Only the reviewed fleet pause may remain as a readiness blocker')
    times=r['freshness']
    for key,maximum in (('riskd',90),('monitor',90),('position',60)):
        if not readiness.fresh(times.get(key),now,maximum):raise ValueError('Stale '+key+' evidence at release')
    if not isinstance(times.get('marks'),list) or any(not readiness.fresh(stamp,now,60) for stamp in times['marks']):raise ValueError('Stale holding mark at release')
    risk=r['risk'];limits=risk['limits'];dd=risk['drawdown'];exp=risk['exposure']
    expected={'dd_pause_pct':.06,'dd_flatten_pct':.08,'dd_kill_pct':.1,'daily_loss_limit_pct':.02,'max_gross_exposure':1.5}
    if any(limits.get(k)!=v for k,v in expected.items()):raise ValueError('Risk limits differ from the reviewed limits')
    if risk.get('entries_paused') is not paused or risk.get('killed') is not False or dd.get('source')!='paper':raise ValueError('Paper risk identity or controls differ')
    if not all(finite(dd.get(k)) and dd[k]>0 for k in ('equity','peak')):raise ValueError('Account valuation is invalid')
    if not finite(dd.get('dd')) or not 0<=dd['dd']<limits['dd_pause_pct']:raise ValueError('Drawdown is at or above the pause limit')
    if not finite(exp.get('ratio')) or not 0<=exp['ratio']<limits['max_gross_exposure']:raise ValueError('Exposure is at or above the cap')
    if not finite(r.get('day_pct')) or r['day_pct']<=-limits['daily_loss_limit_pct']:raise ValueError('Daily loss limit reached or unverified')


def check(root):
    root=Path(root).resolve(strict=True)
    manifest=json.loads((ROOT/'HOLDING-MAINTENANCE-SOURCE.json').read_text())
    if holding.source_stage(root,manifest)!='installed':raise ValueError('Reviewed holding maintenance must already be installed')
    begun=datetime.now(timezone.utc)
    observed=readiness.capture(root)
    def request(route):
        with urllib.request.urlopen('http://127.0.0.1:8585/api/'+route,timeout=5) as response:
            return json.loads(response.read(262144))
    account=request('readiness')['paper_account']
    if account.get('ready') is not True:raise ValueError('Fresh shared paper valuation required')
    with closing(sqlite3.connect((root/'var/cc.db').as_uri()+'?mode=ro',uri=True,timeout=3)) as ledger:
        marks=[row[0] for row in ledger.execute('SELECT m.at FROM positions p LEFT JOIN paper_marks m ON m.symbol=p.symbol WHERE p.qty<>0')]
    times={'riskd':request('health').get('riskd_last',{}).get('at'),
           'monitor':request('incidents?limit=1').get('monitor',{}).get('last_completed_at'),
           'position':observed.get('position_checked_at'),'marks':marks}
    result={'at':begun.isoformat(),'repo':str(root),'readiness':observed,'freshness':times,
            'risk':request('risk'),'day_pct':account.get('day_pct'),'runtime':holding.runtime_snapshot(root),
            'control_files':{str(p.relative_to(root)):__import__('hashlib').sha256(p.read_bytes()).hexdigest() for p in (root/'var/control').iterdir() if p.is_file() and p.name!='PAUSE_ENTRIES'}}
    validate(result,datetime.now(timezone.utc))
    return result


def quiescent_risk(db,now,limits):
    """Recompute the reviewed SPY/flat paper account inside the write transaction.

    No quote request: use exactly the ledger's current marks, capital and history.
    This closes the gap between the earlier HTTP risk read and server shutdown.
    """
    row=db.execute("SELECT value_json FROM kv WHERE key='paper_account'").fetchone()
    if not row:raise ValueError('Paper account is unconfigured')
    capital=json.loads(row[0]).get('initial_capital')
    if not finite(capital) or capital<=0:raise ValueError('Invalid paper capital')
    realized=db.execute('SELECT COALESCE(SUM(pnl),0) FROM trades').fetchone()[0]
    if not finite(realized):raise ValueError('Invalid realized P&L')
    gross=unrealized=0.
    for symbol,qty,entry,price,stamp in db.execute('SELECT p.symbol,p.qty,p.avg_price,m.price,m.at FROM positions p LEFT JOIN paper_marks m ON m.symbol=p.symbol WHERE p.qty<>0'):
        if symbol!='SPY' or type(qty) is not int or qty<=0 or not finite(entry) or entry<=0 or not finite(price) or price<=0 or not readiness.fresh(stamp,now,60):raise ValueError('Current holding quote or identity is unverified')
        if db.execute("SELECT 1 FROM kv WHERE key=?",('paper_mark_invalid:'+symbol,)).fetchone():raise ValueError('Holding mark is invalid')
        gross+=qty*price;unrealized+=qty*(price-entry)
    equity=capital+realized+unrealized
    if not finite(equity) or equity<=0:raise ValueError('Current equity is invalid')
    history=db.execute('SELECT at,equity FROM paper_equity ORDER BY id').fetchall()
    if any(not finite(value) or value<=0 for _,value in history):raise ValueError('Invalid equity history')
    peak=max([capital,equity]+[value for _,value in history])
    today=now.astimezone(ZoneInfo('America/New_York')).date()
    prior=[value for at,value in history if datetime.fromisoformat(at).astimezone(ZoneInfo('America/New_York')).date()<today]
    base=prior[-1] if prior else capital
    dd=(peak-equity)/peak;ratio=gross/equity;day=(equity-base)/base
    if dd>=limits['dd_pause_pct'] or ratio>=limits['max_gross_exposure'] or day<=-limits['daily_loss_limit_pct']:
        raise ValueError('Current quiescent ledger risk breaches a limit; fleet pause retained')
    return {'equity':equity,'drawdown':dd,'exposure_ratio':ratio,'day_pct':day}


def apply(root,r,*,approved=False,now=None):
    if not approved:raise ValueError('Explicit owner paper-entry approval is required')
    now=now or datetime.now(timezone.utc);validate(r,now)
    root=Path(root).resolve(strict=True)
    if r['repo']!=str(root):raise ValueError('Wrong repository receipt')
    controls=root/'var/control';pause=controls/'PAUSE_ENTRIES'
    for path in controls.iterdir():
        if path.is_symlink() or path.name=='KILL' or path.name.endswith(('.kill','.flatten')) or (path.name.endswith('.pause') and path.name!='sip_orb.pause'):
            raise ValueError('Kill, flatten or unsafe control present; no release permitted')
    flag=json.loads(holding.regular_bytes(pause))
    if flag.get('actor')!='riskd' or flag.get('reason')!='portfolio dd 6.9%':raise ValueError('Unexpected fleet pause; independent review required')
    sip=json.loads(holding.regular_bytes(controls/'sip_orb.pause'))
    if sip.get('actor')!='sdk' or sip.get('reason')!='4 consecutive losses':raise ValueError('SIP pause identity differs')
    database=(root/'var/cc.db').resolve(strict=True)
    with closing(sqlite3.connect(database.as_uri()+'?mode=rw',uri=True,timeout=3)) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            current=holding.runtime_snapshot(root)
            if current['fingerprint']!=r['runtime']['fingerprint']:raise ValueError('Financial state or controls changed; no release')
            holding.history_preserved(root,r['runtime']['history'])
            current_risk=quiescent_risk(db,now,r['risk']['limits'])
            row=db.execute("SELECT value_json FROM kv WHERE key='ladder_fired'").fetchone()
            fired=json.loads(row[0]) if row else {}
            if not isinstance(fired,dict):raise ValueError('Invalid ladder state')
            after={key:value for key,value in fired.items() if key!='pause'}
            # Commit the audit and re-arm BEFORE removing the file. If interrupted,
            # the pause remains in place; resetting this latch never creates entries.
            before={'paused':True,'flag':flag,'ladder_fired':fired}
            outcome={'paused':False,'ladder_fired':after,'sip_pause_preserved':True,'phase':'release_authorized','risk':current_risk}
            db.execute('INSERT INTO controls(at,actor,action,target,before_json,after_json,note) VALUES(?,?,?,?,?,?,?)',
                       (now.isoformat(),'owner','resume_entries','fleet',json.dumps(before),json.dumps(outcome),
                        'Owner approved fleet paper entries; retain SIP pause, all risk limits, holding and stop; re-arm only DD pause'))
            db.execute("INSERT INTO kv(key,value_json,updated_at) VALUES('ladder_fired',?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at",(json.dumps(after),now.isoformat()))
            db.commit()
        except BaseException:
            db.rollback();raise
    if json.loads(holding.regular_bytes(pause))!=flag:raise ValueError('Fleet pause changed before release; retained')
    pause.unlink()
    return {'ok':True,'resumed':True,'scope':'FLEET_PAPER_ENTRIES_ONLY','sip_paused':True,
            'pause_threshold':.06,'verified_risk':current_risk,'holding_and_stop':'retained','scanner':'Live opening verification still required'}


def verify(root,r):
    root=Path(root).resolve(strict=True)
    if r['repo']!=str(root):raise ValueError('Wrong repository receipt')
    observed=readiness.capture(root)
    with urllib.request.urlopen('http://127.0.0.1:8585/api/risk',timeout=5) as response:
        risk=json.loads(response.read(262144))
    with urllib.request.urlopen('http://127.0.0.1:8585/api/readiness',timeout=5) as response:
        account=json.loads(response.read(262144))['paper_account']
    if account.get('ready') is not True:raise ValueError('Valuation unavailable after restart')
    def request(route):
        with urllib.request.urlopen('http://127.0.0.1:8585/api/'+route,timeout=5) as response:return json.loads(response.read(262144))
    with closing(sqlite3.connect((root/'var/cc.db').as_uri()+'?mode=ro',uri=True,timeout=3)) as ledger:
        marks=[row[0] for row in ledger.execute('SELECT m.at FROM positions p LEFT JOIN paper_marks m ON m.symbol=p.symbol WHERE p.qty<>0')]
    times={'riskd':request('health').get('riskd_last',{}).get('at'),'monitor':request('incidents?limit=1').get('monitor',{}).get('last_completed_at'),'position':observed.get('position_checked_at'),'marks':marks}
    validate({'at':datetime.now(timezone.utc).isoformat(),'readiness':observed,'risk':risk,'day_pct':account.get('day_pct'),'freshness':times},datetime.now(timezone.utc),paused=False)
    controls=root/'var/control'
    if (controls/'PAUSE_ENTRIES').exists():raise ValueError('Fleet entries remain paused')
    if any(p.name=='KILL' or p.name.endswith(('.kill','.flatten')) for p in controls.iterdir()):raise ValueError('A new risk control requires review')
    expected=r['runtime']
    # Preserve every per-bot flag byte-for-byte; never release SIP implicitly.
    import hashlib
    for name,digest in r.get('control_files',{}).items():
        if not (root/name).is_file() or hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest:
            raise ValueError('Per-bot control changed during release')
    holding.history_preserved(root,expected['history'])
    return {'ok':True,'verified':'FLEET_PAPER_RESUMED_SIP_PAUSED','readiness':observed}


def block(root,r):
    root=Path(root).resolve(strict=True)
    if r['repo']!=str(root):raise ValueError('Wrong repository receipt')
    flag=root/'var/control/PAUSE_ENTRIES'
    if not flag.exists():
        # Refuse overwrite of a concurrent control; exclusive create is fail closed.
        with flag.open('x',encoding='utf-8') as handle:
            json.dump({'at':datetime.now(timezone.utc).isoformat(),'actor':'fleet-resume-guard',
                       'reason':'Resume verification failed; owner review required'},handle)
    return {'ok':True,'entries_paused':True}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['check','apply','verify','block']);parser.add_argument('--repo',required=True,type=Path)
    parser.add_argument('--receipt',required=True,type=Path);parser.add_argument('--approve-fleet-paper-entries',action='store_true')
    args=parser.parse_args()
    try:
        if os.name!='nt':raise ValueError('Operator execution requires the Windows wrapper')
        if args.mode=='check':
            result=check(args.repo);args.receipt.write_text(json.dumps(result,indent=2),encoding='utf-8')
            print(json.dumps({'ok':True,'scope':'READ_ONLY','receipt':str(args.receipt)}))
        elif args.mode in ('verify','block'):
            saved=json.loads(args.receipt.read_text(encoding='utf-8-sig'))
            print(json.dumps(verify(args.repo,saved) if args.mode=='verify' else block(args.repo,saved)))
        else:
            with socket.socket() as probe:
                probe.settimeout(1)
                if probe.connect_ex(('127.0.0.1',8585))==0:raise ValueError('Owned server must be stopped by the wrapper first')
            manifest=json.loads((ROOT/'HOLDING-MAINTENANCE-SOURCE.json').read_text())
            if holding.source_stage(args.repo,manifest)!='installed':raise ValueError('Unexpected runtime source')
            result=apply(args.repo,json.loads(args.receipt.read_text(encoding='utf-8-sig')),approved=args.approve_fleet_paper_entries)
            print(json.dumps(result))
    except Exception as error:
        print(json.dumps({'ok':False,'error':str(error)}));raise SystemExit(1)
