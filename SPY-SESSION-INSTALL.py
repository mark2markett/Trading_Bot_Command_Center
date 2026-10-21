"""Install the reviewed SPY pending-session guard only. No shared code or financial writes."""
from __future__ import annotations
import argparse
import base64
import importlib.util
import json
from pathlib import Path
import sqlite3
import uuid

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('spy_session_source_base',ROOT/'INSTALL-ACTIVITY-DASHBOARD.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
TARGET='bots/spy_mr_bot/bot.py'
PAPER_FILES=('bots/spy_mr_bot/state_paper.json','bots/spy_mr_bot/paper_ledger.json')
BOTS={'spy_mr','gap_go','gap_go_spread','nr7','sip_orb'}


def observe(repo):
    path=base.safe_target(repo,'var/cc.db').resolve(strict=True)
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=3);db.row_factory=sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        bots=[dict(r) for r in db.execute('SELECT id,mode FROM bots ORDER BY id')]
        if len(bots)!=5 or {r['id'] for r in bots}!=BOTS or any(r['mode']!='paper' for r in bots):raise ValueError('Expected five paper bots')
        rows={t:[dict(r) for r in db.execute('SELECT * FROM '+t+' WHERE bot_id=? ORDER BY rowid',('spy_mr',))] for t in ('positions','orders','fills','trades')}
    finally:db.close()
    folder=base.safe_target(repo,'var/control/.spy-source-check').parent
    flags={}
    for p in folder.iterdir():
        if p.is_symlink() or not p.is_file():raise ValueError('Unsafe control path')
        flags[p.name]=base.digest(p.read_bytes())
    if not {'OPTIONS_ONLY','spy_mr.pause','gap_go.pause','nr7.pause','sip_orb.pause'}<=flags.keys():raise ValueError('Options-only share pauses required')
    files={};status={}
    for name in PAPER_FILES:
        raw=base.safe_target(repo,name).read_bytes();files[name]=base.digest(raw)
        if name.endswith('state_paper.json'):
            state=json.loads(raw.decode('utf-8-sig'))
            if not isinstance(state,dict):raise ValueError('Saved SPY state must be an object')
            status={key:state.get(key) for key in ('in_position','qty','pending','stop_order_id','last_decide','last_reconcile')}
    return {'bots':bots,'spy_rows':rows,'paper_files':files,'flags':flags,'saved_state':status}


def saved_receipt(repo,receipt,manifest):
    path=Path(receipt).resolve(strict=True)
    if path.parent!=(repo/'var/backups').resolve(strict=True) or not path.name.startswith('spy-session-') or path.suffix!='.json':raise ValueError('Unexpected SPY source receipt path')
    saved=json.loads(base.safe_target(repo,path.relative_to(repo).as_posix()).read_text())
    old=base64.b64decode(saved['original'],validate=True)
    if saved['repo']!=str(repo) or saved['target']!=TARGET or saved['new_hash']!=manifest['files'][TARGET] or base.digest(old)!=saved['old_hash']:raise ValueError('SPY source receipt identity differs')
    return path,saved,old


def prepare(repo,package=ROOT,*,fetcher=base.fetch):
    repo=Path(repo).resolve(strict=True);manifest,payload=base.read_package(Path(package));base.health_identity(repo,fetcher)
    target=base.safe_target(repo,TARGET);old=target.read_bytes()
    if base.normalized(old) not in {manifest['compatible'][TARGET],base.normalized(payload[TARGET])}:raise ValueError('SPY source differs from reviewed versions')
    before=observe(repo)
    receipt=base.safe_target(repo,'var/backups/spy-session-'+uuid.uuid4().hex+'.json')
    saved={'repo':str(repo),'target':TARGET,'old_hash':base.digest(old),'new_hash':manifest['files'][TARGET],
           'original':base64.b64encode(old).decode(),'before':before,'state':'prepared'}
    base.atomic(receipt,(json.dumps(saved,indent=2)+'\n').encode())
    return {'ok':True,'receipt':str(receipt),'scope':'SPY_BOT_SOURCE_ONLY'}


def apply(repo,package,receipt,*,fetcher=base.fetch):
    repo=Path(repo).resolve(strict=True);manifest,payload=base.read_package(Path(package));base.health_identity(repo,fetcher)
    path,saved,old=saved_receipt(repo,receipt,manifest);target=base.safe_target(repo,TARGET);current=target.read_bytes()
    if current not in (old,payload[TARGET]):raise ValueError('SPY source changed after preflight')
    if observe(repo)!=saved['before']:raise ValueError('SPY state or controls changed after preflight; retry while SPY is idle')
    already=current==payload[TARGET]
    if not already:base.atomic(target,payload[TARGET])
    saved['state']='applied';base.atomic(path,(json.dumps(saved,indent=2)+'\n').encode())
    return {**verify(repo,package,receipt,fetcher=fetcher),'already_installed':already}


def verify(repo,package,receipt,*,fetcher=base.fetch):
    repo=Path(repo).resolve(strict=True);manifest,payload=base.read_package(Path(package));base.health_identity(repo,fetcher)
    path,saved,_=saved_receipt(repo,receipt,manifest)
    if base.safe_target(repo,TARGET).read_bytes()!=payload[TARGET]:raise ValueError('SPY source readback differs')
    if observe(repo)!=saved['before']:raise ValueError('SPY state advanced during verification; source retained, inspect receipt')
    return {'ok':True,'scope':'SPY_BOT_SOURCE_ONLY','receipt':str(path),'financial_writes':0,'server_restarted':False,
            'shared_code_changed':False,'bot_commands_started':0,'paper_state':'unchanged','spy_status':saved['before']['saved_state'],
            'next_step':'Future SPY reconcile requires exactly the saved pending session bar. Shared runtime/display update remains deferred until all bot commands are idle.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('prepare','apply','verify'));parser.add_argument('--repo',type=Path,required=True);parser.add_argument('--receipt',type=Path);args=parser.parse_args()
    try:
        result=prepare(args.repo) if args.action=='prepare' else globals()[args.action](args.repo,ROOT,args.receipt)
        print(json.dumps(result))
    except Exception as error:
        print(json.dumps({'ok':False,'error':type(error).__name__,'detail':str(error)}));raise SystemExit(1)
