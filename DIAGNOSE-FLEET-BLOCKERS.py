"""Read-only local API, controls and SIP evidence; no strategy/provider imports."""
from __future__ import annotations
import argparse
from contextlib import closing
from datetime import datetime,timezone
import importlib.util
import json
from pathlib import Path
import sqlite3
import urllib.request


def request(route):
    with urllib.request.urlopen('http://127.0.0.1:8585/api/'+route,timeout=5) as response:
        value=json.loads(response.read(262144))
        if not isinstance(value,dict):raise ValueError('Unexpected API payload')
        return value


def capture(root):
    root=Path(root).resolve(strict=True)
    result={'at':datetime.now(timezone.utc).isoformat(),'scope':'READ_ONLY','repo':str(root),'api_errors':{}}
    payloads={}
    for route in ('health','readiness','risk','incidents?limit=20'):
        try:payloads[route]=request(route)
        except Exception as error:payloads[route]={};result['api_errors'][route]=type(error).__name__
    result['health']=payloads['health'];result['readiness']=payloads['readiness']
    risk=payloads['risk'];result['risk']={key:risk.get(key) for key in ('entries_paused','killed','drawdown','limits','exposure')}
    incidents=payloads['incidents?limit=20']
    result['incidents']={'monitor':incidents.get('monitor'),'open_count':incidents.get('open_count'),
        'open':[{key:row.get(key) for key in ('id','condition','scope','session_date','state','last_at','good_count','evidence','next_step')} for row in incidents.get('open',[])]}
    path=Path(__file__).with_name('CHECK-OPEN-READINESS.py')
    spec=importlib.util.spec_from_file_location('diagnostic_readiness',path)
    checker=importlib.util.module_from_spec(spec);spec.loader.exec_module(checker)
    try:checker.verify_ledger_identity(payloads['health'],root/'var/cc.db');result['ledger_identity']='MATCH'
    except Exception as error:result['ledger_identity']=str(error)
    flags=[]
    for path in sorted((root/'var/control').iterdir()):
        if path.is_file() and (path.name in ('PAUSE_ENTRIES','KILL') or path.name.endswith(('.pause','.kill','.flatten'))):
            try:value=json.loads(path.read_text(encoding='utf-8-sig'))
            except Exception:value={}
            flags.append({'flag':path.name,**{key:value.get(key) for key in ('at','actor','reason')}})
    result['controls']=flags
    try:
        with closing(sqlite3.connect((root/'var/cc.db').resolve(strict=True).as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
            db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            result['sip_heartbeats']=[dict(row) for row in db.execute("SELECT run,at,ok,detail FROM heartbeats WHERE bot_id='sip_orb' ORDER BY id DESC LIMIT 5")]
            result['sip_decisions']=[dict(row) for row in db.execute("SELECT at,action,reason FROM decisions WHERE bot_id='sip_orb' AND action IN ('UNIVERSE','SCANNER_UNAVAILABLE') ORDER BY id DESC LIMIT 5")]
    except (OSError,sqlite3.Error) as error:result['ledger_read_error']=type(error).__name__
    result['fleet_entries_paused']=bool(any(f['flag']=='PAUSE_ENTRIES' for f in flags) or risk.get('entries_paused') is True)
    result['collection_complete']=not result['api_errors'] and result['ledger_identity']=='MATCH' and 'ledger_read_error' not in result and type(risk.get('entries_paused')) is bool
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--repo',required=True,type=Path);args=parser.parse_args()
    result=capture(args.repo);print(json.dumps(result,indent=2,default=str))
    raise SystemExit(0 if result['collection_complete'] else 2)
