"""Audited correction of a proven absent local paper stop. Never settles or submits."""
from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import math
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
CLOSED_NOTE='Closed paper position and completed sale verified; stale local stop metadata retired; fills and P&L preserved; no broker command issued.'

def note(saved):
    return CLOSED_NOTE if saved.get('closed') is True else NOTE



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


def closed_proof(before,state,paper):
    tables=before['tables']
    if state.get('in_position') is not False or type(state.get('qty')) is not int or state['qty']!=0 or state.get('pending') is not None or state.get('stop_order_id') is not None:
        raise ValueError('Saved paper state is not flat with no pending exit or stop')
    if not isinstance(paper.get('positions'),dict) or not isinstance(paper.get('stops'),dict) or paper['positions'].get('SPY',0)!=0 or 'SPY' in paper['stops'] or paper.get('pending')!=[]:
        raise ValueError('Paper execution registry is not flat, idle and without a SPY stop')
    if any(p['bot_id']=='spy_mr' and p['qty']!=0 for p in tables['positions']):raise ValueError('Native SPY bot still has a holding')
    orders=[o for o in tables['orders'] if o['bot_id']=='spy_mr']
    working=[o for o in orders if str(o['status']).lower() not in TERMINAL]
    if len(working)!=1:raise ValueError('Expected one orphaned paper stop only')
    stop=working[0];qty=stop['qty']
    if type(qty) is not int or qty<=0 or (stop['symbol'],stop['side'],stop['type'],stop['broker_order_id'])!=('SPY','SELL','STOP','paper-stop-SPY') or str(stop['status']).lower() not in ACTIVE:
        raise ValueError('Orphaned paper stop identity differs')
    if any(f['order_id']==stop['id'] for f in tables['fills']):raise ValueError('Stop has recorded fills')
    fills=paper.get('fills')
    if not isinstance(fills,list) or not fills or not isinstance(fills[-1],dict):raise ValueError('Paper execution evidence missing')
    settled=fills[-1]
    if (settled.get('kind'),settled.get('symbol'),settled.get('qty'))!=('SELL_MOC','SPY',qty) or not str(settled.get('id','')).startswith('paper-'):
        raise ValueError('Most recent paper execution is not the full-position sale')
    session=date.fromisoformat(settled['date'])
    queued=datetime.fromisoformat(settled['queued'].replace('Z','+00:00'))
    if queued.tzinfo is None or queued.astimezone(ZoneInfo('America/New_York')).date()!=session:raise ValueError('Completed paper sale session differs')
    if type(settled.get('fill')) not in (int,float) or not math.isfinite(settled['fill']) or settled['fill']<=0:raise ValueError('Invalid paper fill price')
    exits=[o for o in orders if (o['symbol'],o['side'],o['type'],o['qty'],o['broker_order_id'],str(o['status']).lower())==('SPY','SELL','MOC',qty,settled['id'],'filled')]
    if len(exits)!=1 or exits[0]['id']<=stop['id']:raise ValueError('Completed native sale identity differs')
    exit_order=exits[0]
    exit_stamp=datetime.fromisoformat(exit_order['at'].replace('Z','+00:00'))
    if exit_stamp.tzinfo is None or exit_stamp.astimezone(ZoneInfo('America/New_York')).date()!=session:raise ValueError('Native and paper exit sessions differ')
    def average(order):
        rows=[f for f in tables['fills'] if f['order_id']==order['id']]
        if not rows or any(f['bot_id']!='spy_mr' or type(f['qty']) is not int or f['qty']<=0 or type(f.get('price')) not in (int,float) or not math.isfinite(f['price']) or f['price']<=0 for f in rows) or sum(f['qty'] for f in rows)!=qty:
            raise ValueError('Complete native fill evidence missing or ambiguous')
        return sum(f['qty']*f['price'] for f in rows)/qty
    exit_price=average(exit_order)
    trades=[t for t in tables['trades'] if t.get('bot_id')=='spy_mr' and t.get('qty')==qty and t.get('exit_at')==session.isoformat() and t.get('exit_px')==exit_price]
    if len(trades)!=1:raise ValueError('Completed native trade is missing or ambiguous')
    trade=trades[0]
    entries=[o for o in orders if o['id']<stop['id'] and (o['symbol'],o['side'],o['type'],o['qty'],str(o['status']).lower())==('SPY','BUY','MOC',qty,'filled') and str(o['broker_order_id'] or '').startswith('paper-')]
    if not entries:raise ValueError('Paper entry order missing')
    entry=max(entries,key=lambda o:o['id'])
    entered=datetime.fromisoformat(entry['at'].replace('Z','+00:00'))
    if entered.tzinfo is None or entered.astimezone(ZoneInfo('America/New_York')).date().isoformat()!=trade['entry_at']:raise ValueError('Entry session and closed trade differ')
    if average(entry)!=trade['entry_px'] or not math.isclose(trade['pnl'],(exit_price-trade['entry_px'])*qty,abs_tol=0.000001,rel_tol=0):raise ValueError('Recorded closed trade and fills disagree')
    return stop,exit_order,{'id':trade['id'],'qty':qty,'entry_price':trade['entry_px'],'exit_price':exit_price,'pnl':trade['pnl'],'exit_session':session.isoformat(),
                            'paper_exit_price':settled['fill'],'pnl_basis':'Recorded native P&L preserved; simulator slippage/charges are not repriced by this correction.'}


