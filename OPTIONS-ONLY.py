"""Audited options-only entry activation. No orders, fills, cancellations or position writes."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
import sqlite3
import urllib.request
from datetime import date, datetime, timezone

ROOT=Path(__file__).parent
spec=importlib.util.spec_from_file_location('options_runtime_install',ROOT/'INSTALL-ACTIVITY-DASHBOARD.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
STOCKS={'spy_mr','gap_go','nr7','sip_orb'}
BOTS=STOCKS|{'gap_go_spread'}
POLICY_SOURCE={'cc_sdk/cc_sdk/control.py','cc_sdk/cc_sdk/risk.py','cc_sdk/cc_sdk/intraday.py','cc_sdk/cc_sdk/options_runner.py','cc_server/cc_server/api.py','cc_server/cc_server/activity.py'}
NOTE='Options-only trading required; share entries disabled and existing exits preserved.'


def fetch(route,body=None):
    data=json.dumps(body).encode() if body is not None else None
    request=urllib.request.Request('http://127.0.0.1:8585'+route,data=data,
                                   headers={'Accept':'application/json','Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=10) as response:
        return response.read(262144)


def report(repo,fetcher):
    base.health_identity(repo,fetcher)
    value=json.loads(fetcher('/api/activity'))
    bots=value.get('bots')
    if not isinstance(bots,list) or {b.get('id') for b in bots}!=BOTS or len(bots)!=5 or any(b.get('mode')!='paper' for b in bots):
        raise ValueError('Expected the five registered paper bots; no execution mode may change')
    return value


def regular_controls(repo):
    folder=base.safe_target(repo,'var/control/.options-policy-check').parent
    if not folder.is_dir():raise ValueError('Control directory missing')
    values={}
    for path in folder.iterdir():
        if path.is_symlink() or not path.is_file():raise ValueError('Unsafe control path: '+path.name)
        values[path.name]=base.digest(path.read_bytes())
    return folder,values


def receipt_path(repo,receipt):
    path=Path(receipt).resolve(strict=False)
    if path.parent!=(repo/'var/backups').resolve(strict=True) or not path.name.startswith('options-only-') or path.suffix!='.json':
        raise ValueError('Unexpected options-only receipt path')
    return base.safe_target(repo,path.relative_to(repo).as_posix())


def saved_receipt(repo,receipt):
    path=receipt_path(repo,receipt)
    value=json.loads(path.read_text())
    if value.get('repo')!=str(repo):raise ValueError('Receipt repository differs')
    return path,value


def valid_option(symbol):
    match=re.fullmatch(r'[A-Z.]{1,6} *(\d{6})[CP](\d{8})',str(symbol))
    if not match:return False
    ymd=match[1]
    try:date(2000+int(ymd[:2]),int(ymd[2:4]),int(ymd[4:]))
    except ValueError:return False
    return int(match[2])>0


def pending_share_entries(activity):
    return [{'id':o.get('id'),'symbol':o.get('symbol'),'side':o.get('side'),'qty':o.get('qty')}
            for o in activity.get('working_orders',[]) if o.get('side') in {'BUY','SELL_SHORT','BUY_TO_OPEN','SELL_TO_OPEN'}
            and (o.get('side') not in {'BUY_TO_OPEN','SELL_TO_OPEN'} or not valid_option(o.get('symbol')))]


def contain(repo,receipt,*,fetcher=fetch):
    repo=Path(repo).resolve(strict=True)
    observed=report(repo,fetcher)
    folder,flags=regular_controls(repo)
    path=receipt_path(repo,receipt)
    if path.exists():raise ValueError('Receipt already exists; use a new wrapper receipt')
    saved={'repo':str(repo),'at':datetime.now(timezone.utc).isoformat(),'state':'containing','original_flags':flags,
           'observed_positions':observed.get('positions',[])}
    base.atomic(path,(json.dumps(saved,indent=2)+'\n').encode())
    for bot in sorted(STOCKS):
        flag=folder/(bot+'.pause')
        if not flag.exists():
            result=json.loads(fetcher('/api/controls/bot/'+bot+'/pause',{'actor':'owner-options-only','note':NOTE}))
            if result.get('ok') is not True:raise ValueError('Share pause failed: '+bot)
        if not flag.is_file() or flag.is_symlink():raise ValueError('Share pause not verified: '+bot)
    current=report(repo,fetcher)
    if any(b['id'] in STOCKS and b.get('entry_state')=='clear' for b in current['bots']):
        raise ValueError('Share entry permissions still clear')
    saved.update(state='contained',pending_share_entry_orders=pending_share_entries(current))
    base.atomic(path,(json.dumps(saved,indent=2)+'\n').encode())
    return {'ok':True,'state':'SHARE_STRATEGIES_PAUSED','receipt':str(path),
            'pending_share_entry_orders':saved['pending_share_entry_orders']}


def activate(repo,package,receipt,*,fetcher=fetch):
    repo=Path(repo).resolve(strict=True)
    path,saved=saved_receipt(repo,receipt)
    if saved.get('state')!='contained':raise ValueError('Audited share containment must complete first')
    manifest,payload=base.read_package(Path(package))
    if manifest.get('entry_asset_policy')!='options_only' or not POLICY_SOURCE.issubset(payload):
        raise ValueError('Options-only source policy is missing from this package')
    for name in base.SOURCE:
        if base.safe_target(repo,name).read_bytes()!=payload[name]:raise ValueError('Installed source differs: '+name)
    current=report(repo,fetcher)
    if not isinstance(current.get('entry_policy',{}).get('options_only'),bool):
        raise ValueError('Options-only runtime API is not loaded')
    if pending_share_entries(current):raise ValueError('Pending share entry orders need review; no cancellation or fill was fabricated')
    folder,_=regular_controls(repo)
    if any(not (folder/(bot+'.pause')).is_file() for bot in STOCKS):raise ValueError('Share pause was removed before policy activation')
    marker=folder/'OPTIONS_ONLY'
    if not marker.exists():
        database=(repo/'var/cc.db').resolve(strict=True)
        with sqlite3.connect(database.as_uri()+'?mode=rw',uri=True,timeout=5) as db:
            writes={sqlite3.SQLITE_INSERT,sqlite3.SQLITE_UPDATE,sqlite3.SQLITE_DELETE,sqlite3.SQLITE_CREATE_TABLE,sqlite3.SQLITE_ALTER_TABLE,sqlite3.SQLITE_DROP_TABLE}
            db.set_authorizer(lambda action,table,*args:sqlite3.SQLITE_DENY if action in writes and not (action==sqlite3.SQLITE_INSERT and table=='controls') else sqlite3.SQLITE_OK)
            db.execute('BEGIN IMMEDIATE')
            bots=db.execute('SELECT id,mode FROM bots').fetchall()
            if len(bots)!=5 or {b[0] for b in bots}!=BOTS or any(b[1]!='paper' for b in bots):raise ValueError('Paper fleet changed before activation')
            at=datetime.now(timezone.utc).isoformat()
            db.execute('INSERT INTO controls(at,actor,action,target,before_json,after_json,note) VALUES(?,?,?,?,?,?,?)',
                       (at,'owner-options-only','options_only','fleet',json.dumps({'options_only':False}),
                        json.dumps({'options_only':True,'share_strategies_paused':sorted(STOCKS)}),NOTE))
            db.commit()  # Persist the audit before publishing the SDK flag.
        try:
            with marker.open('x',encoding='utf-8') as output:
                json.dump({'at':at,'actor':'owner-options-only','reason':NOTE},output)
        except FileExistsError:
            pass  # A concurrently published restriction must not be overwritten.
    saved['state']='activated'
    base.atomic(path,(json.dumps(saved,indent=2)+'\n').encode())
    return {'ok':True,'options_only':True,'receipt':str(path)}


def verify(repo,receipt,*,fetcher=fetch):
    repo=Path(repo).resolve(strict=True)
    path,saved=saved_receipt(repo,receipt)
    current=report(repo,fetcher)
    folder,flags=regular_controls(repo)
    if current.get('entry_policy',{}).get('options_only') is not True or 'OPTIONS_ONLY' not in flags:
        raise ValueError('Options-only entry policy is not active')
    if any(bot+'.pause' not in flags for bot in STOCKS) or any(b['id'] in STOCKS and b.get('entry_state')=='clear' for b in current['bots']):
        raise ValueError('Share strategies are not blocked')
    if any(flags.get(name)!=value for name,value in saved['original_flags'].items()):
        raise ValueError('A pre-existing control changed; preserve the receipt and review')
    if pending_share_entries(current):raise ValueError('Pending share entry requires review; policy did not cancel old orders')
    saved['state']='verified'
    base.atomic(path,(json.dumps(saved,indent=2)+'\n').encode())
    return {'ok':True,'scope':'OPTIONS_ONLY_NEW_ENTRIES','share_strategies_paused':sorted(STOCKS),
            'options_controls':'preserved','existing_share_positions':[p for p in current.get('positions',[]) if p.get('kind')=='shares'],
            'orders_submitted_by_installer':0,'receipt':str(path),'next_step':'Refresh with Ctrl+F5. Existing share holdings remain visible for exit management.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['contain','activate','verify']);parser.add_argument('--repo',required=True,type=Path)
    parser.add_argument('--receipt',required=True,type=Path);args=parser.parse_args()
    try:
        result=activate(args.repo,ROOT,args.receipt) if args.action=='activate' else globals()[args.action](args.repo,args.receipt)
        print(json.dumps(result))
    except Exception as error:
        print(json.dumps({'ok':False,'error':str(error),'receipt':str(args.receipt),'note':'Restrictive pauses are retained; no positions were closed or converted.'}))
        raise SystemExit(1)
