"""Bind operations recovery to an existing options-only paper fleet; no financial writes."""
import argparse
from contextlib import closing
from datetime import datetime,timezone
import importlib.util
import json
from pathlib import Path
import sqlite3
import uuid

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('operations_policy',ROOT/'OPTIONS-ONLY.py')
policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)
base=policy.base


def prepare(repo):
    repo=Path(repo).resolve(strict=True)
    observed=base.evidence(repo)
    _,flags=policy.regular_controls(repo)
    if 'OPTIONS_ONLY' not in flags or any(bot+'.pause' not in flags for bot in policy.STOCKS):
        raise ValueError('Options-only restriction and all four stock pauses must already exist')
    with closing(sqlite3.connect((repo/'var/cc.db').as_uri()+'?mode=ro',uri=True,timeout=1)) as db:
        bots=db.execute('SELECT id,mode FROM bots').fetchall()
    if len(bots)!=5 or {b[0] for b in bots}!=policy.BOTS or any(b[1]!='paper' for b in bots):
        raise ValueError('Expected exactly the registered paper fleet')
    receipt=base.safe_target(repo,'var/backups/operations-repair-'+uuid.uuid4().hex+'.json')
    saved={'repo':str(repo),'at':datetime.now(timezone.utc).isoformat(),'state':'prepared',
           'original_flags':flags,'observations':observed,'scope':'OPERATIONS_RECOVERY_ONLY'}
    base.atomic(receipt,(json.dumps(saved,indent=2)+'\n').encode())
    return {'ok':True,'paper_fleet':True,'receipt':str(receipt)}


def verify(repo,receipt,*,fetcher=policy.fetch,after=None):
    repo=Path(repo).resolve(strict=True);receipt=Path(receipt).resolve(strict=True)
    if receipt.parent!=repo/'var/backups' or not receipt.name.startswith('operations-repair-') or receipt.suffix!='.json':
        raise ValueError('Unexpected operations receipt path')
    saved=json.loads(base.safe_target(repo,receipt.relative_to(repo).as_posix()).read_text())
    if saved.get('repo')!=str(repo):raise ValueError('Receipt repository differs')
    _,flags=policy.regular_controls(repo)
    if any(flags.get(name)!=value for name,value in saved['original_flags'].items()):
        raise ValueError('Existing control changed; retain the receipt and review')
    activity=policy.report(repo,fetcher)
    if activity.get('entry_policy',{}).get('options_only') is not True or any(b['id'] in policy.STOCKS and b.get('entry_state')=='clear' for b in activity['bots']):
        raise ValueError('Options-only controls are not verified')
    incident=json.loads(fetcher('/api/incidents?limit=1'));monitor=incident.get('monitor',{})
    stamp=datetime.fromisoformat(monitor.get('last_completed_at') or '')
    if (monitor.get('status')!='checking' or monitor.get('errors') or
        not 0 <= (datetime.now(timezone.utc)-stamp).total_seconds() <= 90 or stamp<max(datetime.fromisoformat(saved['at']),datetime.fromisoformat(after) if after else datetime.fromisoformat(saved['at']))):
        raise ValueError('A fresh completed monitor check is still required')
    saved.update(state='verified',monitor=monitor)
    base.atomic(receipt,(json.dumps(saved,indent=2)+'\n').encode())
    return {'ok':True,'scope':'OPERATIONS_RECOVERY_AND_DISPLAY','options_only':True,'monitor':monitor,
            'unresolved_incidents':incident.get('open_count'),'holdings':activity.get('summary',{}).get('open_positions'),
            'orders_submitted_by_repair':0,'receipt':str(receipt),
            'next_step':'Refresh with Ctrl+F5. Prior incidents are retained; recovered position warnings need two advancing healthy checks.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','verify'])
    parser.add_argument('--repo',type=Path,required=True);parser.add_argument('--receipt',type=Path);parser.add_argument('--after');args=parser.parse_args()
    try:
        print(json.dumps(prepare(args.repo) if args.action=='prepare' else verify(args.repo,args.receipt,after=args.after)))
    except Exception as error:
        print(json.dumps({'ok':False,'error':str(error),'receipt':str(args.receipt) if args.receipt else None}))
        raise SystemExit(1)