def validate_proof(before,state,paper,closed=False):
    tables=before['tables'];bots=tables['bots']
    if len(bots)!=5 or {b['id'] for b in bots}!=BOTS or any(b['mode']!='paper' for b in bots):raise ValueError('Expected five paper bots')
    if not {'OPTIONS_ONLY','spy_mr.pause','gap_go.pause','nr7.pause','sip_orb.pause'}<=before['flags'].keys():raise ValueError('Options-only share restrictions must remain present')
    if closed:return closed_proof(before,state,paper)[:2]
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


def prepare(repo,receipt,*,fetcher=base.fetch,closed=False):
    repo=Path(repo).resolve(strict=True);base.health_identity(repo,fetcher)
    path=receipt_path(repo,receipt)
    if path.exists():raise ValueError('Receipt already exists')
    with connect(repo) as db:
        db.execute('BEGIN')
        before,raw,state,paper=evidence(repo,db)
        stop,exit_order=validate_proof(before,state,paper,closed)
        if base.safe_target(repo,STATE).read_bytes()!=raw or base.digest(base.safe_target(repo,PAPER).read_bytes())!=before['paper_hash']:raise ValueError('Paper files changed during preflight')
    after=raw if closed else (json.dumps({**state,'stop_order_id':None},indent=2)+'\n').encode()
    closure=closed_proof(before,state,paper)[2] if closed else None
    saved={'version':1,'closed':closed,'closed_trade':closure,'repo':str(repo),'state':'prepared','at':datetime.now(timezone.utc).isoformat(),'before':before,
           'original_state':base64.b64encode(raw).decode(),'updated_state':base64.b64encode(after).decode(),
           'stop_order_id':stop['id'],'pending_exit_order_id':exit_order['id'],
           'new_reason':str(stop.get('reason') or '')+' '+(CLOSED_NOTE if closed else NOTE)+' Receipt: '+path.name}
    base.atomic(path,(json.dumps(saved,indent=2)+'\n').encode())
    return {'ok':True,'receipt':str(path),'stop_order_id':stop['id'],('completed_exit_order_id' if closed else 'pending_exit_order_id'):exit_order['id'],'scope':'STALE_LOCAL_PAPER_STOP_METADATA_ONLY','closed_trade':closure}


def load(repo,receipt):
    path=receipt_path(repo,receipt)
    saved=json.loads(path.read_text())
    if saved.get('version')!=1 or saved.get('repo')!=str(repo):raise ValueError('Receipt identity differs')
    old=base64.b64decode(saved['original_state'],validate=True);new=base64.b64decode(saved['updated_state'],validate=True)
    if type(saved.get('closed',False)) is not bool:raise ValueError('Receipt mode differs')
    if base.digest(old)!=saved['before']['state_hash'] or (new!=old if saved.get('closed') else json.loads(new)!={**json.loads(old),'stop_order_id':None}):raise ValueError('Receipt state scope differs')
    if saved.get('closed'):
        _,paper=read_file(repo,PAPER)
        if closed_proof(saved['before'],json.loads(old.decode('utf-8-sig')),paper)[2]!=saved.get('closed_trade'):raise ValueError('Closed-trade receipt evidence differs')
    return path,saved,old,new


