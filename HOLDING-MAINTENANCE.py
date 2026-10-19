"""Read-only gate for an observation/paused-scanner repair with one existing paper holding.

The full accounting installer retains its flat-account guard. This helper never
imports a bot, sends an order, refreshes a quote or writes the financial ledger.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BOTS={"spy_mr","sip_orb","gap_go","gap_go_spread","nr7"}
PROTECTED=("positions","orders","fills","trades","controls","limits","option_trades","journal","trade_costs")
ET=ZoneInfo("America/New_York")


def maintenance_time(now=None):
    now=(now or datetime.now(ET)).astimezone(ET)
    if 560 <= now.hour*60+now.minute < 975:
        raise ValueError("Install before 09:20 ET or after 16:15 ET; bot commands must be idle")


def regular_bytes(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Missing or unsafe runtime file: "+path.name)
    return path.read_bytes()


def runtime_snapshot(root):
    root=Path(root).resolve(strict=True)
    runtime=root/"var"
    if os.environ.get("CC_VAR") and Path(os.environ['CC_VAR']).resolve()!=runtime:
        raise ValueError("Custom CC_VAR requires a separately reviewed installation")
    pause=runtime/"control/PAUSE_ENTRIES"
    regular_bytes(pause)
    records={}; history={}; holding=None
    database=runtime/"cc.db"
    if database.is_symlink(): raise ValueError("Unsafe ledger")
    with sqlite3.connect(database.resolve(strict=True).as_uri()+"?mode=ro",uri=True,timeout=3) as db:
        db.row_factory=sqlite3.Row
        db.execute("PRAGMA query_only=ON"); db.execute("BEGIN")
        bots=[dict(row) for row in db.execute("SELECT id,mode FROM bots ORDER BY id")]
        if len(bots)!=5 or {b['id'] for b in bots}!=BOTS or any(b['mode']!='paper' for b in bots):
            raise ValueError("Expected exactly five paper bots")
        positions=[dict(p) for p in db.execute("SELECT * FROM positions WHERE qty<>0")]
        active=[dict(p) for p in db.execute("SELECT * FROM orders WHERE status IN ('sent','submitted','pending','open','partially_filled')")]
        if positions:
            p=positions[0]
            if len(positions)!=1 or p['bot_id']!='spy_mr' or p['symbol']!='SPY' or type(p['qty']) is not int or p['qty']<=0:
                raise ValueError("Only one existing long SPY paper holding is supported")
            if len(active)!=1: raise ValueError("Unresolved orders or missing SPY stop; preserve and reconcile")
            stop=active[0]
            price=stop.get('stop_price')
            if any(stop.get(k)!=v for k,v in {'bot_id':'spy_mr','symbol':'SPY','side':'SELL','qty':p['qty'],'type':'STOP','broker_order_id':'paper-stop-SPY'}.items()) or type(price) not in (float,int) or not math.isfinite(price) or price<=0:
                raise ValueError("SPY stop does not match the holding")
            folder=root/'bots/spy_mr_bot'
            state=json.loads(regular_bytes(folder/'state_paper.json'))
            paper=json.loads(regular_bytes(folder/'paper_ledger.json'))
            if (not isinstance(state,dict) or state.get('in_position') is not True or state.get('qty')!=p['qty'] or state.get('pending') is not None or state.get('stop_order_id')!='paper-stop-SPY'):
                raise ValueError("Daily state does not match the holding")
            if not isinstance(paper,dict) or paper.get('pending')!=[] or paper.get('positions',{}).get('SPY')!=p['qty']:
                raise ValueError("Daily paper ledger does not match the holding")
            if any(qty!=0 for symbol,qty in paper['positions'].items() if symbol!='SPY') or paper.get('stops',{}).get('SPY')!={'qty':p['qty'],'stop':price} or set(paper.get('stops',{}))!={'SPY'}:
                raise ValueError("Daily stop or position records are ambiguous")
            holding={k:p[k] for k in ('bot_id','symbol','qty')}
        elif active:
            raise ValueError("Unresolved orders remain; maintenance does not settle or cancel")
        tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in PROTECTED:
            if table in tables:
                records[table]=[dict(row) for row in db.execute('SELECT * FROM "'+table+'" ORDER BY rowid')]
        for table in ('equity','paper_equity'):
            if table in tables:
                maximum=db.execute('SELECT COALESCE(MAX(rowid),0) FROM "'+table+'"').fetchone()[0]
                rows=[dict(r) for r in db.execute('SELECT * FROM "'+table+'" WHERE rowid<=? ORDER BY rowid',(maximum,))]
                history[table]={'maximum':maximum,'digest':hashlib.sha256(json.dumps(rows,sort_keys=True,allow_nan=False).encode()).hexdigest()}
        # Financial settings are protected; moving risk and monitor metadata are not.
        cols={r[1] for r in db.execute("PRAGMA table_info(kv)")}
        if 'value_json' in cols:
            records['financial_settings']=[dict(r) for r in db.execute("SELECT * FROM kv WHERE key LIKE 'paper_account%' ORDER BY key")]
    files={}
    for path in sorted((runtime/'control').rglob('*')):
        if path.is_symlink(): raise ValueError("Unsafe control path")
        if path.is_file(): files[str(path.relative_to(root))]=hashlib.sha256(regular_bytes(path)).hexdigest()
    for folder in sorted((root/'bots').iterdir()):
        if folder.is_dir():
            for name in ('state_paper.json','paper_ledger.json'):
                path=folder/name
                if path.exists(): files[str(path.relative_to(root))]=hashlib.sha256(regular_bytes(path)).hexdigest()
    fingerprint=hashlib.sha256(json.dumps({'records':records,'files':files},sort_keys=True,allow_nan=False).encode()).hexdigest()
    return {'holding':holding,'fingerprint':fingerprint,'history':history}



def history_preserved(root,expected):
    with sqlite3.connect((Path(root)/'var/cc.db').resolve(strict=True).as_uri()+'?mode=ro',uri=True,timeout=3) as db:
        db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        for table,item in expected.items():
            if table not in ('equity','paper_equity'): raise ValueError('Invalid history receipt')
            rows=[dict(r) for r in db.execute('SELECT * FROM "'+table+'" WHERE rowid<=? ORDER BY rowid',(item['maximum'],))]
            if hashlib.sha256(json.dumps(rows,sort_keys=True,allow_nan=False).encode()).hexdigest()!=item['digest']:
                raise ValueError('Existing equity history changed; preserve receipt and investigate')
    return True


def source_stage(root,manifest):
    targets=tuple(manifest['stages']['installed'])
    if any(name.startswith(('bots/','cc_sdk/cc_sdk/paper_account.py','cc_sdk/cc_sdk/ledger.py','cc_sdk/cc_sdk/schema.sql','cc_sdk/cc_sdk/schwab_feed.py')) for name in targets):
        raise ValueError("Maintenance release exceeds observation/scanner scope")
    for name in targets:
        path=root/name
        if path.is_symlink() or any(p.is_symlink() for p in path.parents if p!=root and root in p.parents): raise ValueError("Unsafe source path")
    for name,expected in manifest.get('protected_source',{}).items():
        path=root/name
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest()!=expected:
            raise ValueError('Installed SDK/schema or daily bot source differs from the reviewed maintenance base: '+name)
    for args in (['diff','--cached','--name-only'],['status','--porcelain','--untracked-files=all','--ignored=matching','--',*targets]):
        result=subprocess.run(['git',*args],cwd=root,capture_output=True,check=True)
        if result.stdout: raise ValueError("Repair source or Git index has local changes; preserve them")
    actual={name:hashlib.sha256((root/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest() if (root/name).is_file() else None for name in targets}
    stage=next((key for key,value in manifest['stages'].items() if value==actual),None)
    if stage is None: raise ValueError("Unexpected maintenance source; preserve the checkout")
    return stage


def check(root,now=None):
    maintenance_time(now)
    root=Path(root).resolve(strict=True)
    manifest=json.loads(Path(__file__).with_name('HOLDING-MAINTENANCE-SOURCE.json').read_text())
    stage=source_stage(root,manifest)
    return {'ok':True,'source':stage,**runtime_snapshot(root)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repo',type=Path);parser.add_argument('--preserve',type=Path);args=parser.parse_args()
    try:
        result=check(args.repo)
        if args.preserve:
            previous=json.loads(args.preserve.read_text(encoding='utf-8-sig'))
            if previous['fingerprint']!=result['fingerprint']: raise ValueError('Financial records or controls changed')
            history_preserved(args.repo,previous['history'])
        print(json.dumps(result))
    except Exception as error:
        print(json.dumps({'ok':False,'error':str(error)}));raise SystemExit(1)
