"""Install only compiled overview assets against the already-installed activity API."""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('reviewed_activity_install',ROOT/'INSTALL-ACTIVITY-DASHBOARD.py')
base=importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def install(repo,package,*,fetcher=base.fetch):
    repo=Path(repo).resolve(strict=True)
    manifest,payload=base.read_package(package)
    base.health_identity(repo,fetcher)
    for name in base.SOURCE:
        target=base.safe_target(repo,name)
        if not target.is_file() or base.normalized(target.read_bytes())!=base.normalized(payload[name]):
            raise ValueError('Reviewed activity backend must already be installed; no source changed')
    report=json.loads(fetcher('/api/activity'))
    if report.get('quote_max_age_seconds')!=60 or not isinstance(report.get('summary'),dict) or not isinstance(report.get('bots'),list):
        raise ValueError('Activity API could not be verified; display unchanged')
    prepared=base.prepare(repo,package,fetcher)
    receipt=Path(prepared['receipt'])
    print('Recovery receipt: '+str(receipt),flush=True)
    saved=json.loads((receipt/'receipt.json').read_text())
    saved['scope']='DISPLAY_ONLY'
    base.atomic(receipt/'receipt.json',(json.dumps(saved,indent=2)+'\n').encode())
    previous=(receipt/base.INDEX).read_bytes()
    changed=False
    try:
        for name,value in payload.items():
            if name in base.SOURCE or name==base.INDEX:
                continue
            target=base.safe_target(repo,name)
            target.parent.mkdir(parents=True,exist_ok=True)
            if not target.exists():
                base.atomic(target,value)
            elif target.read_bytes()!=value:
                raise ValueError('Existing asset collision')
        base.atomic(base.safe_target(repo,base.INDEX),payload[base.INDEX]);changed=True
        for name,value in payload.items():
            if name in base.SOURCE:
                continue
            route='/' if name==base.INDEX else '/'+name.removeprefix('cc_web/dist/')
            if fetcher(route)!=value:
                raise ValueError('Served overview differs from reviewed display')
        saved['state']='verified'
        base.atomic(receipt/'receipt.json',(json.dumps(saved,indent=2)+'\n').encode())
        return {'ok':True,'scope':'DISPLAY_ONLY','receipt':str(receipt),
                'server_restarted':False,'source_changed':False,'next_step':'Press Ctrl+F5 to load the rebuilt overview.'}
    except BaseException:
        if changed:
            target=base.safe_target(repo,base.INDEX)
            if target.read_bytes()!=payload[base.INDEX]:
                raise ValueError('Dashboard changed during recovery; preserve receipt: '+str(receipt))
            base.atomic(target,previous)
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(install(args.repo,ROOT)))