def after_matches(repo,db,saved,new,path):
    current,raw,_,_=evidence(repo,db)
    if raw!=new or current['paper_hash']!=saved['before']['paper_hash'] or current['flags']!=saved['before']['flags']:return False
    expected=json.loads(json.dumps(saved['before']['tables']))
    for row in expected['orders']:
        if row['id']==saved['stop_order_id']:row.update(status='cancelled',reason=saved['new_reason'])
    audits=[row for row in current['tables']['controls'] if row not in expected['controls']]
    if len(audits)!=1 or audits[0]['action']!=ACTION or audits[0]['target']!='spy_mr' or audits[0]['note']!=note(saved)+' Receipt: '+path.name:return False
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
        stop,exit_order=validate_proof(current,original,paper,saved.get('closed',False))
        compare={**current,'state_hash':base.digest(old)}
        if compare!=saved['before'] or stop['id']!=saved['stop_order_id'] or exit_order['id']!=saved['pending_exit_order_id']:raise ValueError('Runtime evidence changed after preflight')
        writes={sqlite3.SQLITE_INSERT,sqlite3.SQLITE_UPDATE,sqlite3.SQLITE_DELETE,sqlite3.SQLITE_CREATE_TABLE,sqlite3.SQLITE_ALTER_TABLE,sqlite3.SQLITE_DROP_TABLE}
        def authorize(action,table,column,*rest):
            if action not in writes:return sqlite3.SQLITE_OK
            allowed=(action==sqlite3.SQLITE_UPDATE and table=='orders' and column in {'status','reason'}) or (action==sqlite3.SQLITE_INSERT and table=='controls')
            return sqlite3.SQLITE_OK if allowed else sqlite3.SQLITE_DENY
        db.set_authorizer(authorize)
        if raw!=new:
            base.atomic(base.safe_target(repo,STATE),new);wrote_state=True
        changed=db.execute("UPDATE orders SET status='cancelled',reason=? WHERE id=? AND status=? AND broker_order_id=?",(saved['new_reason'],stop['id'],stop['status'],stop['broker_order_id']))
        if changed.rowcount!=1:raise ValueError('Stop record changed before update')
        db.execute('INSERT INTO controls(at,actor,action,target,before_json,after_json,note) VALUES(?,?,?,?,?,?,?)',
                   (datetime.now(timezone.utc).isoformat(),'paper-metadata-maintenance',ACTION,'spy_mr',json.dumps({'stop_order_id':stop['id'],'status':stop['status']}),
                    json.dumps({'stop_order_id':stop['id'],'status':'cancelled',('completed_exit_order_id' if saved.get('closed') else 'pending_exit_order_id'):exit_order['id'],'receipt':path.name}),note(saved)+' Receipt: '+path.name))
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
            ('completed_exit_order_id' if saved.get('closed') else 'pending_exit_order_id'):saved['pending_exit_order_id'],'position':'flat' if saved.get('closed') else 'retained','closed_trade':saved.get('closed_trade'),'paper_queue':'unchanged','fills_submitted':0,'broker_commands':0}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','apply','verify']);parser.add_argument('--repo',type=Path,required=True);parser.add_argument('--receipt',type=Path,required=True);parser.add_argument('--closed-position',action='store_true');args=parser.parse_args()
    try:
        result=prepare(args.repo,args.receipt,closed=args.closed_position) if args.action=='prepare' else globals()[args.action](args.repo,args.receipt)
        print(json.dumps(result))
    except Exception as error:
        print(json.dumps({'ok':False,'error':type(error).__name__,'detail':str(error),'receipt':str(args.receipt)}));raise SystemExit(1)
