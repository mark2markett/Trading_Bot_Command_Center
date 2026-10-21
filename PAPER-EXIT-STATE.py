"""Audited correction of a proven absent local paper stop. Never settles or submits."""
from __future__ import annotations

import argparse
import base64
import importlib.util
import json
from datetime import date, datetime, timezone
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

ROOT=Path(__file__).parent
spec=importlib.util.spec_from_file_location('paper_exit_source_install',ROOT/'INSTALL-ACTIVITY-DASHBOARD.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
BOTS={'spy_mr','gap_go','gap_go_spread','nr7','sip_orb'}
ACTIVE={'sent','submitted','open','pending','new','accepted','partially_filled','pending_cancel','pending_replace'}
TERMINAL={'filled','cancelled','canceled','rejected','expired','failed','done'}
TABLES=('bots','positions','orders','fills','trades','controls','limits')
STATE='bots/spy_mr_bot/state_paper.json'
PAPER='bots/spy_mr_bot/paper_ledger.json'
ACTION='reconcile_paper_stop_metadata'
NOTE='Local paper stop already absent; pending paper exit and holdings preserved; no broker command issued.'


def connect(repo,readonly=True):
    path=base.safe_target(repo,'var/cc.db').resolve(strict=True)
    db=sqlite3.connect(path.as_uri()+('?mode=ro' if readonly else '?mode=rw'),uri=True,timeout=3)
    db.row_factory=sqlite3.Row
    if readonly:db.execute('PRAGMA query_only=ON')
    return db


def read_file(repo,name):
    path=base.safe_target(repo,name)
    if path.stat().st_size>1_000_000:raise ValueError('Paper state exceeds size limit')
    raw=path.read_bytes()
    value=json.loads(raw.decode('utf-8-sig'))
    if not isinstance(value,dict):raise ValueError('Paper state must be an object')
    return raw,value


def evidence(repo,db):
    flags={}
    folder=base.safe_target(repo,'var/control/.paper-exit-check').parent
    for path in folder.iterdir():
        if path.is_symlink() or not path.is_file():raise ValueError('Unsafe control path')
        flags[path.name]=base.digest(path.read_bytes())
    raw,state=read_file(repo,STATE);paper_raw,paper=read_file(repo,PAPER)
    return {'state_hash':base.digest(raw),'paper_hash':base.digest(paper_raw),'flags':flags,
            'tables':{name:[dict(row) for row in db.execute('SELECT * FROM '+name+' ORDER BY rowid')] for name in TABLES}},raw,state,paper


def validate_proof(before,state,paper):
    tables=before['tables'];bots=tables['bots']
    if len(bots)!=5 or {b['id'] for b in bots}!=BOTS or any(b['mode']!='paper' for b in bots):raise ValueError('Expected five paper bots')
    if not {'OPTIONS_ONLY','spy_mr.pause','gap_go.pause','nr7.pause','sip_orb.pause'}<=before['flags'].keys():raise ValueError('Options-only share restrictions must remain present')
    qty=state.get('qty');pend=state.get('pending')
    if state.get('in_position') is not True or type(qty) is not int or qty<=0 or not isinstance(pend,dict):raise ValueError('Expected an open holding and pending exit')
    if pend.get('side')!='SELL' or pend.get('qty')!=qty or not str(pend.get('order_id','')).startswith('paper-'):raise ValueError('Pending paper exit identity differs')
    session=date.fromisoformat(pend['date'])
    if state.get('stop_order_id')!='paper-stop-SPY':raise ValueError('Saved stop reference differs')
    if not isinstance(paper.get('positions'),dict) or not isinstance(paper.get('stops'),dict):raise ValueError('Paper registry must be an object')
    if paper['positions'].get('SPY')!=qty or 'SPY' in paper['stops']:raise ValueError('Paper holding differs or stop is still present')
    queued=paper.get('pending')
    if not isinstance(queued,list) or len(queued)!=1:raise ValueError('Paper queue is ambiguous')
    q=queued[0]
    if not isinstance(q,dict) or (q.get('id'),q.get('kind'),q.get('symbol'),q.get('qty'))!=(pend['order_id'],'SELL_MOC','SPY',qty):raise ValueError('Paper queue does not match saved exit')
    stamp=datetime.fromisoformat(q['queued'].replace('Z','+00:00'))
    if stamp.tzinfo is None or stamp.astimezone(ZoneInfo('America/New_York')).date()!=session:raise ValueError('Paper queue session differs')
    held=[p for p in tables['positions'] if p['bot_id']=='spy_mr' and p['qty']!=0]
    if len(held)!=1 or held[0]['symbol']!='SPY' or held[0]['qty']!=qty or held[0]['avg_price']!=state.get('entry_price'):raise ValueError('Command Center holding differs')
    working=[o for o in tables['orders'] if o['bot_id']=='spy_mr' and str(o['status']).lower() not in TERMINAL]
    exits=[o for o in working if (o['symbol'],o['side'],o['qty'],o['type'],o['broker_order_id'])==('SPY','SELL',qty,'MOC',pend['order_id'])]
    stops=[o for o in working if (o['symbol'],o['side'],o['qty'],o['type'],o['broker_order_id'])==('SPY','SELL',qty,'STOP',state['stop_order_id'])]
    if len(working)!=2 or len(exits)!=1 or len(stops)!=1 or any(str(o['status']).lower() not in ACTIVE for o in working):raise ValueError('Working exit/stop records are ambiguous')
    if any(f['order_id'] in {exits[0]['id'],stops[0]['id']} for f in tables['fills']):raise ValueError('Order already has recorded fills')
    return stops[0],exits[0]


def receipt_path(repo,receipt):
    path=Path(receipt).resolve(strict=False)
    if path.parent!=(repo/'var/backups').resolve(strict=True) or not path.name.startswith('paper-exit-') or path.suffix!='.json':raise ValueError('Unexpected paper exit receipt path')
    return base.safe_target(repo,path.relative_to(repo).as_posix())


def prepare(repo,receipt,*,fetcher=base.fetch):
    repo=Path(repo).resolve(strict=True);base.health_identity(repo,fetcher)
    path=receipt_path(repo,receipt)
    if path.exists():raise ValueError('Receipt already exists')
    with connect(repo) as db:
        db.execute('BEGIN')
        before,raw,state,paper=evidence(repo,db)
        stop,exit_order=validate_proof(before,state,paper)
        if base.safe_target(repo,STATE).read_bytes()!=raw or base.digest(base.safe_target(repo,PAPER).read_bytes())!=before['paper_hash']:raise ValueError('Paper files changed during preflight')
    after=(json.dumps({**state,'stop_order_id':None},indent=2)+'\n').encode()
    saved={'version':1,'repo':str(repo),'state':'prepared','at':datetime.now(timezone.utc).isoformat(),'before':before,
           'original_state':base64.b64encode(raw).decode(),'updated_state':base64.b64encode(after).decode(),
           'stop_order_id':stop['id'],'pending_exit_order_id':exit_order['id'],
           'new_reason':str(stop.get('reason') or '')+' '+NOTE+' Receipt: '+path.name}
    base.atomic(path,(json.dumps(saved,indent=2)+'\n').encode())
    return {'ok':True,'receipt':str(path),'stop_order_id':stop['id'],'pending_exit_order_id':exit_order['id'],'scope':'STALE_LOCAL_PAPER_STOP_METADATA_ONLY'}


def load(repo,receipt):
    path=receipt_path(repo,receipt)
    saved=json.loads(path.read_text())
    if saved.get('version')!=1 or saved.get('repo')!=str(repo):raise ValueError('Receipt identity differs')
    old=base64.b64decode(saved['original_state'],validate=True);new=base64.b64decode(saved['updated_state'],validate=True)
    if base.digest(old)!=saved['before']['state_hash'] or json.loads(new)!={**json.loads(old),'stop_order_id':None}:raise ValueError('Receipt state scope differs')
    return path,saved,old,new


def after_matches(repo,db,saved,new,path):
    current,raw,_,_=evidence(repo,db)
    if raw!=new or current['paper_hash']!=saved['before']['paper_hash'] or current['flags']!=saved['before']['flags']:return False
    expected=json.loads(json.dumps(saved['before']['tables']))
    for row in expected['orders']:
        if row['id']==saved['stop_order_id']:row.update(status='cancelled',reason=saved['new_reason'])
    audits=[row for row in current['tables']['controls'] if row not in expected['controls']]
    if len(audits)!=1 or audits[0]['action']!=ACTION or audits[0]['target']!='spy_mr' or audits[0]['note']!=NOTE+' Receipt: '+path.name:return False
    expected['controls'].append(audits[0])
    return current['tables']==expected


def apply(repo,receipt,*,fetcher=base.fetch):
    repo=Path(repo).resolve(strict=True);base.health_identity(repo,fetcher)
    path,saved,old,new=load(repo,receipt)
    db=connect(repo,False);wrote_state=False;committed=False
    try:
        db.execute('BEGIN IMMEDIATE')
        if after_matches(repo,db,saved,new,path):
            db.rollback()
            saved['state']='applied';base.atomic(path,(json.dumps(saved,indent=2)+'\n').encode())
            return {'ok':True,'already_applied':True,'receipt':str(path)}
        current,raw,state,paper=evidence(repo,db)
        if raw not in (old,new):raise ValueError('Paper bot state changed after preflight')
        original=json.loads(old.decode('utf-8-sig'))
        stop,exit_order=validate_proof(current,original,paper)
        compare={**current,'state_hash':base.digest(old)}
        if compare!=saved['before'] or stop['id']!=saved['stop_order_id'] or exit_order['id']!=saved['pending_exit_order_id']:raise ValueError('Runtime evidence changed after preflight')
        writes={sqlite3.SQLITE_INSERT,sqlite3.SQLITE_UPDATE,sqlite3.SQLITE_DELETE,sqlite3.SQLITE_CREATE_TABLE,sqlite3.SQLITE_ALTER_TABLE,sqlite3.SQLITE_DROP_TABLE}
        def authorize(action,table,column,*rest):
            if action not in writes:return sqlite3.SQLITE_OK
            allowed=(action==sqlite3.SQLITE_UPDATE and table=='orders' and column in {'status','reason'}) or (action==sqlite3.SQLITE_INSERT and table=='controls')
            return sqlite3.SQLITE_OK if allowed else sqlite3.SQLITE_DENY
        db.set_authorizer(authorize)
        base.atomic(base.safe_target(repo,STATE),new);wrote_state=True
        changed=db.execute("UPDATE orders SET status='cancelled',reason=? WHERE id=? AND status=? AND broker_order_id=?",(saved['new_reason'],stop['id'],stop['status'],stop['broker_order_id']))
        if changed.rowcount!=1:raise ValueError('Stop record changed before update')
        db.execute('INSERT INTO controls(at,actor,action,target,before_json,after_json,note) VALUES(?,?,?,?,?,?,?)',
                   (datetime.now(timezone.utc).isoformat(),'paper-metadata-maintenance',ACTION,'spy_mr',json.dumps({'stop_order_id':stop['id'],'status':stop['status']}),
                    json.dumps({'stop_order_id':stop['id'],'status':'cancelled','pending_exit_order_id':exit_order['id'],'receipt':path.name}),NOTE+' Receipt: '+path.name))
        if base.digest(base.safe_target(repo,PAPER).read_bytes())!=saved['before']['paper_hash']:raise ValueError('Paper queue changed during repair')
        if not after_matches(repo,db,saved,new,path):raise ValueError('Unexpected write during metadata repair; transaction rolled back')
        db.commit();committed=True
        saved['state']='applied';base.atomic(path,(json.dumps(saved,indent=2)+'\n').encode())
    except Exception:
        if not committed:
            db.rollback()
            if wrote_state and base.safe_target(repo,STATE).read_bytes()==new:base.atomic(base.safe_target(repo,STATE),old)
        raise
    finally:db.close()
    return verify(repo,receipt,fetcher=fetcher)


def verify(repo,receipt,*,fetcher=base.fetch):
    repo=Path(repo).resolve(strict=True);base.health_identity(repo,fetcher)
    path,saved,old,new=load(repo,receipt)
    with connect(repo) as db:
        db.execute('BEGIN')
        if not after_matches(repo,db,saved,new,path):raise ValueError('Paper metadata repair has not been verified')
    return {'ok':True,'receipt':str(path),'scope':'STALE_LOCAL_PAPER_STOP_METADATA_ONLY','retired_stop_order_id':saved['stop_order_id'],
            'pending_exit_order_id':saved['pending_exit_order_id'],'position':'retained','paper_queue':'unchanged','fills_submitted':0,'broker_commands':0}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','apply','verify']);parser.add_argument('--repo',type=Path,required=True);parser.add_argument('--receipt',type=Path,required=True);args=parser.parse_args()
    try:print(json.dumps(globals()[args.action](args.repo,args.receipt)))
    except Exception as error:
        print(json.dumps({'ok':False,'error':type(error).__name__,'detail':str(error),'receipt':str(args.receipt)}));raise SystemExit(1)
